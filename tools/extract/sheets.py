"""Planches, tables de découpe et cadres attestés par les arbres Git."""

import hashlib
import io
import posixpath
import re
from collections import defaultdict
from functools import cached_property, lru_cache, partial
from pathlib import PurePosixPath

from PIL import Image

from tools.discovery import formats, references
from tools.extract import magick, regions
from tools.publish import licenses

DIGEST = re.compile(r"[0-9a-fA-F]{64}")
GEOMETRY = re.compile(r"([0-9]{1,10})x([0-9]{1,10})\+([0-9]{1,10})\+([0-9]{1,10})")


def sheet_record(target, digest, name, dimensions, evidence):
    sheet_id = target.sheet_ids.get(digest)
    if sheet_id is None:
        sheet_id = target.ids.allouer(f"sheet:sha256:{digest}", "sheet", name)
        target.sheet_ids[digest] = sheet_id
    return target.sheets.setdefault(sheet_id, {
        "schemaVersion": "1.0", "id": sheet_id, "name": name, "sha256": digest,
        "dimensions": dimensions, "files": {"locations": [], "registry": None},
        "provenance": {"type": "repo-file", "author": "unknown", "evidence": [evidence]},
        "license": "unknown", "status": "needs-review", "regions": [],
    })


def link_region(target, asset, sheet, box, verified, evidence):
    for sheet_id in {asset.get("sourceSheetId"), sheet["id"] if sheet else None}:
        if sheet_id in target.sheets:
            old = target.sheets[sheet_id]["regions"]
            target.sheets[sheet_id]["regions"] = [item for item in old if item["assetId"] != asset["id"]]
    asset["sourceSheetId"] = sheet["id"] if sheet else None
    asset["sourceRegion"] = {**box, "verified": verified, "evidence": evidence} if box else None
    if sheet and box:
        sheet["regions"].append({**box, "assetId": asset["id"], "evidence": evidence,
                                 "status": "verified" if verified else "needs-review"})
        sheet["status"] = ("active" if all(item["status"] == "verified" for item in sheet["regions"])
                           else "needs-review")


def table_entries(document):
    if not isinstance(document, dict) or not isinstance(document.get("elements"), list):
        return []
    fields = ("planche", "planche_sha256", "marge", "ancre", "taille", "licence", "detoure", "effacements",
              "couverture_min", "masque_max")
    defaults = {field: document[field] for field in fields if field in document}
    return [{**defaults, **item} for item in document["elements"] if isinstance(item, dict)]


def provenance_entries(document):
    if isinstance(document, dict):
        entries = document.get("assets")
        return [item for item in entries if isinstance(item, dict)] if isinstance(entries, list) else []
    if isinstance(document, list):
        return [{**item, **item["origine"], "planche_sha256": item["origine"].get("sha256"), "origine": "planche"}
                for item in document if isinstance(item, dict) and isinstance(item.get("origine"), dict)]
    return []


def _region_key(sheet_id, box):
    return f"region:{sheet_id}:" + ",".join(str(box[k]) for k in regions.COORDINATES)


def _geometry(value):
    match = GEOMETRY.fullmatch(value) if isinstance(value, str) else None
    return regions.named_box(tuple(map(int, match.groups()))) if match else None


def _raccords(document, entry, box, margin):
    if not isinstance(document, list) or not box or type(margin) is not int or margin < 0:
        raise ValueError("Recette ou découpe invalide.")
    element = _element_id(entry["id"])
    matches = [item for item in document if isinstance(item, dict) and _element_id(item.get("id")) == element]
    if len(matches) != 1:
        raise ValueError("Identifiant de retouche absent ou ambigu.")
    recipe, = matches
    recipe_margin = recipe.get("marge", margin)
    if _geometry(recipe.get("boite")) != box or type(recipe_margin) is not int or recipe_margin != margin:
        raise ValueError("Géométrie de retouche absente, ambiguë ou différente de la provenance.")
    raccords = recipe.get("raccords", [])
    if not isinstance(raccords, list):
        raise ValueError("Liste de raccords invalide.")
    result = []
    for pair in raccords:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("Paire de raccord invalide.")
        band, target = map(_geometry, pair)
        if not band or not target:
            raise ValueError("Géométrie de raccord invalide.")
        result.append((band, target))
    return result


