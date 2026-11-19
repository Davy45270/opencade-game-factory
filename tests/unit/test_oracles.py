import contextlib
import copy
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HASH = "a" * 64
ASSET_ID = "asset-kitchen-fouet-0001"
SHEET_ID = "sheet-cuisine-0001"
KEY = f"file:sha256:{HASH}"
KEY2 = f"file:sha256:{'b' * 64}"
IDS = {KEY: ASSET_ID}
TRACE = {"method": "path-tokens", "confidence": 0.8, "evidence": ["chemin du fichier"]}
FIELDS = """
schemaVersion id name description category subcategory tags originUniverse visualStyle
sourceSheetId sourceRegion orientation facing state dimensions format alpha pivot files
sha256 provenance license status usages variants createdAt updatedAt
""".split()
MUTATIONS = "import-sheet extract register derive publish scan-repos sync index".split()
COMMANDS = [*MUTATIONS, "search", "inspect", "validate", "usage", "duplicates"]

ASSET = {
    "schemaVersion": "1.0", "id": ASSET_ID, "name": "Fouet",
    "description": "unknown", "category": "kitchen", "subcategory": "unknown",
    "tags": [], "originUniverse": "unknown", "visualStyle": "unknown",
    "sourceSheetId": None, "sourceRegion": None, "orientation": "unknown",
    "facing": "unknown", "state": "unknown", "dimensions": {"width": 16, "height": 16},
    "format": "png", "alpha": True, "pivot": None, "files": {"locations": []},
    "sha256": HASH, "provenance": {"type": "generated", "author": "unknown", "evidence": []},
    "license": "unknown", "status": "draft", "usages": [], "variants": [],
    "createdAt": "2026-11-19T08:00:00Z", "updatedAt": None,
    "family": {"type": "image", "image": {}}, "inference": {"category": TRACE},
}


