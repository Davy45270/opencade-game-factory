"""Cas L7 complémentaires sur des données synthétiques."""

import os
import shutil
import unittest
from unittest.mock import patch

from PIL import Image

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M
from tests.acceptance import test_l7_correctifs as L7
from tools.extract import regions


class LotL7(L7._Monde):
    def test_usage_public_refuse_les_droits_manquants_d_une_ligne_conservee(self):
        L7._scan(self)
        id_a, _ = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        id_b, _ = C.asset_par_chemin(self.reg, "jeu-a", M.NIVEAU)
        L7._modifier_fiche(self.reg, id_b, license="MIT", licenseEvidence=L7.PREUVE)
        self.world.commiter_registre("Catalogue avec un seul asset publiable")
        jeu = self.world.depot("jeu-b")
        first = self.world.ctl(C.cmd_usage_add(id_a, "jeu-b", "Menu", "sprite", jeu, L7.DEST_A,
                                               C.OPTION_CIBLE_PRIVEE))
        self.assertEqual(first.code, C.OK, str(first))
        lock = jeu / C.LOCK_JEU
        before = lock.read_bytes()

        result = self.world.ctl(C.cmd_usage_add(id_b, "jeu-b", "Menu", "sprite", jeu, L7.DEST_B))

        self.assertEqual(result.code, C.REFUS, str(result))
        self.assertIn(id_a, result.stdout + result.stderr)
        self.assertEqual(lock.read_bytes(), before)
        self.assertFalse((jeu / L7.DEST_B).exists())

    def test_validate_detecte_la_reecriture_directe_de_la_preuve(self):
        L7._scan(self)
        asset_id, _ = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        L7._modifier_fiche(self.reg, asset_id, license="MIT", licenseEvidence=L7.PREUVE)
        result = self.world.ctl(C.cmd_publish([asset_id], "public", self.world.racine / "export"))
        self.assertEqual(result.code, C.OK, str(result))
        base = self.world.commiter_registre("Publication de fixture")
        versions = C.assets(self.reg)[asset_id]["versions"]
        versions[0]["publication"]["license"] = "CC0-1.0"
        L7._modifier_fiche(self.reg, asset_id, versions=versions)

        result = self.world.ctl(C.cmd_validate("--base", base))

        self.assertEqual(result.code, C.ECHEC, str(result))
        self.assertIn(("immutable-version", f"catalog/assets/{asset_id}.json"),
                      {(issue["code"], issue["path"]) for issue in result.json["issues"]})

    def test_magick_absent_empeche_la_mesure(self):
        sheet = M.png(L7._planche_k())
        frame = L7._bruit(32, 32, 67)
        L7._ajouter_jeu(self, "jeu-k", L7._fichiers_jeu_k("jeu-k", sheet, frame, {"magick": "7.1.2"}))
        L7._scan(self)
        binaries = self.world.racine / "bin"
        binaries.mkdir()
        (binaries / "git").symlink_to(shutil.which("git"))
        with patch.dict(os.environ, {"PATH": str(binaries)}):
            L7._scan(self, "--no-fetch")

        asset_id, _ = L7._sprite(self, "sprite-k")
        self.assertEqual(L7._rmse_mesurees(L7._regions(self, asset_id)), [])
        limits = C.lire_json(C.rapport(self.reg, "scan-limits"))["sheets"]
        self.assertIn(("sprite-k", "magick-unavailable"), {(row.get("frame"), row["reason"]) for row in limits})


class Raccords(unittest.TestCase):
    def test_cibles_superposees_couvrant_exactement_la_moitie(self):
        pixels = Image.new("RGBA", (64, 64), (13, 55, 82, 255))
        band = regions.named_box([1, 64, 0, 0])
        targets = [regions.named_box([24, 64, 0, 0]), regions.named_box([24, 64, 8, 0])]
        score = regions.measure(pixels, [64, 64, 0, 0], 0, pixels,
                                raccords=[(band, target) for target in targets])
        self.assertEqual(score, 0)
