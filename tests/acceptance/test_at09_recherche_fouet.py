"""AT-09 (matrice E119) : « la recherche d'un fouet propre en vue trois quarts retourne les candidats compatibles et leur historique d'usage. »"""
from __future__ import annotations

import json

from . import _contrat as C
from ._base import MondeScanne

INFERABLES = ("description", "orientation", "facing", "state", "category", "subcategory", "tags",
              "originUniverse", "visualStyle", "pivot")
COMMIT_1 = "1" * 40
COMMIT_2 = "2" * 40


def asset_fixture(asset_id: str, nom: str, description: str, tags: list[str], orientation: str, etat: str,
                  sous_categorie: str, sha: str, usages: list[dict]) -> dict:
    preuve = {"method": "proven", "confidence": 1, "evidence": "fixture d'acceptation AT-09"}
    return {
        "schemaVersion": "1.0", "id": asset_id, "name": nom, "description": description,
        "category": "kitchen", "subcategory": sous_categorie, "tags": tags,
        "originUniverse": "cozy-room-sort", "visualStyle": "cartoon-vector",
        "sourceSheetId": None, "sourceRegion": None, "orientation": orientation, "facing": "right",
        "state": etat, "dimensions": {"width": 64, "height": 96}, "format": "png", "alpha": True,
        "pivot": {"x": 0.5, "y": 1}, "family": "sprite",
        "files": {"locations": [{"repo": "cozy-room-sort", "commit": COMMIT_1,
                                 "path": f"content/assets/{asset_id}.png"}], "registry": None},
        "sha256": sha,
        "provenance": {"type": "repo-file", "author": "unknown", "evidence": ["fixture d'acceptation AT-09"]},
        "license": "unknown", "status": "active", "usages": usages, "variants": [],
        "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z",
        "inference": {champ: dict(preuve) for champ in INFERABLES},
        "creation": {"importJob": "fixture-at09"},
    }


def usage(jeu: str, scene: str, commit: str, ligne: int) -> dict:
    return {"repo": jeu, "game": jeu, "scene": scene, "commit": commit,
            "codeRef": {"path": f"src/scenes/{scene}.ts", "line": ligne}, "role": "sprite",
            "importName": "fouet", "evidence": "fixture d'acceptation AT-09", "status": "active",
            "releases": ["v1.0"]}


FOUET_PROPRE = "asset-kitchen-fouet-propre-0001"
FOUET_SALE = "asset-kitchen-fouet-sale-0001"
FOUET_FACE = "asset-kitchen-fouet-face-0001"
CUILLERE = "asset-kitchen-cuillere-0001"


class AT09RechercheFouet(MondeScanne):
    """AT-09 / E119 — « AT-09 : la recherche d'un fouet propre en vue trois quarts retourne les candidats
    compatibles et leur historique d'usage. »

    Catalogue de fixture (écrit directement dans `catalog/`, sans scan) : un fouet propre trois quarts
    utilisé deux fois (deux jeux), et des distracteurs : un fouet SALE trois quarts, un fouet propre DE
    FACE, une cuillère propre trois quarts. `search "fouet propre" --orientation three-quarter --state
    clean` ne rend que le fouet compatible, avec ses deux usages ; la même requête en anglais aussi."""

    SCANNER = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        reg = cls.monde.registre
        lignes = [
            asset_fixture(FOUET_PROPRE, "Fouet de pâtisserie", "Fouet métallique à manche rouge, propre, vue trois quarts",
                          ["whisk", "patisserie", "clean"], "three-quarter", "clean", "utensils", "a" * 64,
                          [usage("cozy-room-sort", "Cuisine", COMMIT_1, 12), usage("capsule-panic", "Atelier", COMMIT_2, 34)]),
            asset_fixture(FOUET_SALE, "Fouet de pâtisserie sale", "Fouet métallique couvert de pâte, sale, vue trois quarts",
                          ["whisk", "patisserie", "dirty"], "three-quarter", "dirty", "utensils", "b" * 64, []),
            asset_fixture(FOUET_FACE, "Fouet de pâtisserie de face", "Fouet métallique, propre, vu de face",
                          ["whisk", "patisserie", "clean"], "front", "clean", "utensils", "c" * 64, []),
            asset_fixture(CUILLERE, "Cuillère en bois", "Cuillère en bois, propre, vue trois quarts",
                          ["spoon", "clean"], "three-quarter", "clean", "utensils", "d" * 64, []),
        ]
        ids = {}
        for a in lignes:
            (reg / C.DOSSIER_ASSETS).mkdir(parents=True, exist_ok=True)
            (reg / C.DOSSIER_ASSETS / f"{a['id']}.json").write_text(
                json.dumps(a, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            ids[f"file:sha256:{a['sha256']}"] = a["id"]
        (reg / C.FICHIER_IDS).write_text(json.dumps(ids, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        cls.monde.commiter_registre("Catalogue de fixture AT-09")

    def _ids(self, r: C.Resultat) -> list[str]:
        self.exiger_code(r, C.OK)
        return [x.get("id") for x in C.resultats_recherche(r.json)]

    def test_seul_le_fouet_compatible_en_francais(self):
        r = self.ctl(C.cmd_search("fouet propre", "--orientation", "three-quarter", "--state", "clean"))
        self.assertEqual(self._ids(r), [FOUET_PROPRE])

    def test_meme_requete_en_anglais(self):
        r = self.ctl(C.cmd_search("clean whisk", "--orientation", "three-quarter", "--state", "clean"))
        self.assertEqual(self._ids(r), [FOUET_PROPRE])

    def test_synonymes_trois_quarts_dans_le_texte(self):
        r = self.ctl(C.cmd_search("fouet propre trois quarts"))
        ids = self._ids(r)
        self.assertTrue(ids, "aucun résultat")
        self.assertEqual(ids[0], FOUET_PROPRE, f"le fouet compatible doit venir en tête ; vu {ids}")

    def test_filtres_exacts_laissent_tous_les_compatibles(self):
        r = self.ctl(C.cmd_search("fouet", "--orientation", "three-quarter"))
        self.assertEqual(sorted(self._ids(r)), sorted([FOUET_PROPRE, FOUET_SALE]))

    def test_historique_d_usage_dans_le_resultat(self):
        r = self.ctl(C.cmd_search("fouet propre", "--orientation", "three-quarter", "--state", "clean"))
        self.assertEqual(self._ids(r), [FOUET_PROPRE])
        resultat = C.resultats_recherche(r.json)[0]
        for jeu, scene, commit in (("cozy-room-sort", "Cuisine", COMMIT_1), ("capsule-panic", "Atelier", COMMIT_2)):
            trouve = C.dicts(resultat, lambda d: d.get("game") == jeu and d.get("scene") == scene
                             and d.get("commit") == commit)
            self.assertTrue(trouve, f"usage {jeu}/{scene}@{commit[:7]} absent du résultat : {resultat}")
