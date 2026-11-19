"""AT-03 (matrice E113) : « aucun fichier des dépôts sources n'est modifié lors de l'inventaire. »"""
from __future__ import annotations

from . import _contrat as C
from ._base import MondeScanne


class AT03LectureSeule(MondeScanne):
    """AT-03 / E113 — « AT-03 : aucun fichier des dépôts sources n'est modifié lors de l'inventaire. »

    Intention : l'empreinte (chemins, modes, contenus, dates de modification) de l'arbre de travail
    **et** du `.git` de chaque dépôt source est identique avant et après `scan-repos`, puis après le
    second scan `--verify` ; les miroirs vivent ailleurs (cache), jamais dans la source."""

    SCANNER = False

    def test_empreintes_identiques_avant_apres(self):
        noms = ("jeu-a", "jeu-b", "intrus")
        avant = {n: C.empreinte_arbre(self.monde.depot(n)) for n in noms}
        r = self.monde.scan()
        self.exiger_code(r, C.OK)
        self.assertEqual(avant, {n: C.empreinte_arbre(self.monde.depot(n)) for n in noms},
                         "scan-repos a modifié un dépôt source (arbre de travail ou .git)")
        r = self.ctl(C.cmd_verify(self.monde.cache))
        self.exiger_code(r, C.OK)
        self.assertEqual(avant, {n: C.empreinte_arbre(self.monde.depot(n)) for n in noms},
                         "scan-repos --verify a modifié un dépôt source")
        miroirs = [p for p in self.monde.cache.rglob("*") if p.is_file()]
        self.assertTrue(miroirs, "les miroirs doivent être dans le cache, pas ailleurs")
