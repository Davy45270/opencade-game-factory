"""Cas L6 complémentaires sur des dépôts synthétiques."""

import json

from tests.acceptance import _contrat as C
from tests.acceptance import test_l6_correctifs as L6


class LotL6(L6._Monde):
    def test_recettes_manquante_partiellement_invalide_et_sans_raccord(self):
        files = L6._fichiers_jeu_r()
        provenance_path = "assets/provenance.json"
        recipe_path = "assets/source/r.retouches.json"
        provenance = json.loads(files[provenance_path])
        provenance["assets"][1]["source_retouche"] = "assets/source/absente.retouches.json"
        files[provenance_path] = json.dumps(provenance)
        recipes = json.loads(files[recipe_path])
        recipes[0]["raccords"].append([L6.BANDE, "1x1+999+0"])
        del recipes[2]["raccords"]
        files[recipe_path] = json.dumps(recipes)
        L6._ajouter_jeu(self, "jeu-r", files)

        L6._scan(self)

        limits = C.rapport(self.reg, "scan-limits")
        reported = {row["frame"]: (row["reason"], row["recipe"]) for row in C.lire_json(limits)["sheets"]
                    if row["reason"].startswith("declared-retouch-")}
        self.assertEqual(reported, {
            "sprite-raccord-ok": ("declared-retouch-unreadable", recipe_path),
            "sprite-raccord-faux": ("declared-retouch-unreadable", "assets/source/absente.retouches.json"),
            "sprite-hors-raccord": ("declared-retouch-without-raccords", recipe_path),
        })
        for frame in reported:
            with self.subTest(frame=frame):
                asset_id, record = L6._sprite(self, frame)
                self.assertEqual(record["provenance"]["type"], "derived")
                self.assertFalse(record["sourceRegion"]["verified"])
                self.assertEqual(L6._rmse_mesurees(L6._regions(self, asset_id)), [])

    def test_fichier_cite_prioritaire_sur_alias(self):
        files = L6._fichiers_jeu_p()
        files["public/assets/p.png"] = files["assets/export/p.png"]
        L6._ajouter_jeu(self, "jeu-p", files, alias=L6.ALIAS)

        L6._scan(self)

        asset_id, _ = L6._sprite(self, "sprite-p1")
        self.assertLessEqual(min(L6._rmse_mesurees(L6._regions(self, asset_id))), L6.SEUIL)
        self.assertEqual(C.lire_json(C.rapport(self.reg, "path-aliases")), [])

    def test_catalogue_propre_sans_asset_demande(self):
        L6._scan(self)
        self.world.commiter_registre("Catalogue importé")
        game = self.world.depot("jeu-b")
        result = self.world.ctl(C.cmd_usage_add(
            "asset-absent", "jeu-b", "Menu", "sprite", game, L6.DEST_U, C.OPTION_CIBLE_PRIVEE))
        self.assertEqual(result.code, C.REFUS, str(result))
        self.assertIn("commite le catalogue", result.stdout + result.stderr)
        self.assertFalse((game / C.LOCK_JEU).exists())
        self.assertFalse((game / L6.DEST_U).exists())
