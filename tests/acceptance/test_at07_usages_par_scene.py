"""AT-07 (matrice E117) : « les usages d'un sprite sont retrouvés par dépôt, jeu, scène et commit lorsque la référence est statiquement déterminable. »"""
from __future__ import annotations

from . import _contrat as C
from ._base import MondeScanne
from ._monde import FOUET, NIVEAU, SCENE, ligne_de, texte_scene


class AT07UsagesParScene(MondeScanne):
    """AT-07 / E117 — « AT-07 : les usages d'un sprite sont retrouvés par dépôt, jeu, scène et commit
    lorsque la référence est statiquement déterminable. »

    Fixture : `src/scenes/Cuisine.ts` (`super('Cuisine')`) contient
    `this.load.image('fouet', 'assets/fouet.png')` (fichier dans `public/assets/`, résolu à la Vite) et
    un gabarit `` `assets/niveau-${n}.png` `` alors que `niveau-1.png` existe (tentation de deviner)."""

    def test_usage_complet_du_chargement_litteral(self):
        self.exiger_scan_ok()
        asset_id, fouet = self.asset("jeu-a", FOUET)
        ligne = ligne_de(texte_scene(), "'fouet'")
        attendu = {"repo": "jeu-a", "game": "jeu-a", "scene": "Cuisine", "commit": self.monde.commits["jeu-a"]}
        usages = self.usages(asset_id, fouet)
        bons = [u for u in usages if all(u.get(k) == v for k, v in attendu.items())]
        self.assertTrue(bons, f"usage {attendu} introuvable ; vu : {usages}")
        u = bons[0]
        self.assertEqual((u.get("codeRef") or {}).get("path"), SCENE)
        self.assertEqual((u.get("codeRef") or {}).get("line"), ligne)
        self.assertEqual(u.get("importName"), "fouet")
        self.assertEqual(u.get("status"), "active")
        self.assertIn("v1.0", u.get("releases") or [], "le tag v1.0 porte le code et l'asset")

    def test_usage_dans_l_index_inverse(self):
        self.exiger_scan_ok()
        self.exiger_code(self.ctl(C.cmd_index()), C.OK)
        asset_id, _ = self.asset("jeu-a", FOUET)
        index = C.lire_json(self.reg / "generated/usage-index.json")
        self.assertTrue(C.contient_valeur(index, asset_id), "l'asset doit figurer dans l'index inversé")
        self.assertTrue(C.contient_texte(index, "Cuisine"), "la scène doit figurer dans l'index inversé")

    def test_gabarit_journalise_jamais_devine(self):
        self.exiger_scan_ok()
        ligne = ligne_de(texte_scene(), "niveau-${n}")
        dyn = C.lire_json(self.reg / C.RAPPORT_REFS_DYNAMIQUES)
        self.assertTrue(C.dicts(dyn, lambda d: C.contient_valeur(d, SCENE) and C.contient_valeur(d, ligne)),
                        f"référence dynamique {SCENE}:{ligne} absente de dynamic-refs.json")
        asset_id, niveau = self.asset("jeu-a", NIVEAU)
        devines = [u for u in self.usages(asset_id, niveau) if (u.get("codeRef") or {}).get("path") == SCENE]
        self.assertEqual(devines, [], "un gabarit `${}` ne doit jamais être résolu par devinette")
