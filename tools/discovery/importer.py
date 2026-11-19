"""Import idempotent des ressources découvertes et conservation des emplacements."""

import hashlib
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import quote

from PIL import Image

from tools import asset_versions
from tools.core.catalog import Catalogue, InvalidJSON, json_text, write_json
from tools.core.ids import IdRegistry
from tools.core.schemas import schemas
from tools.discovery import enrich, formats
from tools.discovery.repos import GitError, is_earlier

MAX_BLOB = 64 * 1024 * 1024
EXCLUSIONS = tuple(f"{name}/" for name in (
    "node_modules", "dist", "build", "coverage", "test-results", "playwright-report",
    ".npm-cache", ".pw-browsers", ".codex-logs",
))
UNSAFE_PATH = re.compile(r"[\\\x00-\x1f]|^[a-zA-Z]:")
BUILD_MANIFESTS = frozenset({
    "package.json", "project.godot", "Cargo.toml", "CMakeLists.txt",
    "Makefile", "pyproject.toml", "deno.json", "deno.jsonc", "tsconfig.json",
    "pnpm-workspace.yaml", "vite.config.js", "vite.config.ts",
    "webpack.config.js", "webpack.config.ts",
})
DEFAULT_JOB = {
    "schemaVersion": "1.0",
    "jobType": "initial-discovery",
    "sources": {"provider": "github", "scope": "authorized-game-repositories",
                "includeMonorepos": True, "includeReleases": True},
    "discovery": dict.fromkeys(("images", "animations", "tilemaps", "audio", "fonts",
                                "generatedAssets", "codeReferences"), True),
    "processing": dict.fromkeys(("extractSpritesheets", "describeWithAI", "detectDuplicates",
                                 "buildUsageGraph", "verifyLicenses"), True),
    "safety": dict.fromkeys(("modifySourceRepositories", "deleteSourceFiles", "publishUnknownLicenses"), False),
    "output": {"generateMigrationReport": True, "generateSearchIndex": True},
}


def exclusion(path):
    directories = path.split("/")[:-1]
    return next((rule for rule in EXCLUSIONS if rule[:-1] in directories), None)


def read_assets(root):
    catalogue = Catalogue(root)
    return {path.stem: catalogue.read(path) for path in catalogue.documents("assets")}


def _classify(copy, path, family):
    parts = PurePosixPath(path).parts
    game = None
    if copy.role == "game":
        if len(parts) >= 4 and parts[:2] == ("src", "games"):
            game = f"{copy.name}/{parts[2]}"
        elif len(parts) >= 3 and parts[0] == "packages":
            game = f"{copy.name}/{parts[1]}"
        elif copy.games == (copy.name,):
            game = copy.name
        elif len(copy.games) == 1:
            game = copy.games[0]
    if ("generated" in parts[:-1] or ".min." in parts[-1].lower()
            or family == "atlas" or "atlas" in parts[:-1] or "atlases" in parts[:-1]):
        return "generated", game
    return ("game" if game is not None else "shared-library"), game


def location(copy, commit, path, family, release_only):
    classification, game = _classify(copy, path, family)
    result = {"repo": copy.name, "provider": copy.provider, "path": path, "commit": commit,
              "visibility": "private" if copy.visibility == "private" else "public",
              "classification": classification, "game": game, "status": "active"}
    if release_only:
        result["releaseOnly"] = True
    return result


def added_row(row, measured):
    result = {**row, "status": "imported", "family": measured.family["type"]}
    if measured.family.get("audio", {}).get("durationSec", False) is None:
        result.update(durationUnknown=True, reason="audio-duration-unknown")
    return result


