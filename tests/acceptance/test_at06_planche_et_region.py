"""AT-06 (matrice E116) : « chaque sprite extrait pointe vers sa planche et sa région vérifiée, ou marque la région inconnue. »"""
from __future__ import annotations

from . import _contrat as C
from ._base import MondeScanne
from ._monde import BOITE_ETOILE, BOITE_NUAGE, FOUET, PLANCHE


class AT06PlancheEtRegion(MondeScanne):
    """AT-06 / E116 — « AT-06 : chaque sprite extrait pointe vers sa planche et sa région vérifiée, ou
    marque la région inconnue. »

    Fixture : une planche, une table `*.decoupe.json` et un `provenance.json` au format réel (boîte
    `[w, h, x, y]`), un atlas hash dont les cadres `sprite-<id>` sont :
      - `etoile` : découpé exactement dans la boîte → pointe vers la planche (par SHA-256) avec
        `sourceRegion {x:100, y:60, w:40, h:24, verified: true}` (l'ordre w,h,x,y est converti) ;
      - `nuage` : la boîte déclarée ne correspond PAS au cadre (RMSE ≫ 0,02) → jamais `verified: true` ;
      - `lune` : « redessiné (marque) » → aucune région sur la planche, `provenance.type: derived` ;
    et un sprite sans aucune provenance (`fouet.png`) → `sourceSheetId: null`, `sourceRegion: null`.
    Le verdict de la fixture a été contrôlé avec verifier-decoupe.py : etoile RMSE 0, nuage 0,57."""

    def setUp(self):
        self.exiger_scan_ok()
        self.sha_planche = C.sha256_fichier(self.monde.depot("jeu-a") / PLANCHE)

    def test_planche_identifiee_par_empreinte_et_rattachee_a_son_fichier(self):
        trouvees = [p for p in C.planches(self.reg).values() if p.get("sha256") == self.sha_planche]
        self.assertEqual(len(trouvees), 1, "une planche, identifiée par son SHA-256")
        self.assertTrue(any(e.get("path") == PLANCHE for e in C.emplacements(trouvees[0])),
                        "la planche est rattachée au fichier trouvé dans le dépôt")

    def test_cadre_decoupe_pointe_vers_planche_et_region_verifiee(self):
        w, h, x, y = BOITE_ETOILE
        cadres = self.cadres_sur_planche("etoile", self.sha_planche)
        self.assertTrue(cadres, "aucun asset de « etoile » ne pointe vers la planche")
        regions = [a.get("sourceRegion") or {} for _, a in cadres]
        self.assertTrue(any((r.get("x"), r.get("y"), r.get("w"), r.get("h")) == (x, y, w, h)
                            and r.get("verified") is True and r.get("evidence") for r in regions),
                        f"région attendue x={x} y={y} w={w} h={h} vérifiée, avec preuve ; vu : {regions}")

    def test_boite_fausse_jamais_verifiee(self):
        w, h, x, y = BOITE_NUAGE
        for asset_id, a in C.assets_citant(self.reg, "nuage"):
            r = a.get("sourceRegion") or {}
            if self.planche_de(a) and self.planche_de(a).get("sha256") == self.sha_planche:
                self.assertIsNot(r.get("verified"), True, f"{asset_id} : région non conforme marquée vérifiée")

    def test_element_redessine_sans_region_sur_la_planche(self):
        lune = C.assets_citant(self.reg, "lune")
        self.assertTrue(lune, "l'élément redessiné doit être au catalogue")
        for asset_id, a in self.cadres_sur_planche("lune", self.sha_planche):
            self.assertIsNone(a.get("sourceRegion"), f"{asset_id} : redessiné, aucune région ne doit être inventée")
        self.assertTrue(any((a.get("provenance") or {}).get("type") == "derived" for _, a in lune),
                        "redessiné (marque) → provenance.type « derived »")

    def test_sprite_sans_provenance_region_inconnue(self):
        _, fouet = self.asset("jeu-a", FOUET)
        self.assertIsNone(fouet.get("sourceSheetId"))
        self.assertIsNone(fouet.get("sourceRegion"))
