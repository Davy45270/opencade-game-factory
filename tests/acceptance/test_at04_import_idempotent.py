"""AT-04 (matrice E114) : « un second import identique ne crée aucun nouvel asset. »"""
from __future__ import annotations

from . import _contrat as C
from ._base import MondeScanne


class AT04ImportIdempotent(MondeScanne):
    """AT-04 / E114 — « AT-04 : un second import identique ne crée aucun nouvel asset. »

    Intention : un deuxième `scan-repos` sur les mêmes commits rend `catalog/` identique **à l'octet**
    (aucun asset, aucun ID, aucune date nouvelle : les dates viennent des commits, pas de l'horloge) et
    `ids.json` inchangé."""

    def test_second_import_identique_a_l_octet(self):
        self.exiger_scan_ok()
        n_assets = len(C.assets(self.reg))
        self.assertGreater(n_assets, 0, "le premier import doit créer des assets")
        ids_avant = (self.reg / C.FICHIER_IDS).read_bytes()
        catalogue_avant = C.empreinte_arbre(self.reg / "catalog", avec_dates=False)
        r = self.monde.scan()
        self.exiger_code(r, C.OK)
        self.assertEqual((self.reg / C.FICHIER_IDS).read_bytes(), ids_avant, "ids.json a changé")
        self.assertEqual(C.empreinte_arbre(self.reg / "catalog", avec_dates=False), catalogue_avant,
                         "catalog/ diffère après un second import identique")
        self.assertEqual(len(C.assets(self.reg)), n_assets)

    def test_ids_stables_et_uniques(self):
        self.exiger_scan_ok()
        ids = C.lire_json(self.reg / C.FICHIER_IDS)
        valeurs = [v for v in C.parcourir(ids) if isinstance(v, str) and v.startswith(("asset-", "sheet-"))]
        self.assertEqual(len(valeurs), len(set(valeurs)), "deux clés d'identité → un même ID")
        for asset_id in C.assets(self.reg):
            self.assertIn(asset_id, valeurs, f"{asset_id} n'est pas au registre d'identifiants")