class SheetDiscovery:
    @cached_property
    def magick_installation(self):
        return magick.installed()

    def __init__(self, target, snapshots, git):
        self.target = target
        self.git = git
        self.snapshots = snapshots
        self.images = defaultdict(list)
        self.limits = []
        self.path_aliases = {}
        self.processed = {}
        self._image = lru_cache(maxsize=4)(self._read_image)
        self.declarations = {}
        for snapshot in snapshots:
            for path, asset_ids in snapshot.indexed.items():
                if formats.extension(path) in formats.RASTER and path not in snapshot.generated_paths:
                    asset = self._image_record(snapshot, path, asset_ids[0])
                    self.images[asset["sha256"]].append((snapshot, path, asset))

    def _image_record(self, snapshot, path, asset_id):
        asset = self.target.assets[asset_id]
        version = self.target.version_at(asset_id, snapshot, path)
        return {"sha256": asset["versions"][version - 1]["sha256"],
                "dimensions": snapshot.measurements[path][2],
                "locations": [{key: value for key, value in loc.items() if key != "assetVersion"}
                              for loc in asset["files"]["locations"] if loc.get("assetVersion", 1) == version]}

    def _sheet(self, snapshot, path, asset):
        sheet = sheet_record(self.target, asset["sha256"], PurePosixPath(path).stem, asset["dimensions"],
                             f"{snapshot.repo}@{snapshot.commit}:{path}")
        sheet["dimensions"] = asset["dimensions"]
        # One sheet can have matching bytes in several independently versioned sources.
        def identity(loc):
            return loc["repo"], loc.get("provider") or "", loc["path"]

        def key(loc):
            return (*identity(loc), loc["commit"], loc.get("releaseOnly", False), loc.get("status", "active"))

        sightings = [loc for _, _, record in self.images[asset["sha256"]] for loc in record["locations"]]
        observed = {(identity(loc), loc["commit"]) for loc in sightings if not loc.get("releaseOnly")}
        active = {identity(loc) for loc in sightings
                  if not loc.get("releaseOnly") and loc.get("status", "active") == "active"}
        existing = {key(loc): loc for loc in sheet["files"]["locations"]
                    if loc.get("releaseOnly") or loc.get("status") == "removed"
                    or (identity(loc) not in active and (identity(loc), loc["commit"]) not in observed)}
        existing.update((key(loc), loc) for loc in sightings)
        sheet["files"]["locations"] = [existing[slot] for slot in sorted(existing)]
        return sheet

    def _source(self, snapshot, entry, metadata_path):
        raw_digest = entry.get("planche_sha256")
        name = entry.get("planche")
        name = PurePosixPath(name).name if isinstance(name, str) and name.strip() else None
        evidence = f"{metadata_path}@{snapshot.commit}"
        if isinstance(raw_digest, str) and DIGEST.fullmatch(raw_digest):
            digest = raw_digest.lower()
            locations = self.images.get(digest)
            if locations:
                other, path, asset = next((item for item in locations if item[0] is snapshot), locations[0])
                return self._sheet(other, path, asset), other, path
            sheet = sheet_record(self.target, digest, name or digest[:16], None, evidence)
            self.limits.append({"repo": snapshot.repo, "commit": snapshot.commit, "path": metadata_path,
                                "sheetId": sheet["id"], "sha256": digest, "reason": "source-sheet-unavailable"})
            return sheet, None, None
        if raw_digest is not None or not name:
            return None, None, None
        location = entry["planche"]
        local = references.resolve(metadata_path, references.Reference(location, 1, "table"),
                                   snapshot.tree, snapshot.indexed)
        basename_matches = [(other, path, asset) for records in self.images.values()
                            for other, path, asset in records if PurePosixPath(path).name == name
                            and (other is snapshot or _david_path(other, path))]
        if (len(local) == 1 and formats.extension(local[0]) in formats.RASTER
                and local[0] not in snapshot.generated_paths):
            path = local[0]
            asset = self._image_record(snapshot, path, snapshot.indexed[path][0])
            return self._sheet(snapshot, path, asset), snapshot, path
        if len({asset["sha256"] for _, _, asset in basename_matches}) == 1:
            other, path, asset = basename_matches[0]
            return self._sheet(other, path, asset), other, path
        self.limits.append({"repo": snapshot.repo, "commit": snapshot.commit, "path": metadata_path,
                            "reason": "source-sheet-unresolved", "sheet": name})
        return None, None, None

    def _read_image(self, snapshot, path):
        with self.git.batch(snapshot.mirror) as batch:
            raw = batch.read(snapshot.tree[path], snapshot.tree[path].size)
        with Image.open(io.BytesIO(raw)) as image:
            return image.convert("RGBA")

    def _resolve(self, snapshot, path, value, available, field):
        candidates = references.candidates(path, value, snapshot.tree)
        for candidate in candidates:
            if candidate in available and not snapshot.tree[candidate].symlink:
                return candidate
        if any(candidate in snapshot.tree for candidate in candidates):
            return None
        alias = references.resolve_path_alias(candidates, snapshot.path_aliases, available)
        if alias:
            cited, resolved = alias
            key = snapshot.repo, snapshot.commit, path, field, value, cited, resolved
            self.path_aliases[key] = {"repo": snapshot.repo, "commit": snapshot.commit, "path": path,
                                      "field": field, "reference": value, "from": cited, "to": resolved}
            return resolved
        return None

    def _declaration(self, snapshot, atlas_path, frame_name, image_path, atlas_files):
        frame = _element_id(frame_name)
        matches = []
        for metadata_path, provenance, entry in self.declarations[snapshot].get(frame, ()):
            atlas = entry.get("atlas")
            if isinstance(atlas, str):
                resolved = self._resolve(snapshot, metadata_path, atlas, atlas_files, "atlas")
                if resolved not in {atlas_path, image_path}:
                    continue
            scope = posixpath.commonpath([atlas_path, metadata_path])
            matches.append((bool(atlas), provenance, len(scope), metadata_path, entry))
        if not matches:
            return None
        matches.sort(key=lambda match: match[:3], reverse=True)
        best = matches[0]
        ties = [match for match in matches if match[:3] == best[:3]]
        if any(match[-1] != best[-1] for match in ties):
            self.limits.append({"repo": snapshot.repo, "commit": snapshot.commit, "path": atlas_path,
                                "reason": "ambiguous-provenance", "frame": frame_name})
            return None
        if best[1]:
            # The table may carry normalisation options omitted by the provenance writer.
            tables = [match[-1] for match in matches if not match[1]
                      and match[-1].get("planche") == best[-1].get("planche")
                      and match[-1].get("boite") == best[-1].get("boite")]
            if len(tables) == 1:
                return best[3], {**tables[0], **best[4]}
        return best[3], best[4]

    def _frame(self, snapshot, atlas_path, sheet, image, frame, image_path, atlas_files):
        box = {key: frame[key] for key in regions.COORDINATES}
        if not regions.in_image(box, image):
            self.limits.append({"repo": snapshot.repo, "commit": snapshot.commit, "path": atlas_path,
                                "reason": "atlas-frame-out-of-bounds", "frame": frame["name"]})
            return
        name = frame["name"]
        cropped = regions.crop(image, box)
        digest = hashlib.sha256(regions.canonical_png(cropped)).hexdigest()
        key = _region_key(sheet["id"], box)
        atlas_frame = {"atlasSheetId": sheet["id"], **box}
        asset, number = self.target.import_region(
            key, name, snapshot, atlas_path, image_path, digest, cropped, atlas_frame, sheet)
        snapshot.indexed[atlas_path].append(asset["id"])
        snapshot.frame_sources[asset["id"], atlas_path] = image_path
        if number != asset["version"] or asset["status"] == "published":
            return
        if atlas_frame not in asset["files"].setdefault("atlasFrames", []):
            asset["files"]["atlasFrames"].append(atlas_frame)
            self.target.changed.add(asset["id"])
        declaration = self._declaration(snapshot, atlas_path, name, image_path, atlas_files)
        release_only = all(release for _, _, release, _ in snapshot.members)
        priority = (not release_only, declaration is not None)
        if self.processed.get(asset["id"], ()) >= priority:
            return
        self.processed[asset["id"]] = priority
        self.target.changed.add(asset["id"])
        if declaration:
            self._apply_declaration(snapshot, asset, cropped, name, declaration)
            return
        previous_license = asset.get("licenseEvidence")
        if isinstance(previous_license, dict) and previous_license["method"] == "provenance-file":
            asset["license"] = "unknown"
            asset.pop("licenseEvidence", None)
        if "sourceSheetSha256" in asset["provenance"] or asset["provenance"]["type"] == "derived":
            asset["provenance"] = {"type": "repo-file", "author": "unknown", "evidence": [f"{atlas_path}@{snapshot.commit}"]}
        link_region(self.target, asset, sheet, box, True, f"atlas {atlas_path}@{snapshot.commit}")

    def _apply_declaration(self, snapshot, asset, cropped, frame, declaration):
        metadata_path, entry = declaration
        ref = f"{metadata_path}@{snapshot.commit}"
        asset["provenance"] = {"type": "repo-file", "author": "unknown", "evidence": [ref]}
        asset["license"] = "unknown"
        asset.pop("licenseEvidence", None)
        if entry.get("origine") == "redessiné (marque)":
            replacement = entry.get("element_remplace")
            if isinstance(replacement, str) and replacement.strip():
                asset["provenance"]["evidence"] = [replacement]
            asset["provenance"]["type"] = "derived"
            link_region(self.target, asset, None, None, False, ref)
            return
        source, other, path = self._source(snapshot, entry, metadata_path)
        box = regions.named_box(entry.get("boite"))
        margin = entry.get("marge", 0)
        rmse = None
        if source:
            asset["provenance"]["sourceSheetSha256"] = source["sha256"]
        tool = {}
        try:
            normalizer = None
            if declared := entry.get("_magick"):
                if self.magick_installation is None:
                    raise magick.MagickError("magick-unavailable")
                executable, version = self.magick_installation
                if version.split(".")[0].lstrip("0") != declared.split(".")[0].lstrip("0"):
                    raise magick.MagickError("magick-major-version-mismatch")
                normalizer = partial(magick.normalize, executable)
                tool = {"tool": "magick", "toolVersion": version}
            if "source_retouche" in entry:
                rmse = self._measure_retouched(snapshot, metadata_path, entry, box, margin, cropped, other, path,
                                               normalizer=normalizer)
            elif other and box and type(margin) is int and margin >= 0:
                rmse = regions.measure(self._image(other, path), entry["boite"], margin, cropped,
                                       entry.get("ancre"), options=entry, normalizer=normalizer)
        except (magick.MagickError, regions.RaccordCoverageError) as exc:
            self.limits.append({"repo": snapshot.repo, "commit": snapshot.commit, "path": metadata_path,
                                "reason": str(exc), "frame": frame})
        verified = rmse is not None and rmse <= regions.THRESHOLD
        evidence = ({"method": "rmse", "value": rmse, "ref": ref, **tool} if rmse is not None
                    else f"Comparaison indisponible · {ref}")
        if source and box and not _within_sheet(box, source):
            self.limits.append({"repo": snapshot.repo, "commit": snapshot.commit, "path": metadata_path,
                                "reason": "source-region-out-of-bounds", "frame": asset["name"]})
            box = None
        link_region(self.target, asset, source, box if source else None, verified, evidence)
        from_provenance = bool(entry.get("planche_sha256") and PurePosixPath(metadata_path).name == "provenance.json")
        trusted = source and (from_provenance or any(_david_location(loc) for loc in source["files"]["locations"]))
        derived = entry.get("origine") == "dérivé" or bool(entry.get("effacements")) or "source_retouche" in entry
        if derived:
            asset["provenance"]["type"] = "derived"
        if verified and trusted and not derived:
            asset["provenance"]["type"] = "original-sheet-cut"
            licenses.assign(asset, "CC-BY-4.0", "provenance-file", ref, licenses.DAVID_DECISION)
        explicit = entry.get("licence")
        if verified and licenses.explicit_spdx(explicit) and explicit != asset["license"]:
            licenses.assign(asset, explicit, "provenance-file", ref, "Licence SPDX déclarée, découpe vérifiée.")
        if not verified:
            asset["status"] = "needs-review"

    def _measure_retouched(self, snapshot, metadata_path, entry, box, margin, cropped, other, path, *, normalizer):
        recipe = entry["source_retouche"]
        candidates = (references.candidates(metadata_path, recipe, snapshot.tree)
                      if isinstance(recipe, str) and recipe.endswith(".retouches.json") else ())
        recipe_path = next((candidate for candidate in candidates if candidate in snapshot.tree), None)
        try:
            raccords = _raccords(snapshot.metadata.get(recipe_path), entry, box, margin)
            if raccords and other:
                image = self._image(other, path)
                if not regions.in_image(box, image):
                    raise ValueError("Découpe de retouche hors planche.")
                return regions.measure(image, entry["boite"], margin, cropped, entry.get("ancre"),
                                       options=entry, raccords=raccords, normalizer=normalizer)
        except (magick.MagickError, regions.RaccordCoverageError):
            raise
        except ValueError:
            reason = "declared-retouch-unreadable"
        else:
            if raccords:
                return None  # L’indisponibilité de la planche est déjà signalée.
            reason = "declared-retouch-without-raccords"
        self.limits.append({"repo": snapshot.repo, "commit": snapshot.commit, "path": metadata_path,
                            "reason": reason, "frame": entry["id"],
                            "recipe": recipe_path or (recipe if isinstance(recipe, str) else None)})
        return None

    def _read_declarations(self, snapshot):
        entries_by_id = defaultdict(list)
        for path, document in snapshot.metadata.items():
            provenance = PurePosixPath(path).name == "provenance.json"
            if not provenance and not path.endswith(".decoupe.json"):
                continue
            if document is None:
                self.limits.append({"repo": snapshot.repo, "commit": snapshot.commit, "path": path,
                                    "reason": "invalid-sheet-metadata"})
                continue
            tools = document.get("outils") if isinstance(document, dict) else None
            version = tools.get("magick") if isinstance(tools, dict) else None
            for entry in provenance_entries(document) if provenance else table_entries(document):
                if element := _element_id(entry.get("id")):
                    entry = {key: value for key, value in entry.items() if key != "_magick"}
                    if isinstance(version, str) and magick.VERSION.fullmatch(version):
                        entry["_magick"] = version
                    entries_by_id[element].append((path, provenance, entry))
        return entries_by_id

    def run(self):
        for records in self.images.values():
            for snapshot, path, asset in records:
                if max(asset["dimensions"].values()) >= 512 and _sheet_path(path):
                    self._sheet(snapshot, path, asset)
                    break
        for snapshot in self.snapshots:
            self.declarations[snapshot] = self._read_declarations(snapshot)
            atlas_images = {path for path in snapshot.indexed if formats.extension(path) in formats.RASTER
                            and path not in snapshot.generated_paths}
            atlas_files = atlas_images | {path for path, (family, _, _) in snapshot.measurements.items()
                                          if family["type"] == "atlas"}
            for atlas_path, (family, metadata, _) in snapshot.measurements.items():
                if family["type"] != "atlas":
                    continue
                image = metadata["atlasImage"]
                image_path = self._resolve(snapshot, atlas_path, image, atlas_images, "meta.image")
                if not image_path:
                    self.limits.append({"repo": snapshot.repo, "commit": snapshot.commit, "path": atlas_path,
                                        "reason": "atlas-image-unresolved"})
                    continue
                asset = self._image_record(snapshot, image_path, snapshot.indexed[image_path][0])
                sheet = self._sheet(snapshot, image_path, asset)
                pixels = self._image(snapshot, image_path)
                for frame in family["frames"]:
                    self._frame(snapshot, atlas_path, sheet, pixels, frame, image_path, atlas_files)
        self._image.cache_clear()
        return self.limits


def _within_sheet(box, sheet):
    dim = sheet["dimensions"]
    return not dim or (box["x"] + box["w"] <= dim["width"] and box["y"] + box["h"] <= dim["height"])


def _element_id(value):
    return PurePosixPath(value).name.removeprefix("sprite-") if isinstance(value, str) else None


def _david_path(snapshot, path):
    return snapshot.repo == "jeux-assets" and path.startswith("planches/")


def _david_location(location):
    return location["repo"] == "jeux-assets" and location["path"].startswith("planches/")

def _sheet_path(path):
    parts = PurePosixPath(path.casefold()).parts
    return any(p in {"planches", "sources"} for p in parts[:-1]) or bool(re.search("planche|sheet", parts[-1]))
