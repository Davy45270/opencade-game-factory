"""Vérifications ciblées du lot L3 sur un monde construit par les tests."""

import hashlib
import json
import shutil
import unittest
from datetime import datetime, timedelta, timezone

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M


class LotL3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = M.creer_monde()
        cls.addClassCleanup(cls.world.nettoyer)
        cls.root = cls.world.registre
        result = cls.world.scan()
        if result.code != 0:
            raise AssertionError(str(result))
        cls.asset_id, cls.asset = C.asset_par_chemin(cls.root, "jeu-a", M.FOUET)
        cls.star_id = next(aid for aid, asset in C.assets(cls.root).items() if asset["license"] == "CC-BY-4.0")
        paths = cls.world.git(cls.root, "ls-files", "-m", "-o", "--exclude-standard").splitlines()
        cls.world.git(cls.root, "add", "--", *paths)
        cls.world.git(cls.root, "commit", "-qm", "Import de fixture")

    @classmethod
    def commit_catalogue(cls, message):
        paths = cls.world.git(cls.root, "ls-files", "-m", "-o", "--exclude-standard",
                              "--", "catalog", "published").splitlines()
        if not paths:
            return
        cls.world.git(cls.root, "add", "--", *paths)
        cls.world.git(cls.root, "commit", "-qm", message, "--", *paths)

    def ctl(self, args, code=0):
        result = self.world.ctl([*args, "--json"])
        self.assertEqual(result.code, code, str(result))
        return result.json

    def new_asset(self):
        path = self.world.racine / "manuel.png"
        path.write_bytes(M.png(M.uni(7, 15, (31, 83, 122, 160))))
        return path

    def test_T21_similarity_and_exact_filters(self):
        result = self.ctl(["search", "--similar-to", self.asset_id, "--family", "image", "--used-by", "jeu-a"])
        first = result["results"][0]
        self.assertEqual((first["id"], first["phashDistance"]), (self.asset_id, 0))
        self.assertTrue(first["usages"])
        result = self.ctl(["search", "fouet", "--family", "police"])
        self.assertEqual(result["results"], [])

    def test_T22_refuses_expired_or_incomplete_receipts(self):
        receipt = self.world.racine / "T22.json"
        self.ctl(["search", "fouet", "--receipt", str(receipt), "--limit", "1"])
        original = C.lire_json(receipt)
        self.assertIn(self.asset_id, original["results"])
        command = ["register", str(self.new_asset()), "--name", "Manuel", "--category", "kitchen",
                   "--receipt", str(receipt), "--dry-run"]
        self.ctl(command, code=3)
        original["searchedAt"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        receipt.write_text(json.dumps(original), encoding="utf-8")
        self.ctl([*command, *(arg for aid in original["results"] for arg in ("--reject", f"{aid}:autre style"))],
                 code=3)

    def test_T23_rejects_whole_public_batch_and_exports_private(self):
        target = self.world.racine / "T23"
        args = ["publish", self.star_id, self.asset_id, "--dest", str(target), "--target"]
        self.ctl([*args, "public"], code=3)
        self.assertFalse(target.exists())
        self.ctl([*args, "private"])
        manifest = C.lire_json(target / "manifest.json")
        self.assertEqual({row["id"] for row in manifest["assets"]}, {self.star_id, self.asset_id})
        record = self.root / "catalog" / "assets" / f"{self.star_id}.json"
        original = record.read_bytes()
        try:
            for field, value in (("licenseEvidence", None), ("publicExport", "forbidden")):
                with self.subTest(field=field):
                    asset = json.loads(original)
                    if value is None:
                        del asset[field]
                    else:
                        asset[field] = value
                    record.write_text(json.dumps(asset), encoding="utf-8")
                    refused = self.world.racine / f"T23-{field}"
                    self.ctl(["publish", self.star_id, "--target", "public", "--dest", str(refused)], code=3)
                    self.assertFalse(refused.exists())
        finally:
            record.write_bytes(original)

    def test_T25_same_fingerprints_after_removing_generated_and_database(self):
        before = self.ctl(["index"])
        database = self.root / "build" / "registry.sqlite"
        self.assertTrue(database.is_file())
        digest = C.sha256_fichier(database)
        shutil.rmtree(self.root / "generated")
        database.unlink()
        self.assertEqual(before, self.ctl(["index"]))
        self.assertEqual(digest, C.sha256_fichier(database))

    def test_T26_atlas_rejects_duplicate_frame_names(self):
        output = self.root / "atlases" / "T26"
        self.ctl(["export-atlas", self.asset_id, "--out", str(output)])
        path = output.with_suffix(".json")
        self.ctl(["validate-atlas", str(path)])
        atlas = C.lire_json(path)
        frame = json.dumps(atlas["frames"][self.asset_id])
        png = json.dumps(atlas["meta"])
        path.write_text(f'{{"frames":{{"{self.asset_id}":{frame},"{self.asset_id}":{frame}}},"meta":{png}}}',
                        encoding="utf-8")
        self.ctl(["validate-atlas", str(path)], code=1)

    def test_T27_lock_checks_version_and_public_policy(self):
        game = self.world.depot("jeu-b")
        destination = "public/reutilise.png"
        found = self.ctl(["search", "fouet"])["results"][0]["id"]
        self.assertEqual(found, self.asset_id)
        self.commit_catalogue("Catalogue avant la vérification du lock")
        self.ctl(C.cmd_usage_add(found, "jeu-b", "Menu", "sprite", game, destination, "--private-target"))
        path = game / "assets.lock.json"
        self.ctl(["check-lock", str(path)])
        self.ctl(["check-lock", str(path), "--public"], code=3)
        self.ctl(["materialize", found, "--to", str(game / destination), "--private-target"])
        self.assertEqual(C.sha256_fichier(game / destination), self.asset["sha256"])
        self.addCleanup(path.write_bytes, path.read_bytes())
        lock = C.lire_json(path)
        lock["assets"][0]["assetVersion"] = "inconnue"
        path.write_text(json.dumps(lock), encoding="utf-8")
        self.ctl(["check-lock", str(path)], code=1)

    def test_T28_incremental_sync_counts_only_changed_copies(self):
        main = self.world.git(self.root, "rev-parse", "main")
        branch = "sync/T28"
        args = ["sync", "--branch", branch]
        # Ce commit de fixture ajoute un fichier, sans supprimer les ressources des autres tests.
        M.ajouter_commit(self.world, "jeu-a", {"public/assets/t28.png": self.new_asset().read_bytes()}, (),
                         "2026-03-03T10:00:00Z", "Ajout pour sync")
        game = self.world.depot("jeu-a")
        source = C.empreinte_arbre(game)
        first = self.ctl(args)
        self.assertEqual(first["scannedCopies"], 1)
        second = self.ctl(args)
        self.assertEqual(second["scannedCopies"], 0)
        self.assertEqual(first["commit"], second["commit"])
        self.assertEqual(self.world.git(self.root, "rev-parse", "main"), main)
        self.assertEqual(C.empreinte_arbre(game), source)

    def test_T29_dry_run_mutations_leave_files_unchanged(self):
        path = self.world.racine / "T29.json"
        recipe = self.world.racine / "recette-T29.json"
        recipe.write_text('{"mirror":true}\n', encoding="utf-8")
        self.ctl(["search", "zebre", "--receipt", str(path)])
        game = self.world.depot("jeu-b")
        new = self.new_asset()
        self.commit_catalogue("Catalogue avant les mutations à blanc")
        before = C.empreinte_arbre(self.world.racine)
        cases = [
            ["index"], ["duplicates"], ["search", "fouet", "--receipt", str(path)],
            ["register", str(new), "--name", "Neuf", "--category", "kitchen", "--receipt", str(path)],
            ["derive", self.asset_id, "--recipe", str(recipe)],
            ["publish", self.asset_id, "--dest", str(self.world.racine / "T29-export"), "--target", "private"],
            ["materialize", self.asset_id, "--to", str(game / "T29.png"), "--private-target"],
            C.cmd_usage_add(self.asset_id, "jeu-b", "Test", "sprite", game, "T29.png", "--private-target"),
            ["sync", "--branch", "sync/T29"], ["export-atlas", self.asset_id, "--out", "atlases/T29"],
            ["sbom", "--out", "generated/T29.cdx.json"],
        ]
        for command in cases:
            with self.subTest(command=command[0]):
                self.ctl([*command, "--dry-run"])
                self.assertEqual(C.empreinte_arbre(self.world.racine), before)

    def test_T31_deterministic_cyclonedx(self):
        args = ["sbom", "--out", "generated/sbom.cdx.json"]
        self.ctl(args)
        path = self.root / "generated" / "sbom.cdx.json"
        first = path.read_bytes()
        self.ctl(args)
        self.assertEqual(path.read_bytes(), first)
        sbom = C.lire_json(path)
        self.assertEqual((sbom["bomFormat"], sbom["specVersion"]), ("CycloneDX", "1.5"))
        self.assertEqual(sbom["metadata"]["component"]["name"], "opencade-asset-registry")
        self.assertTrue(any(row["purl"].startswith("pkg:pypi/pillow@") for row in sbom["components"]))

    def test_T32_parent_record_changes_only_variants(self):
        recipe = self.world.racine / "recette-T32.json"
        recipe.write_text('{"mirror":"vertical","resize":[8,11],"tint":"#345678"}\n', encoding="utf-8")
        parent_path = self.root / "catalog" / "assets" / f"{self.star_id}.json"
        parent = C.lire_json(parent_path)
        args = ["derive", self.star_id, "--recipe", str(recipe)]
        child = self.ctl(args)["asset"]
        self.assertEqual(self.ctl(args)["id"], child["id"])
        after = C.lire_json(parent_path)
        self.assertIn(child["id"], after.pop("variants"))
        parent.pop("variants")
        self.assertEqual(parent, after)
        self.assertEqual(child["provenance"]["derivedFrom"], self.star_id)
        identities = C.lire_json(self.root / "catalog" / "ids.json")
        self.assertEqual(identities[f"derived:{self.star_id}:{C.sha256_fichier(recipe)}"], child["id"])
        self.assertEqual(child["license"], "CC-BY-4.0")
        self.assertEqual(child["dimensions"], {"width": 8, "height": 11})
        binary = self.root / child["files"]["registry"]
        self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), child["sha256"])
        self.ctl(["validate", "--base", "main"])
