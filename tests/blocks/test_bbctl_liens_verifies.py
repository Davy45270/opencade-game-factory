"""Oracle ARCH-001 E055 (liens vérifiables, ne rien inventer), écrit AVANT le code : `bbctl validate --all` refuse une
fiche dont un `specIds` ne résout vers aucune fiche du registre des specs. Registre absent = indisponibilité dite,
jamais une non-conformité (ARCH-001 E039)."""
from __future__ import annotations

import json
import unittest

from ._outil import Usine, fiche


class LiensVerifies(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()

    def tearDown(self) -> None:
        self.u.nettoyer()

    def registre(self) -> None:
        reg = self.u.usine / "specs" / "registry"
        reg.mkdir(parents=True)
        (reg / "SPEC-SIX-DE-CHAQUE.json").write_text(json.dumps({"id": "SPEC-SIX-DE-CHAQUE", "project": "six-de-chaque"}))

    def test_lien_resolu_accepte(self) -> None:
        self.registre()
        self.u.poser(fiche(specIds=["SPEC-SIX-DE-CHAQUE"]))
        r = self.u.bbctl("validate", "--all", "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(r.json["specLinks"], "verifies")

    def test_lien_non_resolu_refuse(self) -> None:
        self.registre()
        self.u.poser(fiche(specIds=["SPEC-INVENTEE"]))
        r = self.u.bbctl("validate", "--all", "--json")
        self.assertEqual(r.rc, 1, r)
        self.assertEqual(r.json["status"], "check-failed")
        self.assertIn("SPEC-INVENTEE", r.json["error"])

    def test_registre_absent_dit_sans_refuser(self) -> None:
        self.u.poser(fiche(specIds=["SPEC-SIX-DE-CHAQUE"]))
        r = self.u.bbctl("validate", "--all", "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(r.json["specLinks"], "registre-absent")


if __name__ == "__main__":
    unittest.main()
