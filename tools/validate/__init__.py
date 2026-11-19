"""Contrôles en lecture seule du catalogue et de son évolution."""

from collections import Counter
from pathlib import PurePosixPath

from tools.core.catalog import Catalogue, InvalidJSON
from tools.core.git_base import read_base
from tools.core.ids import verifier_contre_base, verifier_registre
from tools.core.schemas import schemas

INFERABLE = (
    "description", "orientation", "facing", "state", "category", "subcategory",
    "tags", "originUniverse", "visualStyle", "pivot",
)
COORDINATES = ("x", "y", "w", "h")
RECORDS = {"assets": "asset", "sheets": "sheet"}
IMPORT_TYPES = {"repo-file", "original-sheet-cut", "code-generated"}


class CatalogueValidation:
    def __init__(self, root):
        self.catalogue = Catalogue(root)
        self.root = root
        self.issues = []
        self.schemas = schemas()

    def issue(self, path, code, message):
        self.issues.append({"path": str(path), "code": code, "message": message})

    def load(self, path):
        try:
            return True, self.catalogue.read(self.catalogue.path / path)
        except InvalidJSON as exc:
            self.issue(path, "invalid-json", str(exc))
            return False, None

    def document(self, schema, value, path):
        valid = True
        for error in self.schemas.validator(schema).iter_errors(value):
            suffix = "".join(
                "/" + str(part).replace("~", "~0").replace("/", "~1")
                for part in error.absolute_path
            )
            self.issue(f"{path}#{suffix}", "schema", error.message)
            valid = False
        return valid

    def sources(self):
        path = "sources.json"
        loaded, sources = self.load(path)
        if not loaded:
            return
        if not isinstance(sources, list):
            from tools.discovery.repos import source_problems

            for problem in source_problems(sources):
                self.issue(path, "schema", problem)
            return
        seen = set()
        for index, source in enumerate(sources):
            location = f"{path}/{index}"
            if self.document("source", source, location):
                if source["repo"] in seen:
                    self.issue(location, "duplicate-source", "Nom canonique de dépôt déjà utilisé.")
                seen.add(source["repo"])

    def records(self):
        declared = Counter()
        paths = set()
        records = {collection: {} for collection in RECORDS}
        for collection in RECORDS:
            for file in self.catalogue.documents(collection):
                path = PurePosixPath("catalog", collection, file.name)
                paths.add(path)
                loaded, record = self.load(PurePosixPath(collection, file.name))
                if not loaded:
                    continue
                if isinstance(record, dict) and isinstance(record.get("id"), str):
                    record_id = record["id"]
                    declared[record_id] += 1
                    if declared[record_id] > 1:
                        self.issue(path, "duplicate-id", f"ID déjà déclaré : {record_id}")
                    if record_id != file.stem:
                        self.issue(path, "id-filename", "Le nom du fichier doit correspondre à l’ID.")
                if self.document(RECORDS[collection], record, path):
                    records[collection].setdefault(record["id"], record)
        for file in self.catalogue.documents("universes"):
            path = PurePosixPath("universes", file.name)
            loaded, universe = self.load(path)
            if loaded and (not isinstance(universe, dict) or universe.get("id") != file.stem):
                self.issue(path, "id-filename", "L’univers doit déclarer l’ID de son fichier.")
            elif loaded:
                declared[universe["id"]] += 1
                if declared[universe["id"]] > 1:
                    self.issue(path, "duplicate-id", f"ID déjà déclaré : {universe['id']}")
        return records, paths

    def asset_rules(self, assets, sheets):
        for asset_id, asset in assets.items():
            path = f"catalog/assets/{asset_id}.json"
            for field in INFERABLE:
                if asset[field] not in (None, "unknown", []) and field not in asset.get("inference", {}):
                    self.issue(path, "inference-required", f"Trace manquante pour {field}.")
            job = asset.get("creation", {}).get("importJob")
            if isinstance(job, str):
                from tools.discovery.jobs import job_id

                jobs = self.catalogue._regular_path(self.catalogue.path / "import-jobs")
                job_file = jobs / f"{job}.json"
                if not job_file.is_file():
                    self.issue(path, "missing-import-job", f"Job d’import introuvable ({job}).")
                else:
                    loaded, contract = self.load(PurePosixPath("import-jobs", f"{job}.json"))
                    if loaded and self.document("import-job", contract, f"catalog/import-jobs/{job}.json"):
                        if "inputs" not in contract or job_id(contract["inputs"]) != job:
                            self.issue(path, "invalid-import-job", f"Entrées incompatibles avec le job {job}.")
            sheet_id = asset["sourceSheetId"]
            region = asset["sourceRegion"]
            sheet = sheets.get(sheet_id)
            if not sheet and (sheet_id is not None or region is not None):
                self.issue(path, "missing-sheet", f"Planche source introuvable : {sheet_id!r}")
            if sheet:
                digest = asset["provenance"].get("sourceSheetSha256")
                if digest and digest.lower() != sheet["sha256"].lower():
                    self.issue(path, "sheet-digest", "Empreinte différente de la planche source.")
                if region is not None and not in_bounds(region, sheet["dimensions"]):
                    self.issue(path, "region-bounds", "La région dépasse les dimensions de la planche.")
                if region and region["verified"] and sheet["dimensions"] is None:
                    self.issue(path, "region-unmeasurable", "Une région vérifiée exige les dimensions de la planche.")
            for frame in asset["files"].get("atlasFrames", ()):
                atlas = sheets.get(frame["atlasSheetId"])
                if atlas is None or atlas["dimensions"] is None or not in_bounds(frame, atlas["dimensions"]):
                    self.issue(path, "atlas-frame", "Cadre hors limites ou planche technique introuvable.")
            references = list(asset["variants"])
            if parent := asset["provenance"].get("derivedFrom"):
                references.append(parent)
            for reference in references:
                if reference not in assets or reference == asset_id:
                    self.issue(path, "invalid-asset-reference", f"Référence d’asset invalide : {reference}")

    def sheet_rules(self, assets, sheets):
        for sheet_id, sheet in sheets.items():
            for index, region in enumerate(sheet["regions"]):
                path = f"catalog/sheets/{sheet_id}.json#/regions/{index}"
                if not in_bounds(region, sheet["dimensions"]):
                    self.issue(path, "region-bounds", "La région dépasse les dimensions de la planche.")
                if (asset_id := region["assetId"]) is None:
                    continue
                asset = assets.get(asset_id)
                if asset is None:
                    self.issue(path, "missing-region-asset", f"Asset introuvable : {asset_id}")
                    continue
                reverse = asset["sourceRegion"]
                if (asset["sourceSheetId"] != sheet_id or reverse is None
                        or any(reverse[key] != region[key] for key in COORDINATES)
                        or reverse["verified"] != (region["status"] == "verified")):
                    self.issue(path, "region-back-reference", f"Région source incohérente pour {asset_id}.")

    def base_rules(self, ref, ids, paths, assets):
        base_ids, base_paths = read_base(self.root, ref)
        for error in verifier_contre_base(base_ids, ids):
            self.issue("catalog/ids.json", "immutable-id", error)
        for path in sorted(base_paths - paths):
            self.issue(path, "record-removed", "Conserver la fiche et déprécier l’asset retiré.")
        for asset_id, asset in assets.items():
            path = PurePosixPath("catalog", "assets", f"{asset_id}.json")
            if path in base_paths:
                continue
            creation = asset.get("creation", {})
            kind = asset["provenance"]["type"]
            atlas_import = kind == "derived" and bool(asset["files"].get("atlasFrames"))
            catalogue_import = (kind == "generated" and bool(asset["files"]["locations"])
                                and asset.get("inference", {}).get("provenance", {}).get("method") == "catalogue-import")
            imported = "importJob" in creation and (kind in IMPORT_TYPES or atlas_import or catalogue_import)
            if not (imported or "searchReceipt" in creation):
                self.issue(path, "creation-required", "Un reçu de recherche ou un job d’import est requis.")

    def run(self, base=None):
        self.sources()
        loaded, ids = self.load("ids.json")
        errors = verifier_registre(ids) if loaded else []
        for error in errors:
            self.issue("catalog/ids.json", "invalid-id-registry", error)
        records, paths = self.records()
        assets, sheets = records["assets"], records["sheets"]
        if loaded and not errors:
            allocated = set(ids.values())
            for record_id in sorted((assets.keys() | sheets.keys()) - allocated):
                self.issue("catalog/ids.json", "unregistered-id", f"ID non alloué : {record_id}")
        self.asset_rules(assets, sheets)
        self.sheet_rules(assets, sheets)
        if base is not None:
            self.base_rules(base, ids, paths, assets)
        return self.issues


def in_bounds(region, dimensions):
    return dimensions is None or (
        region["x"] + region["w"] <= dimensions["width"] and region["y"] + region["h"] <= dimensions["height"]
    )


def validate(root, base=None):
    return CatalogueValidation(root).run(base)
