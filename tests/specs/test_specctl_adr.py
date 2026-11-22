"""ARCH-001 E005 et § 3.2 : REG-003 tient aussi les décisions d'architecture (ADR) d'une spec, par identifiant.

`decisions` d'une fiche peut citer `ADR-<n>` : `specctl blocks` le résout dans `docs/integration-decisions/ADR-<n>-*.md`
de l'usine, sans le recopier. Une ADR introuvable est un lien cassé ; une ADR non approuvée, ou sans l'arbitrage de
David qui l'approuve, n'est pas traçable : les deux rendent le code 2 (non-conformité).
"""
from __future__ import annotations

import json
import unittest

from ._outil import Docs

ADR = """# ADR-0001 — Décision de test

- **Statut :** {statut}
- **Date :** 2026-11-19
- **Approuvée par :** David, HL-525 7-2955

## Contexte

c

## Décision

d
"""


class SpecctlAdr(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()
        self.assertEqual(self.d.specctl("import", "--from", str(self.d.docs), "--json").rc, 0)
        f = self.d.usine / "specs" / "registry" / "SPEC-JEU-A.json"
        v = json.loads(f.read_text())
        v["decisions"] = ["ADR-0001"]
        f.write_text(json.dumps(v, ensure_ascii=False))
        self.adr = self.d.usine / "docs" / "integration-decisions" / "ADR-0001-decision-de-test.md"
        self.adr.parent.mkdir(parents=True)

    def tearDown(self) -> None:
        self.d.nettoyer()

    def blocks(self):
        return self.d.specctl("blocks", "--spec", "SPEC-JEU-A", "--json")

    def test_adr_approuvee_resolue_par_reference(self) -> None:
        self.adr.write_text(ADR.format(statut="approuvée"))
        r = self.blocks()
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(r.json["decisions"], [{"adrId": "ADR-0001", "decided": True, "ref": "HL-525 7-2955",
                                                "path": "docs/integration-decisions/ADR-0001-decision-de-test.md"}])

    def test_adr_introuvable_lien_casse(self) -> None:
        r = self.blocks()
        self.assertEqual((r.rc, r.json["brokenLinks"]), (2, ["ADR-0001"]), r)

    def test_adr_non_approuvee_non_tracable(self) -> None:
        self.adr.write_text(ADR.format(statut="proposée"))
        r = self.blocks()
        self.assertEqual((r.rc, r.json["untraceable"]), (2, ["ADR-0001"]), r)

    def test_adr_sans_arbitrage_de_david_non_tracable(self) -> None:
        self.adr.write_text(ADR.format(statut="approuvée").replace("David, HL-525 7-2955", "un agent"))
        r = self.blocks()
        self.assertEqual((r.rc, r.json["untraceable"]), (2, ["ADR-0001"]), r)


if __name__ == "__main__":
    unittest.main()
