"""ARCH-001 AT-02 : un processus déclaré mais inaccessible reste `unknown` et bloque la décision de remplacement
automatique.

Le processus déclaré est la recherche interne sur graphify (BB-001 § 5, étape 2 d'ARCH-001 § 10) : elle seule dit ce
qui existe déjà. Quand le graphe est inaccessible, ce qui existe est INCONNU, pas absent : `bbctl decide --choice build`
(construire au lieu de réutiliser, donc remplacer l'existant) est refusé, code 4, statut `unknown`, et la fiche n'est
pas écrite. Les décisions qui n'en remplacent rien (reuse, adapt, wrap, fork, defer) restent permises. Avec le graphe
lisible, `build` passe et la décision garde l'empreinte du graphe consulté.
"""
from __future__ import annotations

import hashlib
import json
import unittest

from ._outil import Usine, fiche, sha
from .test_bbctl_acceptation import evaluation

BB = "BB-SIX-PATHFINDING-001"


class AT02InaccessibleResteInconnu(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()
        d = self.u.usine / "blocks" / "evaluations"
        d.mkdir(parents=True)
        (d / f"{BB}.json").write_text(json.dumps(evaluation(candidate=BB), ensure_ascii=False))
        self.fiche = self.u.usine / "blocks" / "catalog" / f"{BB}.json"

    def decider(self, choix: str, graphe: str):
        return self.u.bbctl("decide", "--candidate", BB, "--choice", choix, "--reason", "essai AT-02",
                            "--graph", graphe, "--json")

    def test_graphe_inaccessible_bloque_build(self) -> None:
        avant = hashlib.sha256(self.fiche.read_bytes()).hexdigest()
        r = self.decider("build", str(self.u.tmp / "absent.json"))
        self.assertEqual((r.rc, r.json["status"]), (4, "unknown"), r)
        self.assertIn("inconnu", r.json["error"])
        self.assertEqual(hashlib.sha256(self.fiche.read_bytes()).hexdigest(), avant)      # rien n'est écrit

    def test_graphe_illisible_bloque_build(self) -> None:
        illisible = self.u.tmp / "casse.json"
        illisible.write_text("{\"nodes\": [{\"label\": \"sans id\"}]}")
        self.assertEqual(self.decider("build", str(illisible)).json["status"], "unknown")

    def test_reutiliser_reste_permis_sans_graphe(self) -> None:
        r = self.decider("reuse", str(self.u.tmp / "absent.json"))
        self.assertEqual(r.rc, 0, r)

    def test_graphe_lisible_build_permis_et_trace(self) -> None:
        r = self.decider("build", str(self.u.graphe))
        self.assertEqual(r.rc, 0, r)
        f = json.loads(self.fiche.read_text())
        self.assertEqual(f["decision"]["choice"], "build")
        self.assertEqual(f["decision"]["searchGraphSha256"], sha(self.u.graphe.read_bytes()))


if __name__ == "__main__":
    unittest.main()
