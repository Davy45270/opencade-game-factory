"""ARCH-001 AT-03 : un composant externe candidat est évalué licence, sécurité et maintenance AVANT adoption.

Parcours d'un paquet npm externe, de bout en bout, sur `bbctl` : l'adoption est refusée tant qu'aucune décision n'existe ;
la décision est refusée tant que l'évaluation manque ou qu'un critère (dont la maintenance) n'a pas de preuve ; une
licence inconnue ou une vulnérabilité critique non acceptée élimine le candidat AVANT le score, et un candidat éliminé ne
peut pas être retenu. Seule l'évaluation complète ouvre la décision, puis l'adoption (avec SBOM).
"""
from __future__ import annotations

import json
import unittest

from ._outil import Usine, fiche
from .test_bbctl_acceptation import evaluation
from .test_bbctl_adoption import TCO

BB = "BB-NPM-HOWLER-001"
ORIGINE = {"repositoryUrl": "https://github.com/goldfire/howler.js",
           "licenseSpdx": "MIT", "commitSha": None, "version": "2.2.4"}


class AT03EvaluationAvantAdoption(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()
        self.u.poser(fiche(BB, name="howler", kind="external-library", origin=dict(ORIGINE), usedBy=[],
                           quality={"status": "discovered", "sbomRef": None, "securityReportRef": None}))
        self.evals = self.u.usine / "blocks" / "evaluations"
        self.evals.mkdir(parents=True)

    def evaluer(self, **change) -> None:
        (self.evals / f"{BB}.json").write_text(json.dumps(evaluation(candidate=BB, **change), ensure_ascii=False))

    def decider(self):
        return self.u.bbctl("decide", "--candidate", BB, "--choice", "reuse", "--reason", "audio du jeu", "--json")

    def adopter(self):
        return self.u.bbctl("adopt", "--candidate", BB, "--used-by", "capsule-panic", "--version", "2.2.4",
                            "--pr", "https://forgejo.example/pr/9", "--tests", "tests/audio.test.ts", "--sbom", "s", "--json")

    def test_parcours_complet(self) -> None:
        self.assertNotEqual(self.adopter().rc, 0)                              # ni décision ni évaluation
        r = self.decider()
        self.assertEqual(r.rc, 1, r)
        self.assertIn("Évaluation absente", r.json["error"])

        e = evaluation(candidate=BB)
        del e["scores"]["maintenance"]                                          # maintenance non évaluée
        (self.evals / f"{BB}.json").write_text(json.dumps(e))
        self.assertEqual(self.decider().rc, 1)

        self.evaluer(tco=TCO)                                                   # sans runtime ni qualité des tests
        self.assertEqual(self.decider().rc, 3)                                  # BB-001 § 4 (E181) : refus
        # complète : gates (runtime compris), 6 critères, qualité des tests, coût total
        self.evaluer(tco=TCO, gates={"security": {"critical": 0, "accepted": False}, "provenance": "known",
                                     "technical": "ok", "runtime": "compatible"},
                     checks={"tests": {"score": 4, "preuve": "suite amont verte au tag 2.2.4"}})
        self.assertEqual(self.decider().rc, 0)
        self.assertEqual(self.adopter().rc, 0)

    def test_licence_inconnue_elimine_avant_adoption(self) -> None:
        self.u.poser(fiche(BB, name="howler", kind="external-library", origin={**ORIGINE, "licenseSpdx": "UNKNOWN"},
                           usedBy=[], quality={"status": "discovered", "sbomRef": None, "securityReportRef": None}))
        self.evaluer()
        r = self.decider()
        self.assertNotEqual(r.rc, 0, r)
        self.assertNotEqual(self.adopter().rc, 0)

    def test_vulnerabilite_critique_elimine_avant_adoption(self) -> None:
        self.evaluer(gates={"security": {"critical": 2, "accepted": False}, "provenance": "known", "technical": "ok"})
        self.assertNotEqual(self.decider().rc, 0)
        self.assertNotEqual(self.adopter().rc, 0)


if __name__ == "__main__":
    unittest.main()