def scan_tree(git, mirror, repo, commit, tree, import_blob, examine):
    """Lit chaque blob candidat une seule fois pour un dépôt et un commit."""
    rows, blobs, manifests = [], [], []
    for blob in tree.values():
        if (not blob.symlink and PurePosixPath(blob.path).name in BUILD_MANIFESTS
                and exclusion(blob.path) is None):
            manifests.append(blob.path)
        if (formats.extension(blob.path) in formats.SUPPORTED | formats.UNCOVERED | formats.REFERENCE
                or PurePosixPath(blob.path).name in {"LICENSE", "LICENSE.md"}):
            blobs.append(blob)
    earliest = git.history_dates(mirror, commit, {blob.oid for blob in blobs
                                 if not blob.symlink and formats.extension(blob.path) in formats.SUPPORTED
                                 and blob.size <= MAX_BLOB and exclusion(blob.path) is None})
    with git.batch(mirror) as batch:
        for blob in blobs:
            path, kind = blob.path, formats.extension(blob.path)
            base = {"repo": repo, "commit": commit, "path": path, "format": kind}
            if kind not in formats.SUPPORTED | formats.UNCOVERED | formats.REFERENCE:
                if not blob.symlink and blob.size <= MAX_BLOB and not exclusion(path) and not UNSAFE_PATH.search(path):
                    examine(path, batch.read(blob, MAX_BLOB))
                continue
            if kind in formats.UNCOVERED:
                rows.append({**base, "status": "unsupported", "reason": "unsupported-format"})
                continue
            rule = exclusion(path)
            if rule and kind not in formats.CONDITIONAL:
                rows.append({**base, "status": "excluded", "reason": rule})
                continue
            reason = None
            if blob.symlink:
                reason = "git-symlink"
            elif UNSAFE_PATH.search(path):
                reason = "unrepresentable-path"
            elif blob.size > MAX_BLOB:
                reason = "too-large"
            if reason:
                rows.append({**base, "status": "excluded" if rule else "exception", "reason": rule or reason})
                continue
            raw = batch.read(blob, MAX_BLOB)
            if not rule:
                examine(path, raw)
            try:
                measured = formats.inspect(path, raw)
            except formats.Unreadable as exc:
                rows.append({**base, "status": "excluded" if rule else "exception", "reason": rule or str(exc)})
                continue
            if measured is None:
                rows.append({**base, "status": "excluded" if rule else "examined",
                             "reason": rule or "no-asset"})
                continue
            if rule:
                rows.append({**base, "status": "excluded", "reason": rule})
                continue
            import_blob(path, raw, measured, earliest.get(blob.oid))
            rows.append(added_row(base, measured))
    return rows, manifests


def _trace(evidence, method="proven", confidence=1):
    return {"method": method, "confidence": confidence, "evidence": [evidence]}


def _asset(asset_id, name, evidence, created, reference_date, job_id, digest, measured, family, kind):
    category = family["type"].replace("-", "")
    inference = {key: _trace(evidence) for key in ("family", "format", "sha256")}
    for key in ("dimensions", "alpha"):
        if getattr(measured, key) is not None:
            inference[key] = _trace(evidence)
    inference["category"] = _trace(evidence, "heuristic", 0.4)
    inference["description"] = _trace(evidence, "heuristic", 0.4)
    asset = {
        "schemaVersion": "1.0", "id": asset_id, "name": name,
        "description": f"Ressource {kind} repérée.",
        "category": category, "subcategory": None, "tags": "unknown",
        "originUniverse": "unknown", "visualStyle": None,
        "sourceSheetId": None, "sourceRegion": None,
        "orientation": "unknown", "facing": "unknown", "state": None,
        "dimensions": measured.dimensions, "format": kind, "alpha": measured.alpha,
        "pivot": "unknown", "files": {"registry": None, "locations": []},
        "sha256": digest, "provenance": {"type": "repo-file", "author": "unknown", "evidence": [evidence]},
        "license": "unknown", "status": "needs-review", "usages": [], "variants": [],
        "createdAt": created, "updatedAt": reference_date,
        "family": family, "inference": inference, "creation": {"importJob": job_id},
    }
    if measured.metadata:
        asset["formatMetadata"] = measured.metadata
        inference["formatMetadata"] = _trace(evidence)
    if measured.image is not None:
        from tools.index.dedup import fingerprints

        asset["perceptual"] = fingerprints(measured.image)
        inference["perceptual"] = _trace(evidence)
        asset["thumbnail"] = f"thumbnails/{digest[:2]}/{digest}.webp"
    asset_versions.initialize(asset)
    return asset


