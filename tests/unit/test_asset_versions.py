"""Régressions du versionnement au-delà du contrat AV-01."""

import hashlib
import json
import unittest

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M


NEW = M.png(M.uni(16, 12, (33, 121, 213, 255)))
DATE = "2026-03-06T10:00:00+00:00"


class AssetVersions(unittest.TestCase):
    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        self.root = self.world.registre

    def scan(self):
        result = self.world.scan()
        self.assertEqual(result.code, C.OK, str(result))
        return C.asset_par_chemin(self.root, "jeu-a", M.FOUET)

    def replace(self, content=NEW):
        return M.ajouter_commit(self.world, "jeu-a", {M.FOUET: content}, (), DATE, "Nouveau contenu")

    def check(self, args, code=C.OK):
        result = self.world.ctl(args)
        self.assertEqual(result.code, code, str(result))
        return result.json

    def test_first_scan_keeps_older_tag_on_the_same_asset(self):
        old = (self.world.depot("jeu-a") / M.FOUET).read_bytes()
        head = self.replace()
        asset_id, asset = self.scan()
        self.assertEqual(asset["version"], 2)
        self.assertEqual([v["sha256"] for v in asset["versions"]],
                         [hashlib.sha256(content).hexdigest() for content in (old, NEW)])
        self.assertTrue(any(loc.get("releaseOnly") and loc["assetVersion"] == 1
                            for loc in asset["files"]["locations"]))
        self.assertTrue(any("v1.0" in use["releases"] and use["assetVersion"] == 1 for use in asset["usages"]))
        self.assertTrue(any(use["commit"] == head and use["assetVersion"] == 2 for use in asset["usages"]))
        self.assertEqual(self.scan(), (asset_id, asset))
        self.assertEqual(self.check(["inspect", asset_id, "--json"])["asset"]["versions"], asset["versions"])

    def test_late_tag_keeps_the_persisted_current_number(self):
        game = self.world.depot("jeu-a")
        old_commit = self.world.git(game, "rev-parse", "HEAD")
        self.world.git(game, "tag", "-d", "v1.0")
        self.replace()
        asset_id, first = self.scan()
        self.world.git(game, "tag", "v1.0", old_commit)
        migrated_id, asset = self.scan()
        self.assertEqual(migrated_id, asset_id)
        self.assertEqual((asset["version"], asset["sha256"]), (1, first["sha256"]))
        self.assertEqual(asset["versions"][1]["commit"], old_commit)
        self.assertEqual(self.scan(), (asset_id, asset))
        search = self.check(["search", "fouet", "--json"])
        result = next(row for row in search["results"] if row["id"] == asset_id)
        self.assertEqual((result["version"], result["sha256"]), (1, first["sha256"]))

    def test_equal_contents_in_two_sources_keep_independent_histories(self):
        shared = (self.world.depot("jeu-a") / M.FOUET).read_bytes()
        M.ajouter_commit(self.world, "jeu-b", {M.FOUET: shared}, (), DATE, "Copie du contenu")
        asset_id, _ = self.scan()
        other, _ = C.asset_par_chemin(self.root, "jeu-b", M.FOUET)
        self.assertNotEqual(asset_id, other)
        self.replace()
        self.assertEqual(self.scan()[0], asset_id)
        self.assertEqual(C.asset_par_chemin(self.root, "jeu-b", M.FOUET)[1]["version"], 1)

    def test_legacy_migration_validate_base_and_old_lock(self):
        asset_id, asset = self.scan()
        asset_path = self.root / "catalog" / "assets" / f"{asset_id}.json"
        paths = ["catalog/ids.json", asset_path.relative_to(self.root).as_posix()]
        for key in ("version", "versions"):
            asset.pop(key)
        for record in (*asset["files"]["locations"], *asset["usages"]):
            record.pop("assetVersion", None)
        asset.update(status="published", license="CC0-1.0", licenseEvidence=["LICENSE de fixture"])
        asset_path.write_text(json.dumps(asset), encoding="utf-8")
        self.world.git(self.root, "add", "--", *paths)
        self.world.git(self.root, "commit", "-qm", "Catalogue de base sans versions")
        base = self.world.git(self.root, "rev-parse", "HEAD")

        self.replace()
        _, updated = self.scan()
        self.assertEqual((updated["version"], updated["status"]), (2, "needs-review"))
        self.assertEqual(updated["versions"][0]["publication"]["license"], "CC0-1.0")
        migrated = asset_path.read_bytes()
        self.scan()
        self.assertEqual(asset_path.read_bytes(), migrated)
        self.check(["validate", "--base", base, "--json"])

        lock_path = self.root / "assets.lock.json"
        row = {"assetId": asset_id, "assetVersion": "1", "sha256": asset["sha256"],
               "scene": "Cuisine", "role": "sprite", "path": M.FOUET}
        lock = {"schemaVersion": "1.0", "registryCommit": base, "game": "jeu-a", "assets": [row]}
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        result = self.check(["check-lock", str(lock_path), "--json"])
        self.assertEqual(result["warnings"][0]["currentVersion"], "2")
        row["sha256"] = "f" * 64
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        self.check(["check-lock", str(lock_path), "--json"], C.ECHEC)

        changed = json.loads(migrated)
        changed["versions"][0]["sha256"] = "f" * 64
        asset_path.write_text(json.dumps(changed), encoding="utf-8")
        result = self.check(["validate", "--base", base, "--json"], C.ECHEC)
        self.assertIn("immutable-version", {issue["code"] for issue in result["issues"]})
