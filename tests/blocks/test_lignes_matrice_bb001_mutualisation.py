"""Oracles ligne par ligne de la matrice game-factory (HL-525), BB-001 § 9 et BB-12, écrits AVANT le code.

- E225 (BB-12) : `bbctl mutualiser` recommande d'extraire une brique partagée quand un même module vit dans plusieurs
  dépôts ; chaque recommandation chiffre ses GAINS (dépôts, exports communs) et ses RISQUES (couplage par imports
  locaux, modules sans tests, licences divergentes).
- E213 : une brique partagée ne s'extrait que si la mutualisation est justifiée — `decide` d'une `shared-library`
  sans recommandation « extract » est refusé (3).
"""
from __future__ import annotations

import json
import unittest

from ._outil import Usine, fiche


def module(repo, nom, exports, tests=(), imports=(), licence="MIT"):
    return fiche(f"BB-{repo.upper()}-{nom.upper()}-001", name=nom, usedBy=[f"{repo}/games/x"],
                 origin={"repositoryUrl": None, "repo": repo, "path": f"src/engines/{nom}", "licenseSpdx": licence,
                         "commitSha": None},
                 quality={"status": "discovered", "sbomRef": None, "securityReportRef": None},
                 discovery={"key": f"local:{repo}:src/engines/{nom}", "ecosystem": "local"},
                 analysis={"exports": list(exports), "imports": list(imports), "tests": list(tests),
                           "maintainers": None, "coverage": None, "maturity": "tested" if tests else "untested"})


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()
        (self.u.usine / "blocks" / "catalog" / "BB-SIX-PATHFINDING-001.json").unlink()
        self.u.poser(module("alpha", "grille", ["Grid", "neighbours"], tests=["t1.test.ts"]))
        self.u.poser(module("beta", "grille", ["Grid", "neighbours", "path"], tests=["t2.test.ts"]))
        self.u.poser(module("alpha", "combat", ["attaque"], imports=["local:alpha:src/engines/grille"]))
        self.u.poser(module("beta", "combat", ["attaque"], tests=["t3.test.ts"], licence="GPL-3.0-only"))
        self.u.poser(module("gamma", "audio", ["jouer"], tests=["t4.test.ts"]))

    def tearDown(self) -> None:
        self.u.nettoyer()

    def recommandations(self) -> dict:
        r = self.u.bbctl("mutualiser", "--json")
        self.assertEqual(r.rc, 0, r)
        return {g["name"]: g for g in r.json["groups"]}


class E225RecommandationsGainsEtRisques(Base):
    def test_gains_et_risques_justifies(self) -> None:
        g = self.recommandations()
        self.assertNotIn("audio", g)                                          # un seul dépôt : rien à mutualiser
        grille = g["grille"]
        self.assertEqual(grille["recommendation"], "extract")
        self.assertEqual(grille["gains"], {"repos": ["alpha", "beta"], "sharedExports": ["Grid", "neighbours"],
                                           "modules": ["BB-ALPHA-GRILLE-001", "BB-BETA-GRILLE-001"]})
        self.assertEqual(grille["risks"], {"coupling": [], "untested": [], "licenses": ["MIT"]})
        combat = g["combat"]
        self.assertEqual(combat["recommendation"], "keep-local")
        self.assertEqual(combat["risks"]["coupling"], ["BB-ALPHA-COMBAT-001 -> local:alpha:src/engines/grille"])
        self.assertEqual(combat["risks"]["untested"], ["BB-ALPHA-COMBAT-001"])
        self.assertEqual(combat["risks"]["licenses"], ["GPL-3.0-only", "MIT"])
        self.assertTrue(combat["reasons"])


class E213ExtractionSeulementSiJustifiee(Base):
    def partagee(self, nom: str) -> None:
        self.u.poser(fiche(f"BB-SHARED-{nom.upper()}-001", name=nom, kind="shared-library", usedBy=[],
                           origin={"repositoryUrl": None, "licenseSpdx": "MIT", "commitSha": None},
                           quality={"status": "candidate", "sbomRef": None, "securityReportRef": None}))
        d = self.u.usine / "blocks" / "evaluations"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"BB-SHARED-{nom.upper()}-001.json").write_text(json.dumps({
            "candidate": f"BB-SHARED-{nom.upper()}-001", "date": "2026-11-22",
            "gates": {"security": {"critical": 0, "accepted": False}, "provenance": "known", "technical": "ok"},
            "scores": {k: {"score": 4, "preuve": f"mesure {k}"} for k in
                       ("adequation", "integration", "maintenance", "licence", "securite", "cout")}}))

    def decider(self, nom: str):
        return self.u.bbctl("decide", "--candidate", f"BB-SHARED-{nom.upper()}-001", "--choice", "build",
                            "--reason", "extraction de la brique partagée", "--json")

    def test_extraction_justifiee_acceptee(self) -> None:
        self.partagee("grille")
        r = self.decider("grille")
        self.assertEqual(r.rc, 0, r)

    def test_extraction_non_justifiee_refusee(self) -> None:
        self.partagee("combat")                                                # couplage, sans tests, licences
        r = self.decider("combat")
        self.assertEqual(r.rc, 3, r)
        self.assertIn("mutualisation", r.stdout)
        self.partagee("audio")                                                 # un seul dépôt
        self.assertEqual(self.decider("audio").rc, 3)


if __name__ == "__main__":
    unittest.main()
