"""Orchestration du scan et contrôle indépendant du catalogue."""

import fcntl
import hashlib
import os
import tempfile
from collections import defaultdict
from itertools import chain
from contextlib import contextmanager
from pathlib import Path

from tools.core.catalog import Catalogue, CatalogueScopeError, InvalidJSON, parse_json, read_json, write_json
from tools.core.exit_codes import ExitCode
from tools.core.schemas import schemas
from tools.discovery import formats, importer, references as usage_index, snapshots
from tools.discovery.jobs import job_for
from tools.discovery.repos import OID, Git, GitError, check_destinations, select
from tools.extract.sheets import SheetDiscovery
from tools.index import reports
from tools.publish import licenses

REFERENCE_FILE = "scan-references.json"


def cache_path(args):
    return getattr(args, "cache", None) or Path.home() / ".cache" / "opencade-asset-registry" / "mirrors"


def preflight(root, args):
    selected, local_copies = select(root, args)
    check_destinations(root, cache_path(args), getattr(args, "log", None), local_copies)
    for relative in ("catalog", "catalog/assets", "catalog/sheets", "catalog/import-jobs", "generated",
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


CANONICAL_ORDER = ("github", "forgejo", "local")


def _divergences(copies, prepared):
    """Copies d'une même source à des commits différents : une seule est importée (GitHub, puis
    Forgejo, puis la copie locale), les autres sont signalées « copies divergentes » au lieu de
    produire une seconde version de chaque asset (HL-538, 19/11)."""
    by_name = defaultdict(list)
    for copy in copies:
        if copy.key in prepared:
            by_name[copy.name].append(copy)
    skipped, notices = set(), []
    for name, members in sorted(by_name.items()):
        commits = {prepared[copy.key][1]["commit"] for copy in members}
        if len(commits) < 2:
            continue
        canonical = min(members, key=lambda copy: CANONICAL_ORDER.index(copy.provider))
        kept = prepared[canonical.key][1]["commit"]
        ignored = [copy for copy in members if prepared[copy.key][1]["commit"] != kept]
        skipped.update(copy.key for copy in ignored)
        notices.append({"name": name, "message": "Copies divergentes : seule la copie "
                        f"{canonical.provider} ({kept[:12]}) est importée.",
                        "importedProvider": canonical.provider, "importedCommit": kept,
                        "ignored": [{"provider": copy.provider, "commit": prepared[copy.key][1]["commit"]}
                                    for copy in ignored]})
    return skipped, notices


def _repo_report(copies, prepared, errors, skipped=frozenset()):
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
            {"provider": item["provider"], "commit": item["commit"],
             "imported": (repo["name"], item["provider"]) not in skipped} for item in repo["copies"]
            if repo["divergent"] and "commit" in item
        ]
    return list(repositories.values())


def _declared_assets(git, snapshot):
    blob = snapshot.tree.get("assets.lock.json")
    if blob is None or blob.symlink or blob.size > importer.MAX_BLOB:
        return {}
    with git.batch(snapshot.mirror) as batch:
        try:
            lock = parse_json(batch.read(blob, importer.MAX_BLOB))
        except InvalidJSON:
            return {}
    if not schemas().validator("lock").is_valid(lock):
        return {}
    declarations = defaultdict(set)
    for entry in lock["assets"]:
        declarations[entry["path"], entry["sha256"].lower()].add(entry["assetId"])
    return {key: next(iter(ids)) for key, ids in declarations.items() if len(ids) == 1}


