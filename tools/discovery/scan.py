"""Orchestration du scan et contrôle indépendant du catalogue."""

import fcntl
import hashlib
import os
import tempfile
from collections import defaultdict
from itertools import chain
from contextlib import contextmanager
from functools import cache as memoize
from pathlib import Path

from tools import asset_versions
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
        return {}, {}
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
        heads = document.get("importedHeads", {})
        if not isinstance(heads, dict) or not all(
                isinstance(commit, str) and OID.fullmatch(commit)
                and any(key[0] == name and record["commit"] == commit for key, record in records.items())
                for name, commit in heads.items()):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidJSON("Historique des commits de référence invalide.") from exc
    return records, heads


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


def _descends_from_all(git, mirror, commit, others):
    for other in others:
        if other == commit:
            continue
        try:  # code 1 : pas ancêtre ; 128 : objet absent de ce miroir (histoire inconnue ici)
            git.run("merge-base", "--is-ancestor", other, commit, mirror=mirror)
        except GitError:
            return False
    return True


def _divergences(copies, prepared, git=None, *, eligible=None):
    """Copies d'une même source à des commits différents : une seule est importée, les autres sont signalées
    « copies divergentes » au lieu de produire une seconde version de chaque asset (HL-538, 19/11).
    La copie importée est la plus avancée sur la même histoire (son commit descend de tous les autres : une copie
    seulement en retard n'a rien de plus). Sans copie la plus avancée (histoires réellement divergentes), l'ordre
    GitHub, Forgejo, locale départage et le motif le dit."""
    by_name = defaultdict(list)
    for copy in copies:
        if copy.key in prepared:
            by_name[copy.name].append(copy)
    skipped, notices = set(), []
    for name, members in sorted(by_name.items()):
        commits = {prepared[copy.key][1]["commit"] for copy in members}
        if len(commits) < 2:
            continue
        ordered = sorted(members, key=lambda copy: CANONICAL_ORDER.index(copy.provider))
        candidates = [copy for copy in ordered if eligible is None or copy.key in eligible]
        contenders = candidates or ordered
        contender_commits = {prepared[copy.key][1]["commit"] for copy in contenders}
        ahead = next((copy for copy in contenders if git is not None and _descends_from_all(
            git, prepared[copy.key][0], prepared[copy.key][1]["commit"], contender_commits)), None)
        canonical = ahead or contenders[0]
        reason = ("la plus avancée" if ahead and len(contender_commits) > 1 else
                  "continuité avec la dernière tête importée" if len(candidates) < len(ordered) else
                  "histoires divergentes, priorité GitHub > Forgejo > locale")
        kept = prepared[canonical.key][1]["commit"]
        ignored = [copy for copy in members if prepared[copy.key][1]["commit"] != kept]
        skipped.update(copy.key for copy in ignored)
        notices.append({"name": name, "message": "Copies divergentes : seule la copie "
                        f"{canonical.provider} ({kept[:12]}, {reason}) est importée.",
                        "importedProvider": canonical.provider, "importedCommit": kept,
                        "reason": "ahead" if ahead else "forked",
                        "ignored": [{"provider": copy.provider, "commit": prepared[copy.key][1]["commit"]}
                                    for copy in ignored]})
    return skipped, notices


def _release_authority(prepared, skipped, git, enabled):
    allowed = defaultdict(list)
    notices = []
    if not enabled:
        return allowed, notices
    tags = defaultdict(list)
    for key, (mirror, reference) in prepared.items():
        if key not in skipped:
            for tag in reference["tags"]:
                if tag["commit"]:
                    tags[key[0], tag["name"]].append((key, mirror, tag))
    for (repo, name), candidates in sorted(tags.items()):
        candidates.sort(key=lambda item: CANONICAL_ORDER.index(item[0][1]))
        commits = {tag["commit"] for _, _, tag in candidates}
        if len(commits) == 1:
            for key, _, tag in candidates:
                allowed[key].append(tag)
            continue
        winner = next((tag["commit"] for _, mirror, tag in candidates
                       if _descends_from_all(git, mirror, tag["commit"], commits)), candidates[0][2]["commit"])
        for key, _, tag in candidates:
            accepted = tag["commit"] == winner
            if accepted:
                allowed[key].append(tag)
            notices.append({"repo": repo, "name": name, "provider": key[1],
                            "commit": tag["commit"], "imported": accepted})
    return allowed, notices


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


