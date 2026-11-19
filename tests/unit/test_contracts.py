import json
import subprocess
import sys
from unittest import TestCase

from .test_oracles import ASSET, ASSET_ID, HASH, IDS, KEY, ROOT, SHEET_ID, CatalogueFixture


def usage():
    return {
        "repo": "arcade/cuisine", "game": "cuisine", "scene": "entrée",
        "commit": "b" * 40, "codeRef": {"path": "src/scene.ts", "line": 42},
        "role": "décor", "importName": "fouet", "evidence": ["import statique"],
        "status": "removed", "removedAtCommit": "c" * 40, "releases": ["v1.0"],
    }


class Contracts(CatalogueFixture, TestCase):
    def test_familles_et_licences(self):
        from tools.core.schemas import schemas

        validate = schemas().validator("asset").is_valid
        coordinates = {"x": 0, "y": 0, "w": 16, "h": 16}
        audio = {"durationSec": 0.5, "channels": 2, "sampleRate": 48000}
        families = {
            "image": {"image": {}},
            "sprite": {"sprite": {"frameName": "still"}},
            "animation": {"animation": {"frameCount": 4, "fps": 12}},
            "atlas": {"frames": [{"name": "still", **coordinates}]},
            "tileset": {"tileset": {"tileWidth": 16, "tileHeight": 16, "tileCount": 4}},
            "tilemap": {"tilemap": {"tileWidth": 16, "tileHeight": 16, "layerCount": 0}},
            "svg": {"svg": {"viewBox": "0 0 16 16"}},
            "font": {"font": {"family": "Open Font", "style": "Regular"}},
            "audio": {"audio": audio},
            "music": {"audio": audio},
            "shader": {"shader": {"language": "GLSL", "stage": "fragment"}},
            "code-generated": {"code": {"repo": "arcade/cuisine", "path": "draw.ts", "symbol": "draw"}},
        }
        for name, metadata in families.items():
            with self.subTest(family=name):
                asset = {**ASSET, "family": {"type": name, **metadata}}
                self.assertTrue(validate(asset))
                self.assertFalse(validate({**asset, "family": {"type": name}}))
        for name in ("CC-BY-4.0", "MIT", "OFL-1.1", "Apache-2.0"):
            with self.subTest(license=name):
                asset = {**ASSET, "license": name}
                self.assertFalse(validate(asset))
                self.assertTrue(validate({**asset, "licenseEvidence": ["fichier LICENSE"]}))
        self.assertFalse(validate({**ASSET, "license": "Fictitious-License-1.0",
                                   "licenseEvidence": ["fichier LICENSE"]}))
        self.assertFalse(validate({**ASSET, "sha256": "z" * 64}))
        self.assertFalse(validate({**ASSET, "createdAt": "2026-02-31T08:00:00Z"}))

    def test_schemas_source_usage_et_lock(self):
        from tools.core.schemas import schemas

        source = {
            "provider": "forgejo", "repo": "arcade/cuisine", "role": "game",
            "games": ["cuisine"], "url": "https://forge.invalid/arcade/cuisine",
        }
        for name, value, field, invalid in (
            ("source", source, "provider", "local"),
            ("source", source, "url", "https://secret@forge.invalid/arcade/cuisine"),
            ("source", source, "url", "https://forge.invalid:bogus/arcade/cuisine"),
            ("usage", usage(), "codeRef", {"path": "../scene.ts", "line": 42}),
            ("lock", {"schemaVersion": "1.0", "game": "cuisine", "registryCommit": "a" * 40,
                      "assets": [{"assetId": ASSET_ID, "assetVersion": "1.0", "sha256": HASH,
                                  "scene": "entrée", "role": "décor", "path": "sprites/fouet.png"}]},
             "registryCommit", "main"),
        ):
            with self.subTest(schema=name, field=field):
                schema = schemas().validator(name)
                self.assertTrue(schema.is_valid(value))
                self.assertFalse(schema.is_valid({**value, field: invalid}))

    def test_inspect_asset_et_planche_preserve_usages(self):
        self.asset["usages"] = [usage()]
        self.asset["sourceSheetId"] = SHEET_ID
        self.write_asset()
        sheet = {
            field: self.asset[field] for field in (
                "schemaVersion", "name", "dimensions", "files", "provenance", "license"
            )
        }
        sheet.update(id=SHEET_ID, sha256="b" * 64, regions=[])
        self.write(f"sheets/{SHEET_ID}.json", sheet)
        self.assertEqual(self.cli("inspect", ASSET_ID),
                         (0, {"ok": True, "asset": self.asset, "usages": [usage()]}))
        self.assertEqual(self.cli("inspect", SHEET_ID),
                         (0, {"ok": True, "sheet": sheet, "usages": [{"assetId": ASSET_ID, **usage()}]}))
        self.assertEqual(self.cli("inspect", "asset-kitchen-fouet-0099")[0], 1)
        self.assertEqual(self.cli("inspect", "../ids")[0], 2)

    def test_base_git_fiches_et_registre_restent_immuables(self):
        self.commit_base()
        filename = f"catalog/assets/{ASSET_ID}.json"
        self.git("add", filename)
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "Fiche historique")
        self.assertEqual(self.cli("validate", "--base", "HEAD")[0], 0)
        self.write("ids.json", {})
        code, payload = self.cli("validate", "--base", "HEAD")
        self.assertEqual(code, 1)
        self.assertIn("immutable-id", {issue["code"] for issue in payload["issues"]})
        self.write("ids.json", IDS)
        (self.root / filename).unlink()
        code, payload = self.cli("validate", "--base", "HEAD")
        self.assertEqual(code, 1)
        self.assertIn("record-removed", {issue["code"] for issue in payload["issues"]})
        self.assertEqual(self.cli("validate", "--base", "absent")[0], 2)

    def test_ecriture_canonique_et_artefacts_invalides(self):
        from tools.core.catalog import InvalidJSON, parse_json, write_json

        path = self.root / "écriture.json"
        for value in ({"z": 1, "a": "été"}, {"a": "été", "z": 1}):
            write_json(path, value)
            self.assertEqual(path.read_bytes(), '{\n  "a": "été",\n  "z": 1\n}\n'.encode())
        for payload in (b'{"id": 1, "id": 2}', b'{"x": NaN}', b'{"x": 1e999}', b'"\\ud800"'):
            with self.subTest(content=payload), self.assertRaises(InvalidJSON):
                parse_json(payload)
        (self.root / "catalog/ids.json").write_text(
            json.dumps(IDS)[:-1] + f', "{KEY}": "{ASSET_ID}"}}', encoding="utf-8"
        )
        self.assertEqual(self.cli("validate")[0], 1)
        (self.root / "catalog/ids.json").unlink()
        self.assertEqual(self.cli("validate")[0], 4)
        (self.root / "catalog/ids.json").symlink_to(path)
        self.assertEqual(self.cli("validate")[0], 3)

    def test_points_entree_et_journal(self):
        log = self.root / "commandes.jsonl"
        commands = ([str(ROOT / "assetctl")], [sys.executable, "-m", "tools.cli"])
        for command in commands:
            result = subprocess.run([*command, "validate", "--json"], cwd=ROOT,
                                    capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(result.stdout)["ok"])
            self.assertEqual(json.loads(result.stderr)["event"], "command-finished")
            result = subprocess.run([*command, "--log", str(log), "validate", "--json"],
                                    cwd=ROOT, capture_output=True, text=True, check=True)
            self.assertEqual(result.stderr, "")
        self.assertEqual([json.loads(line)["code"] for line in log.read_text().splitlines()], [0, 0])
