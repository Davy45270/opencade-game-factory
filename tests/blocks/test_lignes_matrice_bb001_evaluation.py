"""Oracles ligne par ligne de la matrice game-factory (HL-525), BB-001 § 4 et § 6, écrits AVANT le code.

- E181 : avant d'adopter un composant open source, l'évaluation vérifie URL canonique, licence exacte, maintenance,
  vulnérabilités, compatibilité runtime, qualité des tests et coût d'intégration ; une vérification manquante bloque
  la réutilisation d'une brique EXTERNE (refus 3), une incompatibilité runtime l'élimine avant le score.
- E226 (BB-13) : TCO — hypothèses chiffrées par poste (§ 6 : intégration, adaptation, maintenance, mises à jour,
  charge de tests, dette de sécurité, coût de sortie), puis mesure après adoption et écart.
"""
from __future__ import annotations

import json
import unittest

from ._outil import Usine, fiche

CRITERES = ("adequation", "integration", "maintenance", "licence", "securite", "cout")
POSTES = ("integration", "adaptation", "maintenance", "misesAJour", "tests", "detteSecurite", "sortie")
BB = "BB-NPM-HOWLER-001"
ORIGINE = {"repositoryUrl": "https://github.com/goldfire/howler.js", "licenseSpdx": "MIT", "commitSha": None,
           "version": "2.2.4"}


def evaluation(**change) -> dict:
    e = {"candidate": BB, "date": "2026-11-22",
         "gates": {"security": {"critical": 0, "accepted": False}, "provenance": "known", "technical": "ok",
                   "license": "compatible", "runtime": "compatible"},
         "checks": {"tests": {"score": 4, "preuve": "suite jest du dépôt amont, 212 tests, CI verte au tag 2.2.4"}},
         "scores": {k: {"score": 4, "preuve": f"mesure {k}"} for k in CRITERES},
         "tco": {k: {"estimation": "2 h", "hypothese": f"hypothèse {k}"} for k in POSTES}}
    e.update(change)
    return e


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()
        self.u.poser(fiche(BB, name="howler", kind="external-library", origin=dict(ORIGINE), usedBy=[],
                           quality={"status": "candidate", "sbomRef": None, "securityReportRef": None}))

    def tearDown(self) -> None:
        self.u.nettoyer()

    def poser(self, e: dict) -> None:
        d = self.u.usine / "blocks" / "evaluations"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{BB}.json").write_text(json.dumps(e, ensure_ascii=False))

    def evaluer(self):
        return self.u.bbctl("evaluate", "--candidate", BB, "--json")

    def decider(self):
        return self.u.bbctl("decide", "--candidate", BB, "--choice", "reuse", "--reason", "son du jeu", "--json")


class E181VerificationsAvantAdoption(Base):
    def test_sept_verifications_puis_decision(self) -> None:
        self.poser(evaluation())
        r = self.evaluer()
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(r.json["verifications"], {k: "verified" for k in (
            "canonicalUrl", "license", "maintenance", "vulnerabilities", "runtime", "tests", "integrationCost")})
        self.assertEqual(self.decider().rc, 0)

    def test_verification_manquante_bloque_la_reutilisation(self) -> None:
        e = evaluation()
        del e["checks"]
        del e["gates"]["runtime"]
        self.poser(e)
        r = self.evaluer()
        self.assertEqual(r.rc, 0, r)
        self.assertEqual((r.json["verifications"]["runtime"], r.json["verifications"]["tests"]), ("missing", "missing"))
        r = self.decider()
        self.assertEqual(r.rc, 3, r)
        self.assertIn("runtime", r.stdout)

    def test_runtime_incompatible_elimine_avant_le_score(self) -> None:
        e = evaluation()
        e["gates"]["runtime"] = "incompatible"
        self.poser(e)
        r = self.evaluer()
        self.assertEqual((r.json["eliminated"], r.json["gates"].get("runtime"), r.json["score"]), (True, "incompatible", None))

    def test_url_canonique_absente(self) -> None:
        self.u.poser(fiche(BB, name="howler", kind="external-library", origin={**ORIGINE, "repositoryUrl": None},
                           usedBy=[], quality={"status": "candidate", "sbomRef": None, "securityReportRef": None}))
        self.poser(evaluation())
        self.assertEqual(self.evaluer().json["verifications"]["canonicalUrl"], "missing")
        self.assertEqual(self.decider().rc, 3)


class E226Tco(Base):
    """Hypothèses au format de `bbctl adopt` (tco.<poste>.estimation/hypothese) ; mesure après adoption (tcoMesure)."""

    def mesure(self, **postes) -> dict:
        return {"date": "2026-12-01", "postes": {k: {"mesure": "3 h", "preuve": f"relevé {k}"} for k in POSTES} | postes}

    def test_hypotheses_puis_mesure_apres_adoption(self) -> None:
        self.poser(evaluation())
        tco = self.evaluer().json["tco"]
        self.assertEqual((tco["hypotheses"], tco["measuredAt"], tco["comparison"], tco["measurementDue"]),
                         ("complete", None, None, False))
        self.u.poser(fiche(BB, name="howler", kind="external-library", origin=dict(ORIGINE), usedBy=["jeu"],
                           quality={"status": "adopted", "sbomRef": "sbom.json", "securityReportRef": None}))
        self.assertTrue(self.evaluer().json["tco"]["measurementDue"])        # adoptée sans mesure : à faire
        self.poser(evaluation(tcoMesure=self.mesure()))
        tco = self.evaluer().json["tco"]
        self.assertEqual((tco["measuredAt"], tco["measurementDue"]), ("2026-12-01", False))
        self.assertEqual(tco["comparison"][0], {"poste": "integration", "estimation": "2 h", "mesure": "3 h"})
        self.assertEqual([c["poste"] for c in tco["comparison"]], list(POSTES))

    def test_mesure_incomplete_ou_sans_preuve_refusee(self) -> None:
        m = self.mesure()
        del m["postes"]["sortie"]                                             # coût de sortie oublié
        self.poser(evaluation(tcoMesure=m))
        self.assertEqual(self.evaluer().rc, 1)
        self.poser(evaluation(tcoMesure=self.mesure(tests={"mesure": "1 h", "preuve": " "})))
        self.assertEqual(self.evaluer().rc, 1)

    def test_hypothese_manquante_dite_incomplete(self) -> None:
        e = evaluation()
        del e["tco"]["sortie"]
        self.poser(e)
        r = self.evaluer()
        self.assertEqual((r.rc, r.json["tco"]["hypotheses"]), (0, "incomplete"))

    def test_evaluation_sans_tco_dit_que_le_tco_manque(self) -> None:
        e = evaluation()
        del e["tco"]
        self.poser(e)
        r = self.evaluer()
        self.assertEqual((r.rc, r.json["tco"], r.json["verifications"]["integrationCost"]), (0, None, "missing"))


if __name__ == "__main__":
    unittest.main()