def _slot(entry):
    return entry["repo"], entry.get("provider"), entry["path"]


def _location_order(entry):
    repo, provider, path = _slot(entry)
    return repo, provider or "", path, entry["commit"], entry.get("status", "")


def _thumbnail(path, source):
    Catalogue._regular_path(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    preview = source.copy()
    preview.thumbnail((96, 96), Image.Resampling.LANCZOS)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".thumbnail-", delete=False) as stream:
        temporary = stream.name
        try:
            preview.save(stream, "WEBP", lossless=True, exact=True)
            stream.close()
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class Importer:
    def __init__(self, root, job_id, dry_run):
        self.root = root
        self.catalogue = Catalogue(root)
        self.assets = read_assets(root)
        self.initial_assets = set(self.assets)
        self.sheets = {path.stem: self.catalogue.read(path) for path in self.catalogue.documents("sheets")}
        self.initial_sheets = {sheet_id: json_text(sheet) for sheet_id, sheet in self.sheets.items()}
        self.sheet_ids = {sheet["sha256"]: sheet_id for sheet_id, sheet in self.sheets.items()}
        self.ids_path = self.catalogue.path / "ids.json"
        entries = self.catalogue.read(self.ids_path)
        try:
            self.ids = IdRegistry(entries)
        except ValueError as exc:
            raise InvalidJSON(str(exc)) from exc
        self.initial_ids = entries
        self.identity_owners = dict(entries)
        self.generated_lineages = {value for key, value in entries.items() if key.startswith("logical:generated-image:")}
        self.legacy_regions = defaultdict(list)
        self.migrated_atlas = {value for key, value in entries.items() if key.startswith("alias:atlas:")}
        for key, value in entries.items():
            if key.startswith("region:") and value in self.assets:
                family = self.assets[value]["family"]
                if isinstance(family, dict) and (frame := family.get("sprite", {}).get("frameName")):
                    self.legacy_regions[frame].append(value)
        self.job_id = job_id
        self.dry_run = dry_run
        self.sightings = defaultdict(list)
        self.changed = set()
        self.sources = defaultdict(set)
        self.slots = {}
        self.content = {}
        self.observed = {}
        self.active_sightings = set()
        self.release_only = {}
        self.active_paths = defaultdict(dict)
        self.historical_paths = {}
        for asset_id, asset in sorted(self.assets.items()):
            if "generator" in asset["provenance"]:
                self.generated_lineages.add(asset_id)
            if asset_versions.initialize(asset):
                self.changed.add(asset_id)
            versions = {entry["version"]: entry["sha256"].lower() for entry in asset["versions"]}
            family = asset["family"]
            symbol = family.get("code", {}).get("symbol") if isinstance(family, dict) else None
            for loc in asset["files"]["locations"]:
                number = loc.get("assetVersion", 1)
                self.remember(asset_id, loc, symbol, versions[number], number)
                if not loc.get("releaseOnly") and loc.get("status") != "removed":
                    self.active_paths[asset_id, loc["repo"]][loc["path"]] = loc["commit"]

    def remember(self, asset_id, loc, symbol, digest, number):
        repo, _, path = _slot(loc)
        self.sources[asset_id].add(repo)
        is_release = loc.get("releaseOnly", False)
        removed = loc.get("status") == "removed"
        if not is_release:
            self.release_only[asset_id] = False
        rank = (not is_release, not removed)
        key = repo, path, symbol
        prior = self.slots.get(key)
        prior_content = self.content.get((repo, digest, symbol))
        if prior is None or rank > prior[0]:
            self.slots[key] = rank, asset_id
        if prior_content is None or rank > prior_content[0]:
            self.content[repo, digest, symbol] = rank, asset_id
        sighting = asset_id, repo, path, loc["commit"]
        if not is_release and not removed:
            self.active_sightings.add(sighting)
        self.observed[sighting] = number
        self.historical_paths.setdefault((repo, path, loc["commit"], symbol), asset_id)

    def lineage(self, loc, symbol, digest, declared, isolated=()):
        repo, _, path = _slot(loc)
        if declared in self.assets and declared not in isolated and repo in self.sources[declared] and symbol is None:
            if repo == min(self.sources[declared]) or self.assets[declared]["sha256"].lower() == digest:
                return declared
        slot = self.slots.get((repo, path, symbol))
        exact = self.content.get((repo, digest, symbol))
        if exact and exact[1] in isolated and (not slot or slot[1] != exact[1]):
            exact = None
        if loc.get("releaseOnly"):
            if seen := self.historical_paths.get((repo, path, loc["commit"], symbol)):
                return seen
            if slot and repo == min(self.sources[slot[1]]):
                return slot[1]
            return exact[1] if exact else None
        matches = (slot, exact) if slot and slot[0] == (True, True) else (exact, slot)
        for match in matches:
            if match is None:
                continue
            _, asset_id = match
            if repo == min(self.sources[asset_id]) or (exact is not None and exact[1] == asset_id):
                return asset_id
        return None

    def allocate(self, key, repo, digest, category, name, isolated=()):
        owner = self.identity_owners.get(key)
        if owner in self.assets and (owner in isolated or self.sources[owner] - {repo} or
                                     self.assets[owner]["sha256"].lower() != digest):
            scope = hashlib.sha256(repo.encode()).hexdigest()
            key = f"file:source:{scope}:{digest}"
        if self.identity_owners.get(key) in isolated:
            key = f"logical:ordinary-image:{hashlib.sha256(json_text([repo, digest]).encode()).hexdigest()}"
        asset_id = self.ids.allouer(key, category, name)
        self.identity_owners[key] = asset_id
        return asset_id

    def generated_lineage(self, repo, path, kind, name):
        slot = self.slots.get((repo, path, None))
        if slot:
            asset_id = slot[1]
            locations = (*self.assets[asset_id]["files"]["locations"], *self.sightings[asset_id])
            if all((loc["repo"], loc["path"]) == (repo, path) for loc in locations):
                self.generated_lineages.add(asset_id)
                return asset_id
        identity = hashlib.sha256(json_text([repo, path]).encode()).hexdigest()
        asset_id = self.ids.allouer(f"logical:generated-image:{identity}", kind.replace("-", ""), name)
        self.generated_lineages.add(asset_id)
        return asset_id

    def split_alias(self, asset_id, snapshot, path, digest, git):
        paths = self.active_paths[asset_id, snapshot.repo]
        if path not in paths or len(paths) < 2 or self.assets[asset_id]["sha256"].lower() == digest:
            return False
        active = sorted(peer for peer in paths if peer in snapshot.tree)
        oid = snapshot.tree[path].oid
        peers = [peer for peer in active if snapshot.tree[peer].oid != oid]
        if not peers:
            return False
        for peer in peers:
            try:
                tree = git.run("ls-tree", paths[peer], "--", f":(literal){peer}", mirror=snapshot.mirror).split()
            except GitError:
                continue
            if tree and tree[2].decode() == snapshot.tree[peer].oid:
                return True
        return snapshot.tree[active[0]].oid != oid

    def update_version(self, asset, first, digest, date, measured, family, kind):
        asset_id = asset["id"]
        repo, _, path = _slot(first)
        commit = first["commit"]
        sighting = asset_id, repo, path, commit
        observed = self.observed.get(sighting)
        release = first.get("releaseOnly", False)
        if (observed is not None and (release or sighting in self.active_sightings)
                and asset["versions"][int(observed) - 1]["sha256"].lower() == digest):
            return observed
        current = asset["sha256"].lower() == digest
        if current:
            return asset["version"]
        if release or (self.sources[asset_id] and repo != min(self.sources[asset_id])):
            for entry in reversed(asset["versions"]):
                if entry["sha256"].lower() == digest:
                    return entry["version"]
        promote = not release or (self.release_only.get(asset_id, True)
                                  and (asset["updatedAt"] is None or is_earlier(asset["updatedAt"], date)))
        if promote:
            asset["versions"][asset["version"] - 1].setdefault("format", asset["format"])
            asset_versions.archive_publication(asset)
        number = asset_versions.append(asset, digest, current=promote, commit=commit, date=date)
        asset["versions"][number - 1]["format"] = kind
        if promote:
            evidence = f"{repo}@{commit}:{path}"
            fresh = _asset(asset_id, asset["name"], evidence, asset["createdAt"], date, self.job_id,
                           digest, measured, family, kind)
            inference = asset.setdefault("inference", {})
            for field in ("family", "format", "dimensions", "alpha", "formatMetadata", "perceptual",
                          "thumbnail", "sha256"):
                inference.pop(field, None)
                if field in fresh:
                    asset[field] = fresh[field]
                else:
                    asset.pop(field, None)
                if field in fresh["inference"]:
                    inference[field] = fresh["inference"][field]
            if asset["status"] == "published":
                asset["status"] = "needs-review"
            if asset["files"].get("registry"):
                asset["files"]["registry"] = None
            asset["license"] = "unknown"
            asset.pop("licenseEvidence", None)
            if asset.get("publicExport") == "allowed":
                asset.pop("publicExport")
        self.changed.add(asset_id)
        return number

    def import_blob(self, references, snapshot, path, digest, measured, earliest, git, declared=None):
        commit, date = snapshot.commit, snapshot.date
        future = measured.family["type"]
        locations = [location(copy, commit, path, future, tag_only) for copy, tag_only in references]
        locations.sort(key=lambda loc: loc.get("releaseOnly", False))
        if future == "code-generated":
            for loc in locations:
                loc["blobSha256"] = digest
        imported_ids = []
        for symbol in measured.symbols or (None,):
            family = measured.family
            first = locations[0]
            name = symbol or PurePosixPath(path).stem
            if not name.strip():
                name = path
            key = f"file:sha256:{digest}"
            if future == "code-generated":
                # Percent encoding preserves separators and keeps literal keys distinct from the module fallback.
                code_path = quote(path, safe="/ .-_")
                identity = quote(symbol, safe="") if symbol is not None else "@module"
                key = f"code:{first['repo']}:{code_path}#{identity}"
                label = "module" if symbol is None else symbol if symbol.strip() else repr(symbol)
                family = {"type": future, "code": {"repo": first["repo"], "path": path, "symbol": label}}
            label = family.get("code", {}).get("symbol")
            generated = path in snapshot.generated_paths
            isolated = self.generated_lineages
            if not generated and (exact := self.content.get((first["repo"], digest, label))):
                if self.active_paths[exact[1], first["repo"]].keys() & snapshot.generated_paths.keys():
                    isolated = isolated | {exact[1]}
            asset_id = (self.generated_lineage(first["repo"], path, future, name) if generated
                        else self.lineage(first, label, digest, declared, isolated))
            if (asset_id is not None and not generated and future != "code-generated" and not first.get("releaseOnly")
                    and self.split_alias(asset_id, snapshot, path, digest, git)):
                identity = json_text([first["repo"], path, digest]).encode()
                key = f"logical:file-path:{hashlib.sha256(identity).hexdigest()}"
                asset_id = None
            if asset_id is None:
                if future == "code-generated":
                    asset_id = self.ids.allouer(key, future.replace("-", ""), name)
                else:
                    asset_id = self.allocate(key, first["repo"], digest, future.replace("-", ""), name, isolated)
            created = datetime.fromtimestamp(earliest, timezone.utc).isoformat() if earliest is not None else date
            if asset_id not in self.assets:
                evidence = f"{first['repo']}@{commit}:{path}"
                self.assets[asset_id] = _asset(asset_id, name, evidence, created, date, self.job_id,
                                               digest, measured, family, formats.extension(path))
                self.assets[asset_id]["versions"][0].update(commit=commit, date=date)
                self.changed.add(asset_id)
            asset = self.assets[asset_id]
            number = self.update_version(asset, first, digest, date, measured, family, formats.extension(path))
            if number == asset["version"] and asset["status"] != "published" and (asset_id not in self.initial_assets
                    or asset["description"].startswith("Ressource ")):
                universe = first["game"].split("/")[-1] if first["game"] else None
                enrich.enrich(asset, path, universe)
                self.changed.add(asset_id)
            if number == asset["version"] and future == "code-generated" and asset["provenance"]["type"] == "repo-file":
                asset["provenance"]["type"] = "code-generated"
                self.changed.add(asset_id)
            if measured.image is not None and not self.dry_run:
                thumbnail = self.root / "thumbnails" / digest[:2] / f"{digest}.webp"
                Catalogue._regular_path(thumbnail.parent)
                if not Catalogue._regular_path(thumbnail).exists():
                    _thumbnail(thumbnail, measured.image)
            if asset["createdAt"] is None or is_earlier(created, asset["createdAt"]):
                asset["createdAt"] = created
                self.changed.add(asset_id)
            if number == asset["version"] and (asset["updatedAt"] is None or is_earlier(asset["updatedAt"], date)):
                asset["updatedAt"] = date
                self.changed.add(asset_id)
            for loc in locations:
                sighting = {**loc, "assetVersion": number}
                self.sightings[asset_id].append(sighting)
                self.remember(asset_id, sighting, label, digest, number)
            imported_ids.append(asset_id)
        return imported_ids

    def legacy_atlas_id(self, legacy_key, repo, path, image_path, name, box):
        suffix = f":{path}#{name}"
        by_evidence, by_image, by_box = [], [], []
        for asset_id in self.legacy_regions[name]:
            if asset_id in self.migrated_atlas:
                continue
            asset = self.assets[asset_id]
            if any(ref.startswith(repo + "@") and ref.endswith(suffix) for ref in asset["provenance"]["evidence"]):
                by_evidence.append(asset_id)
            for frame in asset["files"].get("atlasFrames", ()):
                sheet = self.sheets.get(frame["atlasSheetId"])
                if sheet and any(loc["repo"] == repo and loc["path"] == image_path
                                 for loc in sheet["files"]["locations"]):
                    by_image.append(asset_id)
                    if all(frame[key] == box[key] for key in ("x", "y", "w", "h")):
                        by_box.append(asset_id)
        old_id = self.identity_owners.get(legacy_key)
        if old_id in by_image:
            return old_id
        for candidates in (by_evidence, by_box, by_image):
            if len(set(candidates)) == 1:
                return candidates[0]
        return None

    def import_region(self, legacy_key, name, snapshot, path, image_path, digest, pixels, frame, sheet):
        family = {"type": "sprite", "sprite": {"frameName": name}}
        digest_key = hashlib.sha256(json_text([snapshot.repo, path, name]).encode()).hexdigest()
        key, alias = f"logical:atlas:{digest_key}", f"alias:atlas:{digest_key}"
        asset_id = self.identity_owners.get(alias) or self.identity_owners.get(key)
        if asset_id is None:
            asset_id = self.legacy_atlas_id(legacy_key, snapshot.repo, path, image_path, name, frame)
            if asset_id:
                self.identity_owners[alias] = self.ids.add_alias(alias, asset_id)
                self.migrated_atlas.add(asset_id)
            else:
                asset_id = self.identity_owners[key] = self.ids.allouer(key, "sprite", name)
        evidence = f"{snapshot.repo}@{snapshot.commit}:{path}#{name}"
        measured = formats.Format(family, formats.dimensions(*pixels.size),
                                  pixels.getchannel("A").getextrema()[0] != 255, pixels)
        release = all(item[2] for item in snapshot.members)
        if asset_id not in self.assets:
            asset = _asset(asset_id, name, evidence, snapshot.date, snapshot.date, self.job_id,
                           digest, measured, family, "png")
            asset["files"]["sha256Method"] = "canonical-crop-png"
            asset["versions"][0].update(commit=snapshot.commit, date=snapshot.date)
            enrich.enrich(asset, path)
            self.assets[asset_id] = asset
            self.changed.add(asset_id)
        asset = self.assets[asset_id]
        old_number = asset["version"]
        previous = asset["versions"][old_number - 1]
        if "atlasFrames" not in previous and asset["files"].get("atlasFrames"):
            proofs = [{**old, "sourceSheetSha256": self.sheets[old["atlasSheetId"]]["sha256"]}
                      for old in asset["files"]["atlasFrames"] if old["atlasSheetId"] in self.sheets]
            if proofs:
                previous["atlasFrames"] = proofs
                self.changed.add(asset_id)
        first = {"repo": snapshot.repo, "path": path, "commit": snapshot.commit, "releaseOnly": release}
        number = self.update_version(asset, first, digest, snapshot.date, measured, family, "png")
        if old_number != asset["version"]:
            asset["files"].pop("atlasFrames", None)
            asset["updatedAt"] = snapshot.date
        entry = asset["versions"][number - 1]
        if "commit" not in entry:
            entry.update(commit=snapshot.commit, date=snapshot.date)
            self.changed.add(asset_id)
        proofs = entry.setdefault("atlasFrames", [])
        proof = {**frame, "sourceSheetSha256": sheet["sha256"]}
        if proof not in proofs:
            proofs.append(proof)
            self.changed.add(asset_id)
        self.sources[asset_id].add(snapshot.repo)
        self.observed[asset_id, snapshot.repo, path, snapshot.commit] = number
        if not release:
            self.release_only[asset_id] = False
        if not self.dry_run and asset.get("thumbnail") and number == asset["version"]:
            thumbnail = self.root / asset["thumbnail"]
            Catalogue._regular_path(thumbnail.parent)
            if not Catalogue._regular_path(thumbnail).exists():
                _thumbnail(thumbnail, pixels)
        return asset, number

    def version_at(self, asset_id, snapshot, path):
        return self.observed.get((asset_id, snapshot.repo, path, snapshot.commit), 1)

    def order_new_history(self, asset, sightings):
        # On a first import, older tags can be numbered before the head.
        # Once written, the existing numbers stay fixed.
        if asset["id"] in self.initial_assets or len(asset["versions"]) == 1:
            return
        current = asset["version"]
        versions = sorted(asset["versions"], key=lambda entry: (
            entry["version"] == current, datetime.fromisoformat(entry["date"]), entry["version"]))
        numbers = {}
        for number, entry in enumerate(versions, 1):
            numbers[entry["version"]] = number
            entry.update(version=number, previousVersion=number - 1 or None,
                         nextVersion=number + 1 if number < len(versions) else None)
        asset.update(version=numbers[current], versions=versions)
        for loc in sightings:
            loc["assetVersion"] = numbers[loc["assetVersion"]]
            self.observed[asset["id"], loc["repo"], loc["path"], loc["commit"]] = loc["assetVersion"]

    def reconcile(self, commits):
        source_heads = defaultdict(set)
        for (repo, _), commit in commits.items():
            source_heads[repo].add(commit)
        reassigned = {_slot(loc): (asset_id, loc["commit"])
                      for asset_id in self.generated_lineages for loc in self.sightings[asset_id]
                      if not loc.get("releaseOnly")}
        for asset_id, asset in self.assets.items():
            previous = asset["files"]["locations"]
            latest = self.sightings[asset_id]
            self.order_new_history(asset, latest)
            current = {_slot(entry): entry for entry in latest if not entry.get("releaseOnly")}
            current_by_source = {(entry["repo"], entry["path"]): entry for entry in current.values()}
            history = {(entry["repo"], entry.get("provider"), entry["path"], entry["commit"]): entry
                       for entry in latest if entry.get("releaseOnly")}
            final = []
            for entry in previous:
                identity = _slot(entry)
                commit = commits.get(identity[:2])
                seen = current.get(identity)
                if not identity[1] and len(source_heads[identity[0]]) == 1:
                    commit = next(iter(source_heads[identity[0]]))
                    seen = current_by_source.get((identity[0], identity[2]))
                if entry.get("releaseOnly"):
                    released = (*identity, entry["commit"])
                    if released not in history and (seen is None or seen["commit"] != entry["commit"]):
                        final.append(entry)
                elif entry.get("status") == "removed":
                    if seen is None or entry["commit"] != seen["commit"]:
                        final.append(entry)
                elif seen is not None and seen["assetVersion"] == entry.get("assetVersion", 1):
                    continue
                elif identity in reassigned and reassigned[identity] != (asset_id, entry["commit"]):
                    _, moved_at = reassigned[identity]
                    final.append({**entry, "status": "removed", "removedAtCommit": moved_at})
                elif commit is not None and commit != entry["commit"]:
                    final.append({**entry, "status": "removed", "removedAtCommit": commit})
                else:
                    final.append(entry)
            final = sorted([*final, *current.values(), *history.values()], key=_location_order)
            if final != previous:
                asset["files"]["locations"] = final
                self.changed.add(asset_id)

    def save(self, job):
        if self.dry_run:
            return
        for asset_id in sorted(self.changed):
            record = self.assets[asset_id]
            error = next(schemas().validator("asset").iter_errors(record), None)
            if error:
                field = "/".join(map(str, error.absolute_path))
                raise InvalidJSON(f"Fiche générée invalide ({asset_id}, champ {field}).")
        for sheet in self.sheets.values():
            error = next(schemas().validator("sheet").iter_errors(sheet), None)
            if error:
                raise InvalidJSON(f"Planche générée invalide ({sheet['id']}, champ {list(error.absolute_path)}).")
        jobs = self.catalogue._regular_path(self.catalogue.path / "import-jobs")
        jobs.mkdir(exist_ok=True)
        target = self.catalogue._regular_path(jobs / f"{self.job_id}.json")
        if not target.exists():
            write_json(target, job)
        if self.ids.entries != self.initial_ids:
            write_json(self.ids_path, self.ids.entries)
        directory = self.catalogue._regular_path(self.catalogue.path / "assets")
        for asset_id in sorted(self.changed):
            target = Catalogue._regular_path(directory / f"{asset_id}.json")
            if not target.exists() or self.catalogue.read(target) != self.assets[asset_id]:
                write_json(target, self.assets[asset_id])
        directory = self.catalogue._regular_path(self.catalogue.path / "sheets")
        for sheet_id, sheet in sorted(self.sheets.items()):
            if json_text(sheet) != self.initial_sheets.get(sheet_id):
                write_json(Catalogue._regular_path(directory / f"{sheet_id}.json"), sheet)

    def counts(self):
        return {"newAssets": len(self.assets.keys() - self.initial_assets),
                "newIds": len(self.ids.entries.keys() - self.initial_ids.keys())}