def _record_causality(target, trees, git):
    mirrors = defaultdict(set)
    for snapshot in trees:
        mirrors[snapshot.repo].update(mirror for _, mirror, _, _ in snapshot.members)

    @memoize
    def present(mirror, commit):
        try:
            git.run("cat-file", "-e", commit + "^{commit}", mirror=mirror)
        except GitError:
            return False
        return True

    @memoize
    def precedes(repos, a, b):
        for mirror in sorted(set().union(*(mirrors[repo] for repo in repos))):
            if present(mirror, a) and present(mirror, b):
                if _descends_from_all(git, mirror, b, [a]):
                    return -1
                if _descends_from_all(git, mirror, a, [b]):
                    return 1
                return 0
        return None

    for asset_id, asset in target.assets.items():
        repos = tuple(sorted(target.sources[asset_id]))
        if not repos or not set(repos).intersection(mirrors):
            continue
        if asset_versions.set_causality(asset["versions"], lambda a, b: precedes(repos, a, b)):
            target.changed.add(asset_id)


def _scan(root, args, git, cache, temporary, copies, template):
    incremental = getattr(args, "incremental", False)
    references, heads = _load_references(root)
    prepared = {}
    errors = {}
    for copy in copies:
        try:
            if incremental and not args.fetch:
                provider = Catalogue._regular_path(cache / copy.provider)
                mirror = Catalogue._regular_path(provider / f"{copy.name}.git")
                if not mirror.is_dir():
                    raise GitError("Miroir absent avec --no-fetch.")
                git.check_mirror(copy, mirror)
            else:
                mirror = _mirror_for(git, copy, cache, args.fetch, temporary)
            prepared[copy.key] = mirror, git.reference(mirror, copy)
        except GitError as exc:
            errors[copy.key] = str(exc)

    previous = defaultdict(set)
    for (name, _), record in references.items():
        previous[name].add(heads.get(name, record["commit"]))
    eligible = {key for key, (mirror, ref) in prepared.items()
                if _descends_from_all(git, mirror, ref["commit"], previous[key[0]])}
    eligible_names = {name for name, _ in eligible}
    blocked = {copy.name for copy in copies if previous[copy.name] and copy.name not in eligible_names}
    if blocked:
        for key in prepared:
            if key[0] in blocked:
                errors[key] = "Aucune continuité prouvée avec la dernière tête importée."
        return ExitCode.IO, {
            "ok": False, "scannedCopies": 0, "newAssets": 0, "newIds": 0,
            "divergentSources": [], "divergentTags": [], "blockedSources": sorted(blocked),
            "errors": _repo_report(copies, prepared, errors, prepared.keys()),
        }
    skipped, divergent = _divergences(copies, prepared, git, eligible=eligible)
    skipped.update(prepared.keys() - eligible)
    allowed, divergent_tags = _release_authority(prepared, skipped, git, template["sources"]["includeReleases"])
    next_refs = {}
    changed_repos = set()
    for key, (_, reference) in prepared.items():
        if key in skipped:
            continue
        releases = sorted({tag["commit"] for tag in allowed[key] if tag["commit"] != reference["commit"]})
        record = {"name": key[0], "provider": key[1], **reference, "releaseCommits": releases,
                  "importedTags": allowed[key]}
        next_refs[key] = record
        if references.get(key) != record:
            changed_repos.add(key[0])
    # Reload a source as a group so authority and usage observations stay in sync across providers.
    imported = {key: prepared[key] for key in next_refs if not incremental or key[0] in changed_repos}
    groups = defaultdict(list)
    current_commits = {}
    for copy in copies:
        if copy.key not in imported:
            continue
        mirror, reference = prepared[copy.key]
        head = reference["commit"]
        current_commits[copy.key] = head
        for commit in [head, *next_refs[copy.key]["releaseCommits"]]:
            groups[copy.name, commit].append((copy, mirror, commit != head, reference["date"]))
        references[copy.key] = next_refs[copy.key]
        heads[copy.name] = head

    if incremental and (errors or not groups):
        return (ExitCode.IO if errors else ExitCode.OK), {
            "ok": not errors, "scannedCopies": 0, "newAssets": 0, "newIds": 0,
            "divergentSources": divergent, "divergentTags": divergent_tags, "errors": _repo_report(copies, prepared, errors, skipped) if errors else [],
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
            snapshot.indexed[path] = target.import_blob(locations, snapshot, path, digest, measured, earliest, git,
                                                        declared.get((path, digest)))

        discovered, build_files = importer.scan_tree(git, mirror, repo, commit, snapshot.tree,
                                                      add_blob, snapshot.examine)
        snapshot.import_referenced_data(git, discovered, add_blob)
        rows.extend(discovered)
        manifests.extend({"repo": repo, "commit": commit, "path": path} for path in build_files)

    target.reconcile(current_commits)
    sheet_discovery = SheetDiscovery(target, trees, git)
    sheet_limits = sheet_discovery.run()
    _record_causality(target, trees, git)
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
        aliases = list(sheet_discovery.path_aliases.values())
        aliases_path = Catalogue._regular_path(root / "generated" / "reports" / "path-aliases.json")
        if aliases_path.is_file():
            aliases.extend(row for row in read_json(aliases_path)
                           if (row["repo"], row["commit"]) in active_commits - scanned)
        aliases.sort(key=lambda row: tuple(row[key] for key in ("repo", "commit", "path", "field", "reference")))
        reports.emit(root, repositories, [*rows, *previous_exceptions], exceptions,
                     target.assets.values(), importer.EXCLUSIONS, manifests, sheet_limits, target.sheets.values(),
                     divergent_tags=divergent_tags, path_aliases=aliases)
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
                   {"schemaVersion": "1.0", "references": [references[key] for key in sorted(references)],
                    "importedHeads": dict(sorted(heads.items()))})

    # Une copie indisponible (dont une branche par défaut absente) rend 4, même si d'autres copies
    # ont été lues : jamais de succès muet sur une source manquante.
    code = ExitCode.IO if errors else ExitCode.OK
    return code, {"ok": code == ExitCode.OK, "jobId": job_id, **target.counts(),
                  "scannedCopies": len(imported), "divergentSources": divergent, "divergentTags": divergent_tags,
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


def _skipped_divergent(root):
    path = Catalogue._regular_path(root / "generated" / "reports" / "migration.json")
    if not path.is_file():
        return set()
    return {(repo["name"], item["provider"]) for repo in read_json(path).get("repositories", [])
            for item in repo.get("divergentCopies", []) if item.get("imported") is False}


def _verify(root, args, git, cache, temporary, copies):
    references, _ = _load_references(root)
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
    # Copies divergentes laissées de côté exprès par le scan (7901d3c) : signalées, jamais comptées en dérive.
    skipped = _skipped_divergent(root)
    divergent = [entry for entry in drift if (entry["name"], entry["provider"]) in skipped]
    drift = [entry for entry in drift if (entry["name"], entry["provider"]) not in skipped]
    required = {(copy.name, commit) for copy in copies if (record := references.get(copy.key))
                for commit in [record["commit"], *record["releaseCommits"]]}
    code = (ExitCode.CHECK_FAILED if forgotten or drift else
            ExitCode.IO if required - checked or (errors and not checked) else ExitCode.OK)
    report = {"ok": code == ExitCode.OK, "forgotten": forgotten, "drift": drift, "divergent": divergent,
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
