"""Oracle de la ligne E113 de la matrice game-factory (HL-525), REG-003 § 4, écrit AVANT le code : une exigence porte un
ID, une formulation testable, sa CRITICITÉ, ses critères d'acceptation et ses preuves. La criticité vient de la ligne de
matrice (`priorite`) sinon de la priorité déclarée par le document source (« **Priorité :** P0 ») ; inconnue, elle est
« unknown », jamais devinée. `specctl sync` la recopie comme le statut."""
from __future__ import annotations

import json
import unittest

from ._outil import Docs, sha

SPEC_P0 = "# Jeu A\n\n**Version :** 1.0.0 · **Priorité :** P0\n\nLe joueur pose une tuile.\n"


class E113Criticite(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()
        s = self.d.docs / "specs" / "jeu-a-sources"
        (s / "Jeu_A_v1.0.md.txt").write_text(SPEC_P0)                           # l'archive déclare sa priorité
        (s / "empreintes-drive.sha256").write_text(f"# Drive\n{sha(SPEC_P0.encode())}  Jeu_A_v1.0.md.txt\n")
        self.ecrire_matrice(priorite_e002="P1")
        self.d.commit("priorités")

    def tearDown(self) -> None:
        self.d.nettoyer()

    def ecrire_matrice(self, priorite_e002: str | None) -> None:
        self.d.matrice("jeu-a", "Jeu_A_v1.0.md.txt", [("E001", "Le joueur pose une tuile.", "faite"),
                                                     ("E002", "La partie finit quand la réserve est vide.", "a_faire")])
        f = self.d.docs / "specs" / "jeu-a-conformite.json"
        m = json.loads(f.read_text())
        m["exigences"][0]["preuve_attendue"] = "test e2e"
        m["exigences"][0]["preuve"] = {"type": "mesure", "ref": "tests/a.test.ts", "valeur": 1, "seuil": 1}
        if priorite_e002:
            m["exigences"][1]["priorite"] = priorite_e002
        f.write_text(json.dumps(m, ensure_ascii=False, indent=1))

    def reqs(self, spec: str = "SPEC-JEU-A") -> dict[str, dict]:
        return {r["matrixId"]: r for r in self.d.registre()[spec]["requirements"]}

    def test_cinq_attributs_et_criticite(self) -> None:
        self.assertEqual(self.d.specctl("import", "--from", str(self.d.docs), "--json").rc, 0)
        r = self.reqs()
        self.assertEqual((r["E001"]["criticality"], r["E002"]["criticality"]), ("P0", "P1"))
        e1 = r["E001"]
        self.assertEqual((e1["id"], e1["acceptance"], e1["evidence"]["ref"]), ("REQ-JEU-A-E001", "test e2e", "tests/a.test.ts"))
        self.assertTrue(e1["statement"])
        self.assertEqual(self.d.specctl("validate", "--json").rc, 0)

    def test_sans_priorite_declaree_inconnue(self) -> None:
        self.d.matrice("jeu-b", "Jeu_B_v1.0.md.txt", [("E001", "Le joueur saute.", "a_faire")])
        self.d.commit("b")
        self.assertEqual(self.d.specctl("import", "--from", str(self.d.docs), "--json").rc, 0)
        self.assertEqual(self.reqs("SPEC-JEU-B")["E001"]["criticality"], "unknown")

    def test_sync_recopie_la_criticite(self) -> None:
        self.assertEqual(self.d.specctl("import", "--from", str(self.d.docs), "--json").rc, 0)
        self.ecrire_matrice(priorite_e002=None)                                # la ligne redevient P0 (en-tête)
        self.d.commit("E002 P0")
        r = self.d.specctl("sync", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(self.reqs()["E002"]["criticality"], "P0")

    def test_criticite_hors_enumeration_refusee(self) -> None:
        self.assertEqual(self.d.specctl("import", "--from", str(self.d.docs), "--json").rc, 0)
        f = self.d.usine / "specs" / "registry" / "SPEC-JEU-A.json"
        v = json.loads(f.read_text())
        v["requirements"][0]["criticality"] = "urgent"
        f.write_text(json.dumps(v, ensure_ascii=False))
        self.assertEqual(self.d.specctl("validate", "--json").rc, 2)


if __name__ == "__main__":
    unittest.main()