class CatalogueOracles(unittest.TestCase):
    def setUp(self):
        with contextlib.ExitStack() as cleanup:
            self.root = Path(cleanup.enter_context(tempfile.TemporaryDirectory(dir=ROOT)))
            self.addCleanup(cleanup.pop_all().close)
        for name in ("assets", "sheets", "universes"):
            (self.root / "catalog" / name).mkdir(parents=True)
        self.write("sources.json", [])
        self.write("ids.json", IDS)
        self.asset = copy.deepcopy(ASSET)
        self.write_asset()

    def write(self, path, value):
        (self.root / "catalog" / path).write_text(
            json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def write_asset(self):
        self.write(f"assets/{ASSET_ID}.json", self.asset)

    def cli(self, *args):
        from tools.cli import main
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = main([*args, "--json"], root=self.root)
        return code, json.loads(output.getvalue())

    def validate_asset(self, expected):
        self.write_asset()
        code, payload = self.cli("validate")
        self.assertEqual(code, expected, payload)
        return payload

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def commit_base(self):
        self.git("init", "-q")
        self.git("add", "catalog/ids.json", "catalog/sources.json")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "Base de test")

    def test_T01_27_champs_obligatoires(self):
        self.validate_asset(0)
        for field in FIELDS:
            with self.subTest(field=field):
                self.asset = copy.deepcopy(ASSET)
                del self.asset[field]
                self.validate_asset(1)

    def test_T02_orientations(self):
        self.asset["inference"]["orientation"] = TRACE
        for orientation in ("front", "back", "left", "right", "top", "bottom",
                            "three-quarter", "isometric", "unknown", "diagonal"):
            with self.subTest(orientation=orientation):
                self.asset["orientation"] = orientation
                self.validate_asset(1 if orientation == "diagonal" else 0)

    def test_T03_inference_et_preuve(self):
        self.asset["description"] = "Un fouet"
        self.validate_asset(1)
        self.asset["inference"]["description"] = {**TRACE, "method": "proven"}
        self.validate_asset(1)
        self.asset["inference"]["description"] = TRACE
        self.validate_asset(0)
        self.asset["inference"]["description"] = {**TRACE, "method": "proven", "confidence": 1}
        self.validate_asset(0)

    def test_T04_ids_en_double(self):
        self.write("assets/autre.json", self.asset)
        code, payload = self.cli("validate")
        self.assertEqual(code, 1)
        self.assertIn("duplicate-id", {issue["code"] for issue in payload["issues"]})

    def test_T05_registre_immuable_et_allocation(self):
        from tools.core.ids import IdRegistry, verifier_contre_base
        for head in ({}, {KEY2: ASSET_ID}, {KEY: "asset-kitchen-fouet-0002"}):
            with self.subTest(head=head):
                self.assertTrue(verifier_contre_base(IDS, head))
        registry = IdRegistry(IDS)
        self.assertEqual(registry.allouer(KEY, "autre", "Autre"), ASSET_ID)
        second = registry.allouer(KEY2, "kitchen", "Fouet")
        self.assertEqual(second, "asset-kitchen-fouet-0002")
        self.asset["status"] = "deprecated"
        self.validate_asset(0)
        self.assertEqual(registry.allouer(f"file:sha256:{'c' * 64}", "kitchen", "Fouet"),
                         "asset-kitchen-fouet-0003")
        self.assertFalse(verifier_contre_base(IDS, registry.entries))

    def test_T06_references(self):
        self.asset["sourceSheetId"] = SHEET_ID
        self.validate_asset(1)
        self.asset["sourceSheetId"] = None
        self.asset["variants"] = ["asset-kitchen-fouet-0099"]
        self.validate_asset(1)
        self.asset["variants"] = []
        self.asset["provenance"]["derivedFrom"] = "asset-kitchen-fouet-0099"
        self.validate_asset(1)
        del self.asset["provenance"]["derivedFrom"]
        self.write("ids.json", {**IDS, KEY2: SHEET_ID})
        sheet = {field: self.asset[field] for field in (
            "schemaVersion", "name", "dimensions", "files", "provenance", "license"
        )}
        sheet.update(id=SHEET_ID, sha256="b" * 64, regions=[
            dict(x=0, y=0, w=16, h=16, status="candidate", evidence=["cadre"], assetId=None)
        ])
        self.write(f"sheets/{SHEET_ID}.json", sheet)
        self.validate_asset(0)
        sheet["regions"][0]["assetId"] = "asset-kitchen-fouet-0099"
        self.write(f"sheets/{SHEET_ID}.json", sheet)
        self.validate_asset(1)
        sheet["regions"][0]["assetId"] = ASSET_ID
        self.write(f"sheets/{SHEET_ID}.json", sheet)
        self.validate_asset(1)
        self.asset["sourceSheetId"] = SHEET_ID
        self.asset["sourceRegion"] = dict(x=0, y=0, w=16, h=16, verified=False, evidence=["cadre"])
        self.validate_asset(0)

    def test_T07_import_en_lecture_seule(self):
        from tools.core.schemas import SchemaSet
        job = import_job()
        schema = SchemaSet().validator("import-job")
        self.assertTrue(schema.is_valid(job))
        for field in job["safety"]:
            with self.subTest(field=field):
                unsafe = copy.deepcopy(job)
                unsafe["safety"][field] = True
                self.assertFalse(schema.is_valid(unsafe))

    def test_T08_json_toutes_commandes_et_dry_run(self):
        for command in COMMANDS:
            with self.subTest(command=command):
                args = [ASSET_ID] if command == "inspect" else []
                code, payload = self.cli(command, *args)
                if command in ("validate", "inspect"):
                    self.assertEqual(code, 0, payload)
                else:
                    self.assertEqual(code, 2, payload)
                    self.assertEqual(payload["error"], "not-implemented")
                    self.assertIn(payload["lot"], {"L2", "L3"})
                if command in MUTATIONS:
                    self.assertEqual(self.cli(command, "--dry-run"), (code, payload))
        self.assertEqual(self.cli("index", "rebuild", "--dry-run"), self.cli("index"))

    def test_AT10_nouvel_asset_exige_un_recu_ou_import(self):
        self.commit_base()
        code, payload = self.cli("validate", "--base", "HEAD")
        self.assertEqual(code, 1, payload)
        self.assertIn("creation-required", {issue["code"] for issue in payload["issues"]})
        self.asset["creation"] = {"searchReceipt": {
            "query": "fouet propre", "rejectedCandidates": [
                {"assetId": ASSET_ID, "reason": " "}
            ],
        }}
        self.write_asset()
        self.assertEqual(self.cli("validate", "--base", "HEAD")[0], 1)
        self.asset["creation"]["searchReceipt"]["rejectedCandidates"] = []
        self.write_asset()
        self.assertEqual(self.cli("validate", "--base", "HEAD")[0], 0)
        self.asset["provenance"]["type"] = "repo-file"
        self.asset["creation"] = {"importJob": import_job()}
        self.write_asset()
        self.assertEqual(self.cli("validate", "--base", "HEAD")[0], 0)


def import_job():
    return {
        "schemaVersion": "1.0", "jobType": "initial-discovery",
        "sources": {"provider": "github", "scope": "authorized-game-repositories",
                    "includeMonorepos": True, "includeReleases": True},
        "discovery": dict.fromkeys(("images", "animations", "tilemaps", "audio", "fonts",
                                    "generatedAssets", "codeReferences"), True),
        "processing": dict.fromkeys(("extractSpritesheets", "describeWithAI", "detectDuplicates",
                                     "buildUsageGraph", "verifyLicenses"), True),
        "safety": dict.fromkeys(("modifySourceRepositories", "deleteSourceFiles",
                                 "publishUnknownLicenses"), False),
        "output": {"generateMigrationReport": True, "generateSearchIndex": True},
    }