def _scan(root, args, git, cache, temporary, copies, template):
    incremental = getattr(args, "incremental", False)
    references = _load_references(root)
    unchanged = set()
    prepared = {}
    errors = {}
    for copy in copies:
        try:
            stored = references.get(copy.key)
            if incremental and args.fetch and stored:
                commit, branch = git.remote_head(copy)
                if (commit, branch) == (stored["commit"], stored["branch"]):
                    prepared[copy.key] = None, stored
                    unchanged.add(copy.key)
                    continue
            if incremental and not args.fetch:
                provider = Catalogue._regular_path(cache / copy.provider)
                mirror = Catalogue._regular_path(provider / f"{copy.name}.git")
                if not mirror.is_dir():
                    raise GitError("Miroir absent avec --no-fetch.")
                git.check_mirror(copy, mirror)
            else:
                mirror = _mirror_for(git, copy, cache, args.fetch, temporary)
            reference = git.reference(mirror, copy)
            prepared[copy.key] = mirror, reference
            if incremental and stored and (reference["commit"], reference["branch"]) == (stored["commit"], stored["branch"]):
                unchanged.add(copy.key)
        except GitError as exc:
            errors[copy.key] = str(exc)

    skipped, divergent = _divergences(copies, prepared)
    imported = {key: value for key, value in prepared.items() if key not in skipped | unchanged}
    groups = defaultdict(list)
    current_commits = {}
    for copy in copies:
        if copy.key not in imported:
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

    if incremental and (errors or not groups):
        return (ExitCode.IO if errors else ExitCode.OK), {
            "ok": not errors, "scannedCopies": 0, "newAssets": 0, "newIds": 0,
            "divergentSources": divergent, "errors": _repo_report(copies, prepared, errors, skipped) if errors else [],
        }

    inputs = [(copy.name, copy.provider, commit)
              for (_, commit), members in groups.items() for copy, *_ in members]
    job_id, job = job_for(template, inputs)
    target = importer.Importer(root, job_id, args.dry_run)
    rows, manifests, trees = [], [], []
    ordered = sorted(groups.items(), key=lambda item: (all(member[2] for member in item[1]), item[0]))
    for (repo, commit), members in ordered:
        mirror = members[0][1]
        head_date = next((date for _, _, release, date in members if not release), None)
        date = head_date or git.run("show", "-s", "--format=%cI", commit, mirror=mirror).decode().strip()
        locations = [(copy, release) for copy, _, release, _ in members]

        snapshot = snapshots.Snapshot(repo, commit, mirror, date, members,
                                      {blob.path: blob for blob in git.tree(mirror, commit, sizes=True)})
        trees.append(snapshot)
        declared = _declared_assets(git, snapshot)

        def add_blob(path, data, measured, earliest):
            digest = hashlib.sha256(data).hexdigest()
            snapshot.measurements[path] = measured.family, measured.metadata, measured.dimensions
            snapshot.indexed[path] = target.import_blob(locations, commit, date, path, digest, measured, earliest,
                                                        declared.get((path, digest)))

        discovered, build_files = importer.scan_tree(git, mirror, repo, commit, snapshot.tree,
                                                      add_blob, snapshot.examine)
        snapshot.import_referenced_data(git, discovered, add_blob)
        rows.extend(discovered)
        manifests.extend({"repo": repo, "commit": commit, "path": path} for path in build_files)

    target.reconcile(current_commits)
    sheet_limits = SheetDiscovery(target, trees, git).run()
    snapshots.code_licenses(trees, target)
    snapshots.catalogue_enrichment(trees, target)
    dynamic = snapshots.build_graph(trees, target, references, git, imported)
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
        repositories = _repo_report(copies, prepared, errors, skipped)
        previous_exceptions = [row for row in exceptions if (row["repo"], row["commit"]) not in scanned]
        reports.emit(root, repositories, [*rows, *previous_exceptions], exceptions,
                     target.assets.values(), importer.EXCLUSIONS, manifests, sheet_limits, target.sheets.values())
        usage_index.emit(root, target.assets.values())
        licenses.emit(root, target.assets.values(), target.sheets.values())
        dynamic_path = root / "generated" / "reports" / "dynamic-refs.json"
        if dynamic_path.is_file():
            refreshed = set(imported)
            dynamic.extend(row for row in read_json(dynamic_path)
                           if (row["repo"], row.get("provider")) not in refreshed)
        write_json(dynamic_path, sorted(dynamic, key=lambda row: (
            row["repo"], row.get("provider", ""), row["commit"], row["path"], row["line"], row["excerpt"])))
        write_json(root / "generated" / "duplicates.json", duplicates(target.assets.values()))
        write_json(root / "catalog" / REFERENCE_FILE,
                   {"schemaVersion": "1.0", "references": [references[key] for key in sorted(references)]})

    # Une copie indisponible (dont une branche par défaut absente) rend 4, même si d'autres copies
    # ont été lues : jamais de succès muet sur une source manquante.
    code = ExitCode.IO if errors else ExitCode.OK
    return code, {"ok": code == ExitCode.OK, "jobId": job_id, **target.counts(),
                  "scannedCopies": len(imported), "divergentSources": divergent,
                  "errors": _repo_report(copies, prepared, errors, skipped) if errors else []}


def _inventory(git, mirror, repo, commit, recorded, forgotten):
    tree = {blob.path: blob for blob in git.tree(mirror, commit, sizes=True)}
    examined_json = set()
    with git.batch(mirror) as batch:
        for path, blob in tree.items():
            kind = formats.extension(path)
            key = repo, commit, path
            if kind not in formats.SUPPORTED or key in recorded or importer.exclusion(path):
                continue
            if kind in formats.CONDITIONAL and not blob.symlink and blob.size <= importer.MAX_BLOB:
                data = batch.read(blob, importer.MAX_BLOB)
                try:
                    if formats.inspect(path, data) is None:
                        if kind == "json":
                            examined_json.add(path)
                        continue
                except formats.Unreadable:
                    pass
            forgotten.append({"repo": repo, "commit": commit, "path": path})
        if not examined_json:
            return
        modules = {}
        for path, blob in tree.items():
            if (formats.extension(path) not in formats.CODE | {"html"}
                    or blob.symlink or blob.size > importer.MAX_BLOB or importer.exclusion(path)
                    or importer.UNSAFE_PATH.search(path)):
                continue
            try:
                source = batch.read(blob, importer.MAX_BLOB).decode("utf-8-sig")
            except UnicodeDecodeError:
                continue
            if "\0" not in source:
                modules[path] = usage_index.analyse(path, source)
        eligible = examined_json | {path for name, revision, path in recorded
                                    if name == repo and revision == commit and path in tree}
        missing_data = usage_index.explicit_data_targets(modules, tree, eligible) & examined_json
        forgotten.extend({"repo": repo, "commit": commit, "path": path} for path in sorted(missing_data))


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
