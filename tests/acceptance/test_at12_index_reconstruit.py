"""AT-12 (matrice E122) : « l'index de recherche est reconstruit à partir du seul catalogue versionné. »"""
from __future__ import annotations

import shutil

from . import _contrat as C
from ._base import MondeScanne
from ._monde import FOUET


class AT12IndexReconstruit(MondeScanne):
    """AT-12 / E122 — « AT-12 : l'index de recherche est reconstruit à partir du seul catalogue versionné. »

    Intention : après un `index`, on supprime `generated/` et la base SQLite, on rend les dépôts
    sources ET le cache des miroirs inaccessibles, puis `assetctl index` : les fichiers d'index sont
    identiques à l'octet (et l'empreinte rendue par `index` aussi), et la recherche retrouve l'asset —
    donc seul `catalog/` a servi."""

    def _empreinte(self) -> dict[str, str]:
        return {f: C.sha256_fichier(self.reg / f) for f in C.FICHIERS_INDEX}

    def test_reconstruction_identique_depuis_catalog_seul(self):
        self.exiger_scan_ok()
        r1 = self.ctl(C.cmd_index())
        self.exiger_code(r1, C.OK)
        for f in C.FICHIERS_INDEX:
            self.assertTrue((self.reg / f).is_file(), f"{f} absent après index")
        self.assertTrue((self.reg / C.BASE_SQLITE).is_file(), f"{C.BASE_SQLITE} absente après index")
        avant = self._empreinte()

        shutil.rmtree(self.reg / "generated")
        (self.reg / C.BASE_SQLITE).unlink()
        cache, cache_cache = self.monde.cache, self.monde.cache.with_name("mirrors-caches")
        depots, depots_caches = self.monde.depots, self.monde.depots.with_name("depots-caches")
        cache.rename(cache_cache)
        depots.rename(depots_caches)
        try:
            r2 = self.ctl(C.cmd_index())
            self.exiger_code(r2, C.OK)
            self.assertEqual(avant, self._empreinte(), "index reconstruit différent")
            if isinstance(r1.json, dict) and isinstance(r2.json, dict):
                self.assertEqual({k: v for k, v in r1.json.items() if "empreinte" in k or "fingerprint" in k
                                  or "sha" in k},
                                 {k: v for k, v in r2.json.items() if "empreinte" in k or "fingerprint" in k
                                  or "sha" in k}, "empreinte rendue par index différente")
            asset_id, _ = C.asset_par_chemin(self.reg, "jeu-a", FOUET)
            r = self.ctl(C.cmd_search("fouet"))
            self.exiger_code(r, C.OK)
            self.assertIn(asset_id, [x.get("id") for x in C.resultats_recherche(r.json)])
        finally:
            cache_cache.rename(cache)
            depots_caches.rename(depots)
