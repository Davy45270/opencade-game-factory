"""Régressions de découverte sur des dépôts Git synthétiques."""

import hashlib
import json
import re
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M
from tools.extract.aseprite import executable


class DiscoveryL2b(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = M.creer_monde()
        cls.addClassCleanup(cls.world.nettoyer)
        M.ajouter_commit(cls.world, "jeu-a", {
            "assets/planches/sheet-candidates.png": M.png(M.planche()[:, ::-1]),
            "src/plain.tsx": "export default () => <div/>;",
            "src/draw.jsx": "export default () => <svg/>;",
            "src/refs.ts": "const files = import.meta.glob('../public/assets/crate/*.png');\n"
                           "this.load.image('dynamic', folder + 'assets/fouet.png');\n"
                           "this.load.json('dialogue', '/assets/dialogue.json');\n"
                           "import './style.css';\n"
                           "const icon = new URL('./icon.png', import.meta.url);\n",
            "src/style.css": "/* url('/assets/niveau-1.png') */\n.a { background: url(../public/assets/crate/a.png); }",
            "src/icon.png": M.png(M.uni(6, 6, (90, 40, 70, 255))),
            "public/manifest.webmanifest": '{"icons":[{"src":"/assets/characters/lumi-front-clean.png"}]}',
            "public/assets/dialogue.json": '{"dialogue":"bonjour"}',
            "public/assets/crate/a.png": M.png(M.uni(3, 4, (20, 40, 80, 255))),
            "public/assets/crate/b.png": M.png(M.uni(3, 4, (30, 40, 80, 255))),
            "public/assets/characters/lumi-front-clean.png": M.png(M.uni(3, 4, (70, 40, 80, 255))),
        }, (), "2026-02-28T12:00:00+00:00", "Fixture L2b")
        result = cls.world.scan()
        if result.code:
            raise AssertionError(str(result))
        cls.assets = C.assets(cls.world.registre)
        cls.sheets = C.planches(cls.world.registre)

    def asset(self, path):
        return C.asset_par_chemin(self.world.registre, "jeu-a", path)[1]

    def frame(self, name):
        return next(a for a in self.assets.values() if a["name"] == name and a["sourceRegion"])

    def test_T12_references(self):
        usage = self.asset(M.FOUET)["usages"][0]
        self.assertEqual((usage["scene"], usage["codeRef"]["line"], usage["importName"]),
                         ("Cuisine", M.ligne_de(M.texte_scene(), "'fouet'"), "fouet"))
        self.assertEqual(usage["provider"], "local")
        report = C.lire_json(self.world.registre / C.RAPPORT_REFS_DYNAMIQUES)
        self.assertTrue(any("${" in row["excerpt"] for row in report))
        self.assertTrue(any("folder +" in row["excerpt"] for row in report))
        for name in "ab":
            self.assertTrue(any(u["codeRef"]["path"] == "src/refs.ts"
                                for u in self.asset(f"public/assets/crate/{name}.png")["usages"]))

        for path, method in (("src/style.css", "import"), ("src/icon.png", "new URL"),
                             ("public/assets/dialogue.json", "phaser.load.json")):
            self.assertTrue(any(method in use["evidence"][0] for use in self.asset(path)["usages"]))
        self.assertFalse(self.asset(M.NIVEAU)["usages"])
        self.assertTrue(any(u["role"] == "icon" and u["codeRef"]["path"] == "public/manifest.webmanifest"
                            for u in self.asset("public/assets/characters/lumi-front-clean.png")["usages"]))

    def test_T16_atlases(self):
        atlas_ids = {sheet["id"] for sheet in self.sheets.values()}
        frames = [a for a in self.assets.values() if a["files"].get("atlasFrames")]
        self.assertGreaterEqual(len(frames), 5)
        atlas_digests = {hashlib.sha256(raw).hexdigest() for raw, _ in (M.atlas_elements(), M.atlas_pions())}
        self.assertTrue(atlas_digests <= {sheet["sha256"] for sheet in self.sheets.values()})
        for asset in frames:
            self.assertEqual(asset["files"]["sha256Method"], "canonical-crop-png")
            if asset["sourceRegion"] and asset["sourceRegion"]["verified"]:
                self.assertIn(asset["sourceSheetId"], atlas_ids)
        self.assertEqual(len([a for a in frames if a["name"] == "sprite-etoile"]), 1)

    def test_T17_candidats(self):
        sheet = next(s for s in self.sheets.values()
                     if any(l["path"] == "assets/planches/sheet-candidates.png" for l in s["files"]["locations"]))
        self.assertEqual(sheet["regions"], [])
        before = C.empreinte_arbre(self.world.registre / "catalog")
        result = self.world.ctl(["extract", sheet["id"], "--candidates", "--json"])
        self.assertEqual(result.code, 0, str(result))
        self.assertTrue(result.json["candidates"])
        self.assertTrue(all(r["status"] == "candidate" for r in result.json["candidates"]))
        self.assertEqual(before, C.empreinte_arbre(self.world.registre / "catalog"))

    def test_T18_decoupe(self):
        star, cloud = self.frame("sprite-etoile"), self.frame("sprite-nuage")
        self.assertEqual(star["license"], "CC-BY-4.0")
        self.assertEqual(star["licenseEvidence"]["method"], "provenance-file")
        self.assertEqual((cloud["license"], cloud["status"]), ("unknown", "needs-review"))
        self.assertFalse(cloud["sourceRegion"]["verified"])
        self.assertLessEqual(star["sourceRegion"]["evidence"]["value"], C.SEUIL_RMSE)
        self.assertGreater(cloud["sourceRegion"]["evidence"]["value"], C.SEUIL_RMSE)
        self.assertEqual(self.asset(M.FOUET)["license"], "unknown")

    def test_T19_code_et_image(self):
        self.assertEqual(self.asset(M.FOUET)["license"], "unknown")
        code = self.asset("src/draw.jsx")
        self.assertEqual(code["license"], "MIT")
        commit = self.world.git(self.world.depot("jeu-a"), "rev-parse", "HEAD")
        self.assertEqual(code["licenseEvidence"]["ref"], f"LICENSE@{commit}")

    def test_T20_enrichissement(self):
        asset = self.asset("public/assets/characters/lumi-front-clean.png")
        for key, value in {"category": "characters", "orientation": "front", "state": "clean"}.items():
            self.assertEqual(asset[key], value)
            trace = asset["inference"][key]
            self.assertLess(trace["confidence"], 1)
            self.assertTrue(trace["method"] and trace["evidence"])
        self.assertEqual(self.asset(M.FOUET)["orientation"], "unknown")

    def test_couverture_modules(self):
        report = C.lire_json(C.rapport(self.world.registre, "coverage"))
        for row in report["formats"]:
            self.assertEqual(row["found"], sum(row[key] for key in
                             ("imported", "exception", "excluded", "unsupported", "examined")))
        tsx = next(row for row in report["formats"] if row["format"] == "tsx")
        self.assertGreater(tsx["examined"], 0)
        self.assertEqual(tsx["exception"], 0)

    def test_T24_suppression(self):
        world = M.creer_monde()
        self.addCleanup(world.nettoyer)
        self.assertEqual(world.scan().code, 0)
        asset_id, _ = C.asset_par_chemin(world.registre, "jeu-a", M.FOUET)
        commit = M.ajouter_commit(world, "jeu-a", {}, (M.FOUET,), "2026-03-01T10:00:00+00:00", "Retrait")
        self.assertEqual(world.scan().code, 0)
        usages = C.assets(world.registre)[asset_id]["usages"]
        self.assertTrue(usages)
        for usage in usages:
            self.assertEqual((usage["status"], usage["removedAtCommit"]), ("removed", commit))
            self.assertIn("v1.0", usage["releases"])
        self.assertIn(asset_id, (world.registre / C.RAPPORT_SUPPRESSIONS).read_text())

    def test_fournisseurs_divergents(self):
        world = M.creer_monde()
        self.addCleanup(world.nettoyer)
        old_commit = world.commits["jeu-a"]
        mirror = world.cache / "github" / "jeu-a.git"
        mirror.parent.mkdir(parents=True)
        world.git(world.depot("jeu-a"), "clone", "--mirror", "--no-local", ".", str(mirror))
        world.git(mirror, "remote", "set-url", "origin", "https://github.com/fixture/jeu-a")
        document = C.lire_json(world.registre / C.SOURCES)
        source = next(e for e in document["sources"] if e["name"] == "jeu-a")
        source["copies"].append({"provider": "github", "url": "https://github.com/fixture/jeu-a",
                                 "visibility": "public", "defaultBranch": "main"})
        (world.registre / C.SOURCES).write_text(json.dumps(document))
        local_commit = M.ajouter_commit(world, "jeu-a", {M.SCENE: "\n" + M.texte_scene()}, (),
                                       "2026-03-01T10:00:00+00:00", "Copie locale divergente")
        local_path = world.cache / "local" / "jeu-a.git"
        local_path.parent.mkdir(parents=True)
        world.git(world.depot("jeu-a"), "clone", "--mirror", "--no-local", world.depot("jeu-a").as_uri(),
                  str(local_path))
        result = world.scan("--no-fetch", "--only", "jeu-a")
        self.assertEqual(result.code, 0, str(result))
        asset_id, asset = C.asset_par_chemin(world.registre, "jeu-a", M.FOUET)
        self.assertTrue(C.contient_valeur(C.lire_json(world.registre / "generated/usage-index.json"), asset_id))
        # Copies divergentes (HL-538, 19/11) : la copie la plus avancée (locale) est importée, GitHub est signalée.
        self.assertEqual({(u["provider"], u["commit"]) for u in asset["usages"]}, {("local", local_commit), ("local", old_commit)})  # old_commit : tag v1.0
        self.assertEqual(result.json["divergentSources"][0]["ignored"],
                         [{"provider": "github", "commit": old_commit}])

    def test_catalogue_et_planche_externe(self):
        world = M.creer_monde()
        self.addCleanup(world.nettoyer)
        shared = world.depots / "jeux-assets"
        sheet_raw = M.png(M.planche())
        image_raw = M.png(M.uni(4, 5, (130, 40, 25, 255)))
        unknown_raw = M.png(M.uni(4, 5, (60, 40, 25, 255)))

        def entry(raw, rights):
            return {"desc": "Description du catalogue", "tags": ["univers"], "statut": "utilisé",
                    "auteur": "outil IA (ChatGPT) sur commande de David", "jeux": ["Le jeu"],
                    "droits": rights, "fichiers": [{"sha256": hashlib.sha256(raw).hexdigest()[:16]}]}

        rights = "publié dans un dépôt public sous MIT (accord de David pour cet usage)"
        document = {"entrees": [entry(image_raw, rights), entry(unknown_raw, rights + " à confirmer")]}
        M._depot(world, "jeux-assets", {"planches/Planche_Test.png": sheet_raw,
                                       "catalogue.json": json.dumps(document),
                                       "image.png": image_raw, "sans-preuve.png": unknown_raw},
                 "2026-02-02T00:00:00+00:00")
        M.ajouter_commit(world, "jeu-a", {}, (M.PLANCHE,), "2026-03-02T00:00:00+00:00", "Planche déplacée")
        sources = C.lire_json(world.registre / C.SOURCES)
        sources["sources"].append(C.source_locale("jeux-assets", shared, "shared-library", []))
        (world.registre / C.SOURCES).write_text(json.dumps(sources))
        result = world.scan()
        self.assertEqual(result.code, 0, str(result))
        _, image = C.asset_par_chemin(world.registre, "jeux-assets", "image.png")
        _, unknown = C.asset_par_chemin(world.registre, "jeux-assets", "sans-preuve.png")
        self.assertEqual(image["license"], "MIT")
        self.assertEqual(image["description"], "Description du catalogue")
        self.assertEqual(image["historicalGames"], ["Le jeu"])
        self.assertEqual(image["inference"]["tags"]["confidence"], 0.9)
        self.assertEqual(image["provenance"]["model"], "ChatGPT")
        self.assertEqual(unknown["license"], "unknown")
        sheet = next(s for s in C.planches(world.registre).values()
                     if s["sha256"] == hashlib.sha256(sheet_raw).hexdigest())
        self.assertTrue(any(loc["repo"] == "jeux-assets" for loc in sheet["files"]["locations"]))
        self.assertEqual(sheet["license"], "unknown")
        asset = next(a for a in C.assets(world.registre).values() if a["name"] == "sprite-etoile")
        self.assertEqual((asset["sourceSheetId"], asset["license"]), (sheet["id"], "CC-BY-4.0"))

    def test_import_sheet_et_extraction(self):
        world = M.creer_monde()
        self.addCleanup(world.nettoyer)
        source = world.racine / "image.png"
        source.write_bytes(M.png(M.planche()))
        table = world.racine / "regions.json"
        table.write_text(json.dumps({"elements": [
            {"id": "etoile", "boite": M.BOITE_ETOILE, "marge": 4, "taille": "40x24"},
        ]}))
        registry_before = C.empreinte_arbre(world.registre / "catalog")
        dry = world.ctl(["import-sheet", str(source), "--dry-run", "--json"])
        self.assertEqual(dry.code, 0, str(dry))
        self.assertEqual(registry_before, C.empreinte_arbre(world.registre / "catalog"))
        sheet = world.ctl(["import-sheet", str(source), "--json"])
        self.assertEqual(sheet.code, 0, str(sheet))
        self.assertEqual(sheet.json, dry.json)
        command = ["extract", sheet.json["sheetId"], "--regions", str(table), "--out", "sprites/ui", "--json"]
        extraction = world.ctl(command)
        self.assertEqual(extraction.code, 0, str(extraction))
        item = extraction.json["assets"][0]
        output = world.registre / item["path"]
        asset = C.assets(world.registre)[item["assetId"]]
        self.assertEqual(asset["sha256"], C.sha256_fichier(output))
        self.assertEqual((asset["license"], asset["sourceRegion"]["verified"]), ("unknown", True))
        self.assertEqual(world.ctl(command).json, extraction.json)
        self.assertEqual(world.ctl(["validate", "--json"]).code, 0)

    @unittest.skipUnless(executable(), "Aseprite et LibreSprite absents")
    def test_aseprite_batch(self):
        from tools.extract.aseprite import export
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            png, ase = root / "sprite.png", root / "sprite.aseprite"
            png.write_bytes(M.png(M.motif_etoile()))
            subprocess.run([executable(), "--batch", str(png), "--save-as", str(ase)],
                           env={**os.environ, "SDL_VIDEODRIVER": "dummy"}, check=True, capture_output=True)
            image, metadata = root / "sheet.png", root / "sheet.json"
            export(ase, image, metadata)
            self.assertTrue(image.is_file())
            self.assertIsInstance(C.lire_json(metadata)["frames"], dict)

    @unittest.skipUnless(shutil.which("magick"), "ImageMagick absent")
    def test_verdict_verifier_decoupe(self):
        script = Path("/home/david/Projets/homelab-diag/arcade-lab/verifier-decoupe.py")
        if not script.is_file():
            self.skipTest("Vérificateur de référence absent")
        from tools.extract.regions import measure
        from PIL import Image
        import io
        files = M.fichiers_jeu_a()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            atlas, meta = M.atlas_elements()
            paths = [root / name for name in ("source.png", "table.json", "atlas.png", "atlas.json")]
            for path, data in zip(paths, (files[M.PLANCHE], files[M.DECOUPE].encode(), atlas,
                                          json.dumps(meta).encode())):
                path.write_bytes(data)
            result = subprocess.run(["python3", str(script), *map(str, paths)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            table = json.loads(paths[1].read_text())
            for element in table["elements"]:
                frame = meta["frames"]["sprite-" + element["id"]]["frame"]
                x, y, w, h = (frame[key] for key in "xywh")
                with Image.open(io.BytesIO(atlas)) as image, Image.open(paths[0]) as source:
                    rmse = measure(source, element["boite"], table["marge"],
                                   image.crop((x, y, x+w, y+h)), element["ancre"])
                line = next(line for line in result.stdout.splitlines() if line.startswith(element["id"] + ":"))
                reference = float(re.search(r"RMSE ([\d.]+)", line)[1])
                self.assertEqual(rmse <= 0.02, reference <= 0.02)
