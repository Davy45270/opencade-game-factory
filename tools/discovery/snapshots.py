"""Éléments nécessaires à l’analyse croisée des commits autorisés."""

import re
from collections import defaultdict
from pathlib import PurePosixPath

from tools.core.catalog import InvalidJSON, parse_json
from tools.discovery import formats, references
from tools.discovery.importer import MAX_BLOB, _classify, added_row
from tools.publish import licenses


class Snapshot:
    def __init__(self, repo, commit, mirror, date, members, tree):
        self.repo = repo
        self.commit = commit
        self.mirror = mirror
        self.date = date
        self.members = members
        self.tree = tree
        self.indexed = {}
        self.measurements = {}
        self.metadata = {}
        self.license_texts = {}
        self.modules = {}
        self.frame_sources = {}

    def examine(self, path, raw):
        name = PurePosixPath(path).name
        if name in {"LICENSE", "LICENSE.md"}:
            self.license_texts[path] = licenses.from_text(raw)
        if (name == "provenance.json" or name.endswith(".decoupe.json")
                or (path == "catalogue.json" and self.repo == "jeux-assets")):
            try:
                self.metadata[path] = parse_json(raw)
            except InvalidJSON:
                self.metadata[path] = None
        if formats.extension(path) in formats.REFERENCE:
            try:
                source = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                return
            if "\0" not in source:
                parsed = references.analyse(path, source)
                if parsed[2] or parsed[3]:
                    self.modules[path] = parsed

    def import_referenced_data(self, git, rows, add_blob):
        examined = {row["path"]: row for row in rows if row["format"] == "json" and row["status"] == "examined"}
        if not examined:
            return
        indexed = examined.keys() | self.indexed.keys()
        paths = references.explicit_data_targets(self.modules, self.tree, indexed) & examined.keys()
        if not paths:
            return
        measured = formats.Format({"type": "data"})
        with git.batch(self.mirror) as batch:
            for path in sorted(paths):
                raw = batch.read(self.tree[path], MAX_BLOB)
                try:
                    parse_json(raw)
                except InvalidJSON:
                    examined[path].update(status="exception", reason="invalid-json-data")
                    continue
                add_blob(path, raw, measured, None)
                row = examined[path]
                row.pop("reason")
                row.update(added_row(row, measured))

    def code_license(self, path):
        package = references.roots(path, self.tree)
        # A package license takes precedence if present. Fall back to the repository license.
        for base in dict.fromkeys((package, "")):
            for name in ("LICENSE", "LICENSE.md"):
                license_path = f"{base}/{name}" if base else name
                if license_path in self.license_texts:
                    return license_path, self.license_texts[license_path]
        return None, None


