"""Orchestration du scan et contrôle indépendant du catalogue."""

import fcntl
import os
import tempfile
from collections import defaultdict
from itertools import chain
from contextlib import contextmanager
from pathlib import Path

from tools.core.catalog import Catalogue, CatalogueScopeError, InvalidJSON, read_json, write_json
from tools.core.exit_codes import ExitCode
from tools.core.schemas import schemas
from tools.discovery import formats, importer
from tools.discovery.jobs import job_for
from tools.discovery.repos import OID, Git, GitError, check_destinations, select
from tools.index import reports

REFERENCE_FILE = "scan-references.json"


def cache_path(args):
    return args.cache or Path.home() / ".cache" / "opencade-asset-registry" / "mirrors"


def preflight(root, args):
    selected, local_copies = select(root, args)
    check_destinations(root, cache_path(args), getattr(args, "log", None), local_copies)
    for relative in ("catalog", "catalog/assets", "catalog/import-jobs", "generated",
                     "generated/reports", "thumbnails"):
        if (root / relative).is_symlink():
            raise CatalogueScopeError("Lien symbolique interdit dans une destination du scan.")
    return selected


@contextmanager
def directory_lock(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _load_references(root):
    catalogue = Catalogue(root)
    path = catalogue._regular_path(catalogue.path / REFERENCE_FILE)
    if not path.exists():
        return {}
    records = {}
    try:
        document = catalogue.read(path)
        if document["schemaVersion"] != "1.0" or not isinstance(document["references"], list):
            raise ValueError
        for record in document["references"]:
            key = record["name"], record["provider"]
            if (key in records or not isinstance(record["releaseCommits"], list) or
                    not all(OID.fullmatch(commit) for commit in (record["commit"], *record["releaseCommits"]))):
                raise ValueError
            records[key] = record
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidJSON("Historique des commits de référence invalide.") from exc
    return records


def _template(args, copies):
    if args.job is None:
        providers = {copy.provider for copy in copies}
        source_settings = importer.DEFAULT_JOB["sources"]
        provider = next(iter(providers)) if len(providers) == 1 else source_settings["provider"]
        return {**importer.DEFAULT_JOB, "sources": {**source_settings, "provider": provider}}, copies
    job = read_json(args.job)
    if not schemas().validator("import-job").is_valid(job) or "inputs" in job:
        raise InvalidJSON("Le job doit respecter le contrat initial-discovery de la section 6.")
    provider = job["sources"]["provider"]
    if args.provider and args.provider != provider:
        raise InvalidJSON("Les fournisseurs de --job et --provider divergent.")
    selected = [copy for copy in copies if copy.provider == provider and
                (job["sources"]["includeMonorepos"] or copy.role != "game" or len(copy.games) == 1)]
    return job, selected


def _mirror_for(git, copy, cache, fetch, temporary, *, verify=False):
    existing = cache / copy.provider / f"{copy.name}.git"
    if temporary is None or (not fetch and not verify):
        use_cache = cache
    elif verify and (existing.exists() or existing.is_symlink()):
        use_cache = cache
        fetch = False
    else:
        use_cache = temporary
    return git.prepare(copy, use_cache, fetch)


def _repo_report(copies, prepared, errors):
    repositories = {}
    for copy in copies:
        repo = repositories.setdefault(copy.name, {"name": copy.name, "role": copy.role,
                                                    "games": list(copy.games), "copies": []})
        entry = {"provider": copy.provider, "visibility": copy.visibility}
        if copy.key in prepared:
            entry.update(prepared[copy.key][1])
        if copy.key in errors:
            entry["error"] = errors[copy.key]
        repo["copies"].append(entry)
    for repo in repositories.values():
        repo["divergent"] = len({item["commit"] for item in repo["copies"] if "commit" in item}) > 1
        repo["divergentCopies"] = [
            {"provider": item["provider"], "commit": item["commit"]} for item in repo["copies"]
            if repo["divergent"] and "commit" in item
        ]
    return list(repositories.values())


def _scan(root, args, git, cache, temporary, copies, template):
    prepared = {}
    errors = {}
    for copy in copies:
        try:
            mirror = _mirror_for(git, copy, cache, args.fetch, temporary)
            prepared[copy.key] = mirror, git.reference(mirror)
        except GitError as exc:
            errors[copy.key] = str(exc)

    groups = defaultdict(list)
    references = _load_references(root)
    current_commits = {}
    for copy in copies:
        if copy.key not in prepared:
            continue
        mirror, reference = prepared[copy.key]
        head = reference["commit"]
        current_commits[copy.key] = head
        releases = sorted({tag["commit"] for tag in reference["tags"] if tag["commit"] and tag["commit"] != head})
        if not template["sources"]["includeReleases"]:
            releases = []
        for commit in [head, *releases]:
            groups[copy.name, commit].append((copy, mirror, commit != head, reference["date"]))
        references[copy.key] = {"name": copy.name, "provider": copy.provider,
                                **reference, "releaseCommits": releases}

    inputs = [(copy.name, copy.provider, commit)
              for (_, commit), members in groups.items() for copy, *_ in members]
    job_id, job = job_for(template, inputs)
    target = importer.Importer(root, job_id, args.dry_run)
    rows, manifests = [], []
    for (repo, commit), members in sorted(groups.items()):
        mirror = members[0][1]
        head_date = next((date for _, _, release, date in members if not release), None)
        date = head_date or git.run("show", "-s", "--format=%cI", commit, mirror=mirror).decode().strip()
        locations = [(copy, release) for copy, _, release, _ in members]

        def add_blob(path, data, measured, earliest):
            target.import_blob(locations, commit, date, path, data, measured, earliest)

        discovered, build_files = importer.scan_tree(git, mirror, repo, commit, add_blob)
        rows.extend(discovered)
        manifests.extend({"repo": repo, "commit": commit, "path": path} for path in build_files)

    target.reconcile(current_commits)
    active_commits = {(record["name"], commit) for record in references.values()
                      for commit in [record["commit"], *record["releaseCommits"]]}
    scanned = set(groups)
    exceptions = [row for row in rows if row["status"] == "exception"]
    exceptions_path = Catalogue._regular_path(root / "generated" / "reports" / "exceptions.json")
    if exceptions_path.is_file():
        exceptions.extend(row for row in read_json(exceptions_path)
                          if (row["repo"], row["commit"]) in active_commits - scanned)
    exceptions.sort(key=lambda row: (row["repo"], row["commit"], row["path"]))
    if not args.dry_run:
        from tools.index.dedup import duplicates

        target.save(job)
        repositories = _repo_report(copies, prepared, errors)
        previous_exceptions = [row for row in exceptions if (row["repo"], row["commit"]) not in scanned]
        reports.emit(root, repositories, [*rows, *previous_exceptions], exceptions,
                     target.assets.values(), importer.EXCLUSIONS, manifests)
        write_json(root / "generated" / "duplicates.json", duplicates(target.assets.values()))
        write_json(root / "catalog" / REFERENCE_FILE,
                   {"schemaVersion": "1.0", "references": [references[key] for key in sorted(references)]})

    code = ExitCode.IO if errors and not prepared else ExitCode.OK
    return code, {"ok": code == ExitCode.OK, "jobId": job_id, **target.counts(),
                  "scannedCopies": len(prepared), "errors": _repo_report(copies, prepared, errors) if errors else []}


def _inventory(git, mirror, repo, commit, recorded, forgotten):
    # Enumerate the full committed tree before accounting for exclusions.
    with git.batch(mirror) as batch:
        for blob in git.tree(mirror, commit, sizes=False):
            path = blob.path
            kind = formats.extension(path)
            key = repo, commit, path
            if kind not in formats.SUPPORTED:
                continue
            if key in recorded or importer.exclusion(path):
                continue
            if kind in formats.CONDITIONAL and not blob.symlink:
                data = batch.read(blob, importer.MAX_BLOB)
                if data is not None:
                    try:
                        if formats.inspect(path, data) is None:
                            continue
                    except formats.Unreadable:
                        if kind in {"ts", "js"} and not formats.is_generated_code(path, data):
                            continue
            forgotten.append({"repo": repo, "commit": commit, "path": path})


def _verify(root, args, git, cache, temporary, copies):
    references = _load_references(root)
    records = importer.read_assets(root).values()
    catalogue = Catalogue(root)
    sheets = (catalogue.read(path) for path in catalogue.documents("sheets"))
    recorded = {(loc["repo"], loc["commit"], loc["path"])
                for record in chain(records, sheets) for loc in record["files"]["locations"]}
    exceptions = Catalogue._regular_path(root / "generated" / "reports" / "exceptions.json")
    if exceptions.is_file():
        recorded.update((line["repo"], line["commit"], line["path"]) for line in read_json(exceptions))
    forgotten, drift, errors = [], [], []
    checked = set()
    for copy in copies:
        stored = references.get(copy.key)
        if args.fetch:
            try:
                remote_commit, _ = git.remote_head(copy)
                if stored is None or remote_commit != stored["commit"]:
                    drift.append({"name": copy.name, "provider": copy.provider,
                                  "catalogCommit": stored["commit"] if stored else None,
                                  "remoteCommit": remote_commit})
            except GitError as exc:
                errors.append({"name": copy.name, "provider": copy.provider, "error": str(exc),
                               "stage": "remote-head"})
        if stored is None:
            continue
        commits = {stored["commit"], *stored["releaseCommits"]}
        for commit in sorted(commits):
            key = copy.name, commit
            if key in checked:
                continue
            try:
                mirror = _mirror_for(git, copy, cache, args.fetch, temporary, verify=True)
                try:
                    git.run("cat-file", "-e", commit + "^{commit}", mirror=mirror)
                except GitError:
                    if not args.fetch:
                        raise
                    mirror = git.prepare(copy, temporary, True)
                _inventory(git, mirror, copy.name, commit, recorded, forgotten)
                checked.add(key)
            except GitError as exc:
                errors.append({"name": copy.name, "provider": copy.provider, "commit": commit,
                               "error": str(exc), "stage": "inventory"})
    required = {(copy.name, commit) for copy in copies if (record := references.get(copy.key))
                for commit in [record["commit"], *record["releaseCommits"]]}
    code = (ExitCode.CHECK_FAILED if forgotten or drift else
            ExitCode.IO if required - checked or (errors and not checked) else ExitCode.OK)
    report = {"ok": code == ExitCode.OK, "forgotten": forgotten, "drift": drift,
              "errors": errors, "checkedCommits": len(checked)}
    if not args.dry_run:
        destination = root / "generated" / "reports"
        destination.mkdir(parents=True, exist_ok=True)
        write_json(destination / "verify.json", report)
    return code, report


def run(root, args, copies):
    template, copies = _template(args, copies)
    cache = cache_path(args).resolve()
    git = Git(root)
    with directory_lock(root / "catalog"), tempfile.TemporaryDirectory(prefix="assetctl-scan-") as transient:
        temporary = Path(transient)
        if not copies:
            if args.verify:
                return _verify(root, args, git, cache, temporary, copies)
            return _scan(root, args, git, cache, temporary, copies, template)
        if args.verify:
            if cache.is_dir():
                with directory_lock(cache):
                    return _verify(root, args, git, cache, temporary, copies)
            return _verify(root, args, git, cache, temporary, copies)
        if args.dry_run:
            if not args.fetch and cache.is_dir():
                with directory_lock(cache):
                    return _scan(root, args, git, cache, temporary, copies, template)
            return _scan(root, args, git, cache, temporary, copies, template)
        if args.fetch and copies:
            cache.mkdir(parents=True, exist_ok=True)
        if cache.is_dir():
            with directory_lock(cache):
                return _scan(root, args, git, cache, None, copies, template)
        return _scan(root, args, git, cache, None, copies, template)
