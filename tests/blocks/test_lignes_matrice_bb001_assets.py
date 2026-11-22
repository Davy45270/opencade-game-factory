"""Oracle de la ligne E209 de la matrice game-factory (HL-525), BB-001 : réutiliser les catalogues Asset (et
EXT-001, niveaux) sans dupliquer les métadonnées — lien PAR IDENTIFIANT vers le module assets. Écrit AVANT le code.

- `bbctl link-assets` relie une brique aux assets et niveaux du catalogue de l'usine situés sous son module (même
  dépôt, chemin du fichier sous `origin.path`) : la fiche ne reçoit QUE des identifiants (`assetIds`) ;
- `bbctl assets <BB>` relit les métadonnées dans le catalogue des assets au moment de la lecture (jamais copiées) ;
- `validate` refuse un identifiant qui ne résout pas, et le schéma refuse des métadonnées recopiées dans la fiche ;
- `index` : arête uses-asset dans le graphe.
"""
from __future__ import annotations

import json
import unittest

from ._outil import Usine, fiche


def asset(id_, repo, path, category="sprite"):
    return {"id": id_, "category": category, "format": "png", "license": "MIT",
            "files": {"locations": [{"repo": repo, "path": path, "status": "active", "provider": "local"}],
                      "registry": None}}


def niveau(id_, repo, path):
    return {"id": id_, "kind": "level", "format": "json",
            "origin": {"sourceRepo": f"https://forgejo.example/david/{repo}.git", "sourcePath": path, "license": "MIT"}}


class E209LienParIdentifiantVersLesAssets(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()
        cat = self.u.usine / "catalog"
        for d, rec in (("assets", asset("asset-sprite-capsule-0001", "jeu", "packages/assets/sprites/capsule.png")),
                       ("assets", asset("asset-sprite-autre-0001", "jeu", "packages/assetsbis/x.png")),     # préfixe trompeur
                       ("assets", asset("asset-sprite-ailleurs-0001", "autre", "packages/assets/y.png")),   # autre dépôt
                       ("levels", niveau("level-jeu-001-salon", "jeu", "packages/assets/levels/001.json"))):
            (cat / d).mkdir(parents=True, exist_ok=True)
            (cat / d / f"{rec['id']}.json").write_text(json.dumps(rec))
        self.bb = "BB-JEU-ASSETS-001"
        self.u.poser(fiche(self.bb, name="assets", kind="game-local-module", usedBy=["jeu"],
                           origin={"repositoryUrl": None, "repo": "jeu", "path": "packages/assets",
                                   "licenseSpdx": "MIT", "commitSha": None}))

    def tearDown(self) -> None:
        self.u.nettoyer()

    def fiche_bb(self) -> dict:
        return json.loads((self.u.usine / "blocks" / "catalog" / f"{self.bb}.json").read_text())

    def test_lien_par_identifiant_seulement(self) -> None:
        r = self.u.bbctl("link-assets", "--json")
        self.assertEqual(r.rc, 0, r)
        f = self.fiche_bb()
        self.assertEqual(f["assetIds"], ["asset-sprite-capsule-0001", "level-jeu-001-salon"])
        self.assertNotIn("MIT", json.dumps(f["assetIds"]))
        self.assertNotIn("sprite", json.dumps({k: v for k, v in f.items() if k != "assetIds"}))   # rien de recopié
        r = self.u.bbctl("assets", self.bb, "--json")                         # métadonnées relues à la source
        self.assertEqual(r.rc, 0, r)
        self.assertEqual([(a["id"], a["catalog"], a["path"]) for a in r.json["assets"]],
                         [("asset-sprite-capsule-0001", "assets", "packages/assets/sprites/capsule.png"),
                          ("level-jeu-001-salon", "levels", "packages/assets/levels/001.json")])
        self.assertEqual(self.u.bbctl("validate", "--all", "--json").rc, 0)
        out = self.u.tmp / "gen"
        self.assertEqual(self.u.bbctl("index", "--out", str(out), "--json").rc, 0)
        self.assertIn({"from": self.bb, "to": "asset-sprite-capsule-0001", "type": "uses-asset"},
                      json.loads((out / "dependency-graph.json").read_text())["edges"])

    def test_identifiant_qui_ne_resout_pas_refuse(self) -> None:
        f = self.fiche_bb()
        f["assetIds"] = ["asset-sprite-fantome-0001"]
        self.u.poser(f)
        r = self.u.bbctl("validate", "--all", "--json")
        self.assertEqual(r.rc, 1, r)
        self.assertIn("asset-sprite-fantome-0001", r.stdout)

    def test_metadonnees_recopiees_refusees_par_le_schema(self) -> None:
        f = self.fiche_bb()
        f["assetIds"] = [{"id": "asset-sprite-capsule-0001", "license": "MIT"}]
        self.u.poser(f)
        r = self.u.bbctl("validate", "--all", "--json")
        self.assertEqual(r.rc, 1, r)
        self.assertIn("schéma invalide (assetIds", r.stdout)


if __name__ == "__main__":
    unittest.main()
