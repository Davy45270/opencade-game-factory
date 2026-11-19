"""Oracles REG-07 (REG-003 § 4, § 5.6 ; REG-T05) : traçabilité des tests, couverture CALCULÉE avec preuves.

Écrits AVANT le code (Claude, oracle, HL-525 19/11, lot (c)) : ils échouent tant que `specctl coverage` n'existe pas.
L'implémentation (Codex) les fait passer SANS les modifier ; un oracle jugé faux se signale dans le rapport.

Contrat d'appel (en plus de tests/specs/_outil.py) :
  specctl coverage --project <jeu> --json
  - lit le registre (USINE_RACINE) ; l'import (`specctl import`) y porte, pour chaque exigence, le statut ET la preuve
    de la ligne de matrice (`preuve` : type + ref ; `arbitrage` pour une écartée) — rien n'est recalculé de mémoire ;
  - rend {"project", "total", "covered", "waived", "uncovered": [REQ-…], "ratio", "requirements": [{"id",
    "matrixId", "status", "evidence": {"type", "ref"} | null}], "inconsistent": [REQ-…]} ;
  - covered = « faite » AVEC preuve ; waived = « ecartee » (hors dénominateur) ; ratio = covered / (total − waived),
    arrondi à 4 décimales ; une « faite » SANS preuve est incohérente : listée dans `inconsistent`, non couverte, code 1 ;
  - projet inconnu = 1 ; aucune écriture.
"""
from __future__ import annotations

import json
import unittest

from ._outil import SPEC_A, Docs, sha

SPEC_C = SPEC_A + "Le score s'affiche.\nLa sauvegarde est locale.\n"


class REG07Couverture(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()
        self.d.archive("jeu-c", {"Jeu_C_v1.0.md.txt": SPEC_C})
        f = "specs/jeu-c-sources/Jeu_C_v1.0.md.txt"
        lignes = [
            {"id": "E001", "statut": "faite", "extrait": "Le joueur pose une tuile.",
             "preuve": {"type": "test", "ref": "tests/regle.test.ts > pose une tuile"}},
            {"id": "E002", "statut": "a_faire", "extrait": "La partie finit quand la réserve est vide."},
            {"id": "E003", "statut": "ecartee", "extrait": "Le score s'affiche.",
             "arbitrage": {"ref": "HL-0 7-0", "date": "2026-11-19", "valide_par_david": True, "expire": "0.2.0"}},
            {"id": "E004", "statut": "faite", "extrait": "La sauvegarde est locale.",
             "preuve": {"type": "capture", "ref": "partie-390x844.png"}},
        ]
        m = {"schema": "conformite-jeu/1", "jeu": "jeu-c", "sources": [{"fichier": f, "sha256": sha((self.d.docs / f).read_bytes())}],
             "exigences": [{"id": l["id"], "source": {"fichier": f, "extrait": l["extrait"]}, "statut": l["statut"],
                            **({"preuve": l["preuve"]} if "preuve" in l else {}),
                            **({"arbitrage": l["arbitrage"]} if "arbitrage" in l else {})} for l in lignes]}
        (self.d.docs / "specs" / "jeu-c-conformite.json").write_text(json.dumps(m, ensure_ascii=False, indent=1))
        self.d.commit("jeu C")

    def tearDown(self) -> None:
        self.d.nettoyer()

    def importer(self) -> None:
        r = self.d.specctl("import", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 0, r)

    def couverture(self, projet: str = "jeu-c"):
        return self.d.specctl("coverage", "--project", projet, "--json")

    def test_couverture_calculee(self) -> None:
        self.importer()
        r = self.couverture()
        self.assertEqual(r.rc, 0, r)
        v = r.json
        self.assertEqual((v["project"], v["total"], v["covered"], v["waived"]), ("jeu-c", 4, 2, 1))
        self.assertEqual(v["ratio"], round(2 / 3, 4))
        self.assertEqual(v["uncovered"], ["REQ-JEU-C-E002"])
        self.assertEqual(v["inconsistent"], [])

    def test_chaque_exigence_couverte_porte_sa_preuve(self) -> None:
        self.importer()
        par_id = {x["matrixId"]: x for x in self.couverture().json["requirements"]}
        self.assertEqual(par_id["E001"]["evidence"], {"type": "test", "ref": "tests/regle.test.ts > pose une tuile"})
        self.assertEqual(par_id["E004"]["evidence"]["type"], "capture")
        self.assertIsNone(par_id["E002"]["evidence"])
        self.assertEqual(par_id["E003"]["status"], "ecartee")

    def test_faite_sans_preuve_incoherente(self) -> None:
        p = self.d.docs / "specs" / "jeu-c-conformite.json"
        m = json.loads(p.read_text())
        del m["exigences"][3]["preuve"]
        p.write_text(json.dumps(m, ensure_ascii=False, indent=1))
        self.d.commit("E004 sans preuve")
        self.importer()
        r = self.couverture()
        self.assertEqual(r.rc, 1, r)
        self.assertEqual(r.json["inconsistent"], ["REQ-JEU-C-E004"])
        self.assertEqual(r.json["covered"], 1)
        self.assertIn("REQ-JEU-C-E004", r.json["uncovered"])

    def test_projet_inconnu(self) -> None:
        self.importer()
        self.assertEqual(self.couverture("inexistant").rc, 1)

    def test_lecture_seule(self) -> None:
        self.importer()
        avant = (self.d.empreinte_usine(), self.d.empreinte_docs())
        r = self.couverture()
        self.assertEqual(r.rc, 0, r)
        self.assertEqual((self.d.empreinte_usine(), self.d.empreinte_docs()), avant)

    def test_deterministe(self) -> None:
        self.importer()
        a, b = self.couverture(), self.couverture()
        self.assertEqual((a.rc, b.rc), (0, 0), a)
        self.assertEqual(a.stdout, b.stdout)


if __name__ == "__main__":
    unittest.main()
