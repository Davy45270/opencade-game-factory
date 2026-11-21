"""Oracles BB-001 E179 (HL-525), écrits AVANT le code : relier chaque brique aux spécifications REG-003 des projets
qui la consomment.

`bbctl link-specs [--dry-run] --json` : pour chaque fiche, `specIds` reçoit `SPEC-<PROJET>` de chaque dépôt
consommateur (premier segment de `usedBy`) dont la spec existe au registre `specs/registry/` de l'usine. Un lien posé à
la main n'est jamais retiré ; un dépôt sans spec est signalé, jamais inventé ; relance = octets identiques.
"""
from __future__ import annotations

import json
import unittest

from ._outil import Usine, fiche


class LienSpecs(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()
        reg = self.u.usine / "specs" / "registry"
        reg.mkdir(parents=True)
        for projet in ("six-de-chaque", "capsule-panic"):
            (reg / f"SPEC-{projet.upper()}.json").write_text(json.dumps({"id": f"SPEC-{projet.upper()}", "project": projet}))
        self.u.poser(fiche(id="BB-A-001", usedBy=["six-de-chaque/apps/web", "capsule-panic", "tictac"], specIds=[]))
        self.u.poser(fiche(id="BB-B-001", usedBy=["tictac"], specIds=["SPEC-MANUEL"]))

    def tearDown(self) -> None:
        self.u.nettoyer()

    def lire(self, i: str) -> dict:
        return json.loads((self.u.usine / "blocks" / "catalog" / f"{i}.json").read_text())

    def test_specs_des_consommateurs_reliees(self) -> None:
        r = self.u.bbctl("link-specs", "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(self.lire("BB-A-001")["specIds"], ["SPEC-CAPSULE-PANIC", "SPEC-SIX-DE-CHAQUE"])
        self.assertEqual(r.json["withoutSpec"], ["tictac"])
        self.assertEqual(self.u.bbctl("validate", "--all", "--json").rc, 0)

    def test_lien_manuel_garde_rien_d_invente(self) -> None:
        self.u.bbctl("link-specs", "--json")
        self.assertEqual(self.lire("BB-B-001")["specIds"], ["SPEC-MANUEL"])

    def test_dry_run_puis_relance_idempotente(self) -> None:
        avant = self.u.empreinte(self.u.usine)
        r = self.u.bbctl("link-specs", "--dry-run", "--json")
        self.assertEqual((r.rc, r.json["linked"]), (0, 2), r)                    # BB-A et la fiche de la fixture
        self.assertEqual(self.u.empreinte(self.u.usine), avant)
        self.u.bbctl("link-specs", "--json")
        apres = self.u.empreinte(self.u.usine)
        self.assertEqual(self.u.bbctl("link-specs", "--json").json["linked"], 0)
        self.assertEqual(self.u.empreinte(self.u.usine), apres)


if __name__ == "__main__":
    unittest.main()
