"""Contrôles en lecture seule du catalogue et de son évolution."""

import hashlib
import re
from collections import Counter
from pathlib import PurePosixPath

from tools import asset_versions
from tools.core.catalog import Catalogue, CatalogueScopeError, InvalidJSON, read_json
from tools.core.git_base import read_base
from tools.core.ids import DERIVED, verifier_contre_base, verifier_registre
from tools.core.schemas import schemas

INFERABLE = (
    "description", "orientation", "facing", "state", "category", "subcategory",
    "tags", "originUniverse", "visualStyle", "pivot",
)
COORDINATES = ("x", "y", "w", "h")
RECORDS = {"assets": "asset", "sheets": "sheet"}
IMPORT_TYPES = {"repo-file", "original-sheet-cut", "code-generated"}
PUBLISHED = PurePosixPath("published", "sha256")
PUBLISHED_NAME = re.compile(r"([a-f0-9]{64})\.[A-Za-z0-9][A-Za-z0-9_-]{0,31}")
MUTABLE_VERSION_FIELDS = {"nextVersion", "causalPrevious", "causalNext", "causalOrder", "atlasFrames"}



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
            message = error.message
            if schema == "asset" and suffix == "/creation" and error.validator == "minProperties":
                message = "creation doit contenir searchReceipt ou importJob."
            self.issue(f"{path}#{suffix}", "schema", message)
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
            for problem in asset_versions.problems(asset):
                self.issue(path, "invalid-version-history", problem)
            for field in INFERABLE:
                if asset[field] not in (None, "unknown", []) and field not in asset.get("inference", {}):
                    self.issue(path, "inference-required", f"Trace manquante pour {field}.")
            creation = asset.get("creation", {})
            receipt = creation.get("searchReceipt", {})
            if "results" in receipt:
                rejections = creation.get("rejectedCandidates")
                if (rejections != receipt["rejectedCandidates"] or rejections is None
                        or sorted(row["assetId"] for row in rejections) != sorted(receipt["results"])):
                    self.issue(path, "incomplete-search-receipt", "searchReceipt exige un rejet pour chaque résultat.")
            job = creation.get("importJob")
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

    def revision_proofs(self, assets, sheets):
        publications = set()
        for asset_id, asset in assets.items():
            path = f"catalog/assets/{asset_id}.json"
            for version in asset_versions.history(asset):
                for frame in version.get("atlasFrames", ()):
                    sheet = sheets.get(frame["atlasSheetId"])
                    if (sheet is None or frame["sourceSheetSha256"].lower() != sheet["sha256"].lower()
                            or sheet["dimensions"] is None or not in_bounds(frame, sheet["dimensions"])):
                        self.issue(path, "invalid-atlas-proof", f"Preuve d’atlas invalide pour la version {version['version']}.")
                publication = version.get("publication", {})
                if local := publication.get("registry"):
                    local = PurePosixPath(local)
                    name = PUBLISHED_NAME.fullmatch(local.name)
                    if (local.parent != PUBLISHED or not name or name[1] != version["sha256"].lower()
                            or publication["status"] != "published"):
                        self.issue(path, "invalid-published-path", "Adresse de publication incohérente.")
                    else:
                        publications.add(local.name)
                elif publication and version["version"] == asset_versions.version_number(asset):
                    self.issue(path, "invalid-published-path", "Adresse de publication manquante.")
            provenance = asset["provenance"]
            if parent_id := provenance.get("parentId"):
                parent = assets.get(parent_id)
                parent_number = provenance["parentVersion"]
                versions = asset_versions.history(parent) if parent else []
                if (parent_id != provenance["derivedFrom"] or parent_number > len(versions)
                        or versions[parent_number - 1]["sha256"].lower() != provenance["parentSha256"].lower()):
                    self.issue(path, "invalid-parent-revision", "La révision du parent ne correspond pas à sa preuve.")
        return publications

    def published_files(self, publications):
        path = self.root / PUBLISHED
        try:
            Catalogue._regular_path(path.parent)
            Catalogue._regular_path(path)
            files = sorted(path.iterdir()) if path.exists() else []
        except (OSError, CatalogueScopeError):
            self.issue(PUBLISHED, "invalid-published-store", "Magasin de publication inaccessible.")
            return set()
        found = set()
        digests = set()
        for file in files:
            match = PUBLISHED_NAME.fullmatch(file.name)
            relative = PUBLISHED / file.name
            if not match or file.is_symlink() or not file.is_file():
                self.issue(relative, "invalid-published-file", "Nom ou type de fichier publié invalide.")
                continue
            found.add(file.name)
            if file.name not in publications or match[1] in digests:
                self.issue(relative, "unreferenced-published-file", "Publication absente ou adresse SHA-256 dupliquée.")
            digests.add(match[1])
            with file.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != match[1]:
                    self.issue(relative, "published-digest", "Les octets publiés diffèrent de leur adresse.")
        for missing in sorted(publications - found):
            self.issue(PUBLISHED / missing, "missing-published-file", "Binaire publié introuvable.")
        return found

    def migration_report(self):
        relative = "generated/reports/migration.json"
        path = self.root / relative
        if path.exists():
            try:
                self.document("migration", read_json(Catalogue._regular_path(path)), relative)
            except (OSError, InvalidJSON, CatalogueScopeError) as exc:
                self.issue(relative, "invalid-migration-report", str(exc))

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

    def immutable_revision_changed(self, old, new):
        if any(proof not in new.get("atlasFrames", ()) for proof in old.get("atlasFrames", ())):
            return True
        for field, value in old.items():
            if field in MUTABLE_VERSION_FIELDS or value == new.get(field):
                continue
            if field == "publication" and "registry" not in value:
                updated = new.get("publication", {})
                if "registry" in updated and value == {k: v for k, v in updated.items() if k != "registry"}:
                    continue
            return True
        return False

    def base_rules(self, ref, ids, paths, assets, published):
        base_ids, base_paths, base_document = read_base(self.root, ref)
        from tools.discovery.repos import Git

        git = Git(self.root)
        tracked = git.run("ls-tree", "-rz", "--name-only", ref + "^{commit}", "--", PUBLISHED.as_posix())
        for name in tracked.decode("utf-8", "replace").split("\0"):
            if name and PurePosixPath(name).name not in published:
                self.issue(name, "published-file-removed", "Conserver les octets publiés et leur chemin.")
        for error in verifier_contre_base(base_ids, ids):
            self.issue("catalog/ids.json", "immutable-id", error)
        for path in sorted(base_paths - paths):
            self.issue(path, "record-removed", "Conserver la fiche et déprécier l’asset retiré.")
        derivations = {asset_id: match[1] for key, asset_id in (ids.items() if isinstance(ids, dict) else ())
                       if isinstance(key, str) and isinstance(asset_id, str) and (match := DERIVED.fullmatch(key))}
        for asset_id, asset in assets.items():
            path = PurePosixPath("catalog", "assets", f"{asset_id}.json")
            if path in base_paths:
                prior = base_document(path)
                if not self.document("asset", prior, f"{ref}:{path}"):
                    continue
                earlier = asset_versions.history(prior)
                now = asset_versions.history(asset)
                if (len(now) < len(earlier) or any(
                        self.immutable_revision_changed(old, new)
                        for old, new in zip(earlier, now))):
                    self.issue(path, "immutable-version", "Conserver les versions antérieures et leurs empreintes.")
                continue
            creation = asset.get("creation", {})
            kind = asset["provenance"]["type"]
            atlas_import = kind == "derived" and bool(asset["files"].get("atlasFrames"))
            catalogue_import = (kind == "generated" and bool(asset["files"]["locations"])
                                and asset.get("inference", {}).get("provenance", {}).get("method") == "catalogue-import")
            imported = "importJob" in creation and (kind in IMPORT_TYPES or atlas_import or catalogue_import)
            parent_id = asset["provenance"].get("derivedFrom")
            variant = (kind == "derived" and parent_id in assets and derivations.get(asset_id) == parent_id
                       and asset_id in assets[parent_id]["variants"])
            if not (imported or variant or "searchReceipt" in creation):
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
        published = self.published_files(self.revision_proofs(assets, sheets))
        self.sheet_rules(assets, sheets)
        self.migration_report()
        if base is not None:
            self.base_rules(base, ids, paths, assets, published)
        return self.issues


def in_bounds(region, dimensions):
    return dimensions is None or (
        region["x"] + region["w"] <= dimensions["width"] and region["y"] + region["h"] <= dimensions["height"]
    )


def validate(root, base=None):
    return CatalogueValidation(root).run(base)
