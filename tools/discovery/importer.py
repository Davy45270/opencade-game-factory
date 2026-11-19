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

from tools.core.catalog import Catalogue, InvalidJSON, json_text, write_json
from tools.core.ids import IdRegistry
from tools.core.schemas import schemas
from tools.discovery import enrich, formats
from tools.discovery.repos import is_earlier

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
        self.job_id = job_id
        self.dry_run = dry_run
        self.sightings = defaultdict(list)
        self.changed = set()

    def import_blob(self, references, commit, date, path, raw, measured, earliest):
        digest = hashlib.sha256(raw).hexdigest()
        future = measured.family["type"]
        locations = [location(copy, commit, path, future, tag_only) for copy, tag_only in references]
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
            asset_id = self.ids.allouer(key, future.replace("-", ""), name)
            created = datetime.fromtimestamp(earliest, timezone.utc).isoformat() if earliest is not None else date
            if asset_id not in self.assets:
                evidence = f"{first['repo']}@{commit}:{path}"
                self.assets[asset_id] = _asset(asset_id, name, evidence, created, date, self.job_id,
                                               digest, measured, family, formats.extension(path))
                self.changed.add(asset_id)
            asset = self.assets[asset_id]
            if asset["status"] != "published" and (asset_id not in self.initial_assets
                    or asset["description"].startswith("Ressource ")):
                universe = first["game"].split("/")[-1] if first["game"] else None
                enrich.enrich(asset, path, universe)
                self.changed.add(asset_id)
            if future == "code-generated" and asset["provenance"]["type"] == "repo-file":
                asset["provenance"]["type"] = "code-generated"
                self.changed.add(asset_id)
            if measured.image is not None and "thumbnail" in asset and not self.dry_run:
                thumbnail = self.root / "thumbnails" / digest[:2] / f"{digest}.webp"
                Catalogue._regular_path(thumbnail.parent)
                if not Catalogue._regular_path(thumbnail).exists():
                    _thumbnail(thumbnail, measured.image)
            if asset["createdAt"] is None or is_earlier(created, asset["createdAt"]):
                asset["createdAt"] = created
                self.changed.add(asset_id)
            if asset["updatedAt"] is None or is_earlier(asset["updatedAt"], date):
                asset["updatedAt"] = date
                self.changed.add(asset_id)
            if (future == "code-generated" and asset["status"] != "published"
                    and not is_earlier(date, asset["updatedAt"])):
                if asset["sha256"] != digest:
                    asset["sha256"] = digest
                    asset["inference"]["sha256"] = _trace(f"{first['repo']}@{commit}:{path}")
                    self.changed.add(asset_id)
            self.sightings[asset_id].extend(locations)
            imported_ids.append(asset_id)
        return imported_ids

    def import_region(self, key, name, snapshot, path, digest, pixels):
        family = {"type": "sprite", "sprite": {"frameName": name}}
        asset_id = self.ids.allouer(key, "sprite", name)
        if asset_id not in self.assets:
            evidence = f"{snapshot.repo}@{snapshot.commit}:{path}#{name}"
            measured = formats.Format(family, formats.dimensions(*pixels.size),
                                      pixels.getchannel("A").getextrema()[0] != 255, pixels)
            asset = _asset(asset_id, name, evidence, snapshot.date, snapshot.date, self.job_id,
                           digest, measured, family, "png")
            asset["files"]["sha256Method"] = "canonical-crop-png"
            enrich.enrich(asset, path)
            self.assets[asset_id] = asset
            self.changed.add(asset_id)
        asset = self.assets[asset_id]
        if not self.dry_run and asset.get("thumbnail"):
            path = self.root / asset["thumbnail"]
            Catalogue._regular_path(path.parent)
            if not Catalogue._regular_path(path).exists():
                _thumbnail(path, pixels)
        return asset

    def reconcile(self, commits):
        for asset_id, asset in self.assets.items():
            previous = asset["files"]["locations"]
            latest = self.sightings[asset_id]
            current = {_slot(entry): entry for entry in latest if not entry.get("releaseOnly")}
            history = {(entry["repo"], entry.get("provider"), entry["path"], entry["commit"]): entry
                       for entry in latest if entry.get("releaseOnly")}
            final = []
            for entry in previous:
                identity = _slot(entry)
                commit = commits.get(identity[:2])
                seen = current.get(identity)
                if entry.get("releaseOnly"):
                    released = (*identity, entry["commit"])
                    if released not in history and (seen is None or seen["commit"] != entry["commit"]):
                        final.append(entry)
                elif entry.get("status") == "removed":
                    if seen is None or entry["commit"] != seen["commit"]:
                        history.pop((*identity, entry["commit"]), None)
                        final.append(entry)
                elif seen is not None:
                    # The location still carries the same content on this copy.
                    continue
                elif commit is not None and commit != entry["commit"]:
                    history.pop((*identity, entry["commit"]), None)
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
