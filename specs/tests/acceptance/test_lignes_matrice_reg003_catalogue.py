"""Oracle de la ligne E152 de la matrice game-factory (HL-525), REG-11 (P1) « UI catalogue — navigation par
projet/exigence », écrit AVANT le code : `specctl export --format html` rend une page autonome où l'on navigue par
projet (sommaire → section du projet) et par exigence (index des REQ → ancre de l'exigence), texte échappé, et dont
l'export public ne montre aucune spec privée."""
from __future__ import annotations

import re
import unittest

from .._outil import Docs

REF = "HL-525 7-2955"


class E152CatalogueNavigable(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()
        self.d.matrice("jeu-b", "Jeu_B_v1.0.md.txt", [("E001", "Le joueur saute.", "a_faire")])
        self.d.commit("matrice b")
        self.assertEqual(self.d.specctl("import", "--from", str(self.d.docs), "--json").rc, 0)

    def tearDown(self) -> None:
        self.d.nettoyer()

    def html(self, *extra: str) -> str:
        r = self.d.specctl("export", "--format", "html", *extra, "--json")
        self.assertEqual(r.rc, 0, r)
        return r.json["html"]

    def test_navigation_par_projet_et_par_exigence(self) -> None:
        h = self.html()
        self.assertTrue(h.startswith("<!doctype html>"))
        for projet in ("jeu-a", "jeu-b"):
            self.assertIn(f'href="#projet-{projet}"', h)                       # sommaire → projet
            self.assertIn(f'id="projet-{projet}"', h)
        for req in ("REQ-JEU-A-E001", "REQ-JEU-A-E002", "REQ-JEU-B-E001"):
            self.assertIn(f'href="#{req}"', h)                                 # index des exigences → ancre
            self.assertEqual(len(re.findall(f'id="{req}"', h)), 1)
        self.assertRegex(h, r'id="REQ-JEU-A-E001"[^>]*>.*faite')                # statut visible sur l'exigence
        ancres = set(re.findall(r'id="([^"]+)"', h))
        for cible in re.findall(r'href="#([^"]+)"', h):
            self.assertIn(cible, ancres)                                       # aucun lien de navigation cassé

    def test_texte_echappe(self) -> None:
        self.d.matrice("jeu-b", "Jeu_B_v1.0.md.txt", [("E001", "<script>alert(1)</script>", "a_faire")])
        self.d.commit("piège")
        self.d.specctl("sync", "--from", str(self.d.docs), "--json")
        self.assertNotIn("<script>alert", self.html())

    def test_export_public_sans_spec_privee(self) -> None:
        self.assertEqual(self.d.specctl("statuer", "--spec", "SPEC-JEU-B", "--visibility", "public", "--ref", REF,
                                        "--json").rc, 0)
        h = self.html("--public")
        self.assertIn("projet-jeu-b", h)
        self.assertNotIn("SPEC-JEU-A", h)
        self.assertNotIn("homelab-docs", h)


if __name__ == "__main__":
    unittest.main()