def catalogue_enrichment(snapshots, target):
    prefixes = defaultdict(list)
    for asset in target.assets.values():
        if asset["sha256"]:
            prefixes[asset["sha256"][:16]].append(asset)
    claims = defaultdict(list)
    for snapshot in snapshots:
        if all(release for _, _, release, _ in snapshot.members):
            continue
        document = snapshot.metadata.get("catalogue.json")
        entries = document.get("entrees") if isinstance(document, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            files = entry.get("fichiers") if isinstance(entry, dict) else None
            for item in files if isinstance(files, list) else ():
                prefix = item.get("sha256") if isinstance(item, dict) else None
                if isinstance(prefix, str) and re.fullmatch(r"[0-9a-fA-F]{16}", prefix):
                    claims[prefix.lower()].append((entry, f"catalogue.json@{snapshot.commit}"))
    for prefix, sources in claims.items():
        assets = prefixes.get(prefix, [])
        if len({a["sha256"] for a in assets}) != 1 or any(entry != sources[0][0] for entry, _ in sources):
            continue
        entry, ref = sources[0]
        for asset in assets:
            if asset["status"] != "published":
                licenses.apply_catalogue(asset, entry, ref)
                target.changed.add(asset["id"])


def code_licenses(snapshots, target):
    claims = defaultdict(list)
    for snapshot in snapshots:
        release_only = all(release for _, _, release, _ in snapshot.members)
        for path, asset_ids in snapshot.indexed.items():
            for asset_id in asset_ids:
                asset = target.assets[asset_id]
                if (asset["family"]["type"] != "code-generated" or asset["status"] == "published"
                        or target.version_at(asset_id, snapshot, path) != asset["version"]):
                    continue
                license_path, value = snapshot.code_license(path)
                claims[asset_id].append((release_only, value, f"{license_path}@{snapshot.commit}"))
    for asset_id, claims_for_asset in claims.items():
        priority = min(entry[0] for entry in claims_for_asset)
        entries = [(value, ref) for release, value, ref in claims_for_asset if release == priority]
        asset = target.assets[asset_id]
        value, ref = entries[0]
        if value and all(other == value for other, _ in entries):
            licenses.assign(asset, value, "license-file", ref, "Licence du code identifiée par son texte.")
        else:
            asset["license"] = "unknown"
            asset.pop("licenseEvidence", None)
        target.changed.add(asset_id)


def _identity(use):
    return (use["repo"], use.get("provider"), use["game"], use["scene"], use["codeRef"]["path"],
            use["codeRef"]["line"], use["importName"], use.get("assetPath"), use["role"], use.get("assetVersion", 1))


def _release_names(tags, code_path, code_oid, asset_blobs):
    paths = {**asset_blobs, code_path: code_oid}
    return sorted({name for name, tree in tags if all(p in tree and tree[p].oid == oid for p, oid in paths.items())})


def build_graph(snapshots, target, references_by_copy, git, prepared):
    trees = {(s.repo, s.commit): s.tree for s in snapshots}
    heads = {}
    tags = {}
    for key, (mirror, _) in prepared.items():
        record = references_by_copy[key]
        heads[key] = record["commit"], trees[key[0], record["commit"]]
        tags[key] = []
        for tag in record.get("importedTags", record["tags"]):
            commit = tag["commit"]
            if not commit:
                continue
            tree_key = key[0], commit
            if tree_key not in trees:
                trees[tree_key] = {blob.path: blob for blob in git.tree(mirror, commit, sizes=False)}
            tags[key].append((tag["name"], trees[tree_key]))

    observations, dynamic = defaultdict(list), []
    for snapshot in snapshots:
        for path, (scene, method, refs, unresolved) in snapshot.modules.items():
            for copy, _, release_only, _ in snapshot.members:
                if not release_only:
                    dynamic.extend({"repo": copy.name, "provider": copy.provider, "commit": snapshot.commit,
                                    "path": path, "line": line, "excerpt": excerpt} for line, excerpt in unresolved)
                _, game = _classify(copy, path, "code")
                for ref in refs:
                    for asset_path in references.resolve(path, ref, snapshot.tree, snapshot.indexed):
                        for asset_id in dict.fromkeys(snapshot.indexed[asset_path]):
                            asset = target.assets[asset_id]
                            blobs = {asset_path: snapshot.tree[asset_path].oid}
                            if dependency := snapshot.frame_sources.get((asset_id, asset_path)):
                                blobs[dependency] = snapshot.tree[dependency].oid
                            releases = _release_names(tags[copy.key], path, snapshot.tree[path].oid, blobs)
                            use = references.usage(copy, snapshot.commit, path, game, scene, method,
                                                   asset, asset_path, ref, releases)
                            use["assetBlobs"] = blobs
                            use["assetVersion"] = target.version_at(asset_id, snapshot, asset_path)
                            observations[asset_id].append((release_only, use))
    for asset in target.assets.values():
        _reconcile_usages(asset, heads, observations.get(asset["id"], ()), target)
    return sorted(dynamic, key=lambda item: (item["repo"], item["provider"], item["path"], item["line"], item["excerpt"]))


def _reconcile_usages(asset, heads, sightings, target):
    current = {}
    history = {}
    for release_only, use in sightings:
        key = _identity(use)
        if not release_only:
            current[key] = use
        elif use["releases"]:
            history[key, use["commit"]] = use

    active_paths = {(use["repo"], use.get("provider"), use.get("assetPath")) for use in current.values()}

    def missing(use):
        copy = use["repo"], use.get("provider")
        path = use.get("assetPath")
        if copy not in heads or not path or (*copy, path) in active_paths:
            return None
        commit, tree = heads[copy]
        if path not in tree or any(p not in tree or tree[p].oid != oid
                                   for p, oid in use.get("assetBlobs", {}).items()):
            return commit
        return None

    previous = asset["usages"]
    kept = {}
    for use in previous:
        key = _identity(use)
        slot = key, use["commit"]
        if use["status"] == "removed":
            history.pop(slot, None)
            kept[slot] = use
        elif removed_at := missing(use):
            release_tags = set(use["releases"])
            if slot in history:
                release_tags.update(history.pop(slot)["releases"])
            kept[slot] = {**use, "status": "removed", "removedAtCommit": removed_at, "releases": sorted(release_tags)}
        elif (use["repo"], use.get("provider")) not in heads or (use["releases"] and key not in current):
            kept[slot] = use

    for (key, commit), use in history.items():
        if key in current and set(use["releases"]) <= set(current[key]["releases"]):
            continue
        if removed_at := missing(use):
            use = {**use, "status": "removed", "removedAtCommit": removed_at}
        kept.setdefault((key, commit), use)
    for key, use in current.items():
        slot = key, use["commit"]
        prior = kept.get(slot)
        if prior:
            use["releases"] = sorted(set(use["releases"]) | set(prior["releases"]))
        kept[slot] = use

    ordered = sorted(kept.values(), key=lambda use: (use["repo"], use.get("provider") or "", use["codeRef"]["path"],
                     use["codeRef"]["line"], use["commit"], use.get("assetPath") or "", use["importName"]))
    if ordered != previous:
        asset["usages"] = ordered
        target.changed.add(asset["id"])
