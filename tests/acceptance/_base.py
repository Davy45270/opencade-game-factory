"""Classe commune : un monde de fixture par classe de test, scanné une fois."""
from __future__ import annotations

import os
import unittest

from . import _contrat as C
from ._monde import Monde, creer_monde


class MondeScanne(unittest.TestCase):
    """Construit le monde, lance `scan-repos` une fois, et le garde pour toute la classe.
    `GARDER_FIXTURES=1` conserve le dossier temporaire pour l'inspecter."""

    monde: Monde
    scan: C.Resultat
    FANTOME = False
    SCANNER = True

    @classmethod
    def setUpClass(cls) -> None:
        cls.monde = creer_monde(fantome=cls.FANTOME)
        if cls.SCANNER:
            cls.scan = cls.monde.scan()

    @classmethod
    def tearDownClass(cls) -> None:
        if os.environ.get("GARDER_FIXTURES") != "1":
            cls.monde.nettoyer()

    # -- aides --------------------------------------------------------------------------------
    @property
    def reg(self):
        return self.monde.registre

    def ctl(self, args: list[str]) -> C.Resultat:
        return self.monde.ctl(args)

    def exiger_code(self, r: C.Resultat, code: int) -> None:
        self.assertEqual(r.code, code, f"code {code} attendu\n{r}")

    def exiger_scan_ok(self) -> None:
        self.exiger_code(self.scan, C.OK)
        self.assertIsNotNone(self.scan.json, f"scan-repos --json doit rendre du JSON\n{self.scan}")

    def asset(self, depot: str, chemin: str) -> tuple[str, dict]:
        return C.asset_par_chemin(self.reg, depot, chemin)

    def planche_de(self, asset: dict) -> dict | None:
        sid = asset.get("sourceSheetId")
        return C.planches(self.reg).get(sid) if sid else None

    def cadres_sur_planche(self, nom: str, sha_planche: str) -> list[tuple[str, dict]]:
        """Assets de l'élément `nom` (cité quelque part dans leur JSON) rattachés à la planche d'empreinte
        `sha_planche` par `sourceSheetId`."""
        return [(i, a) for i, a in C.assets_citant(self.reg, nom)
                if (p := self.planche_de(a)) is not None and p.get("sha256") == sha_planche]

    def usages(self, asset_id: str, asset: dict) -> list[dict]:
        """Usages de l'asset : ceux du catalogue, plus ceux que rend `assetctl usage <id> --json`."""
        trouves = [u for u in (asset.get("usages") or []) if isinstance(u, dict)]
        r = self.ctl(["usage", asset_id, "--json"])
        if r.code == C.OK and r.json is not None:
            trouves += C.dicts(r.json, lambda d: "scene" in d and "commit" in d)
        return trouves
