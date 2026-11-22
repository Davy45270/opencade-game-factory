"""Oracles ligne par ligne de la matrice game-factory (HL-525) pour BB-001, écrits AVANT le code : une classe par
ligne `E nnn`, critère rejoué de bout en bout par `bbctl`. Contrat d'appel : tests/blocks/_outil.py.

- E206 et E224 (BB-11) : les manifestes JSON du catalogue font foi ; l'index SQLite FTS5 et le graphe de dépendances
  sont GÉNÉRÉS (`bbctl index --out`), reconstructibles à l'identique, et `--check` voit un index perdu ou périmé.
- E183 : statut de validation et statut de consommation séparés (`bbctl inspect`), et incohérence refusée.
- E184 : chaque étape de « reuse before build » (specctl resolve, recherche interne, évaluation, décision) laisse
  sa trace dans un reçu commun (`--receipt`).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import unittest

from specs.tests._outil import Docs

from ._outil import Usine, fiche, sha


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()
        self.u.poser(fiche("BB-SIX-SAUVEGARDE-001", name="Sauvegarde locale", capabilities=["save-slots"],
                           specIds=["SPEC-SIX-DE-CHAQUE"], usedBy=[],
                           quality={"status": "approved", "sbomRef": None, "securityReportRef": None},
                           origin={"repositoryUrl": None, "repo": "six-de-chaque", "path": "packages/save",
                                   "licenseSpdx": "MIT", "commitSha": None}))

    def tearDown(self) -> None:
        self.u.nettoyer()

    def ok(self, *args: str) -> dict:
        r = self.u.bbctl(*args, "--json")
        self.assertEqual(r.rc, 0, r)
        return r.json


class E206E224IndexFts5EtGrapheGeneres(Base):
    def test_index_fts5_et_graphe_reconstructibles(self) -> None:
        out = self.u.tmp / "gen"
        self.ok("index", "--out", str(out))
        base = out / "blocks-fts.sqlite"
        with sqlite3.connect(base) as c:                                       # un vrai index FTS5
            sql = c.execute("select sql from sqlite_master where name = 'blocks'").fetchone()[0]
        self.assertIn("fts5", sql.casefold())
        trouve = self.ok("search", "--scope", "catalog", "--index", str(out), "--query", "sauvegarde")
        self.assertEqual([x["block"] for x in trouve["results"]], ["BB-SIX-SAUVEGARDE-001"])
        graphe = json.loads((out / "dependency-graph.json").read_text())
        self.assertIn({"from": "BB-SIX-SAUVEGARDE-001", "to": "SPEC-SIX-DE-CHAQUE", "type": "specified-by"},
                      graphe["edges"])
        self.assertIn({"from": "BB-SIX-PATHFINDING-001", "to": "six-de-chaque", "type": "used-by"}, graphe["edges"])
        avant = (out / "dependency-graph.json").read_bytes()
        shutil.rmtree(out)                                                     # index perdus
        self.assertEqual(self.u.bbctl("index", "--out", str(out), "--check", "--json").rc, 1)
        self.ok("index", "--out", str(out))
        self.assertEqual((out / "dependency-graph.json").read_bytes(), avant)
        self.assertEqual(self.ok("search", "--scope", "catalog", "--index", str(out), "--query", "sauvegarde"), trouve)
        self.assertEqual(self.ok("index", "--out", str(out), "--check")["status"], "ok")

    def test_index_perime_vu_par_check(self) -> None:
        out = self.u.tmp / "gen"
        self.ok("index", "--out", str(out))
        self.u.poser(fiche("BB-SIX-AUDIO-001", name="Audio", usedBy=["six-de-chaque"]))  # le catalogue a bougé
        r = self.u.bbctl("index", "--out", str(out), "--check", "--json")
        self.assertEqual(r.rc, 1, r)

    def test_recherche_sans_index_source_indisponible(self) -> None:
        r = self.u.bbctl("search", "--scope", "catalog", "--index", str(self.u.tmp / "absent"), "--query", "x", "--json")
        self.assertEqual(r.rc, 4, r)


class E183ValidationSepareeDeConsommation(Base):
    def test_deux_statuts_orthogonaux(self) -> None:
        approuvee = self.ok("inspect", "BB-SIX-SAUVEGARDE-001")["status"]
        self.assertEqual(approuvee, {"validation": "approved", "consumption": "unused"})
        self.u.poser(fiche("BB-SIX-DES-001", usedBy=["six-de-chaque/apps/web"],
                           quality={"status": "discovered", "sbomRef": None, "securityReportRef": None}))
        self.assertEqual(self.ok("inspect", "BB-SIX-DES-001")["status"],
                         {"validation": "discovered", "consumption": "consumed"})   # consommée sans être validée
        self.assertEqual(self.ok("inspect", "BB-SIX-PATHFINDING-001")["status"],
                         {"validation": "approved", "consumption": "consumed"})    # adopted = approuvée ET consommée

    def test_adoptee_sans_consommateur_refusee(self) -> None:
        self.assertEqual(self.ok("validate", "--all")["count"], 2)
        self.u.poser(fiche("BB-SIX-ORPHELINE-001", usedBy=[]))                  # adopted, mais personne ne l'utilise
        r = self.u.bbctl("validate", "--all", "--json")
        self.assertEqual(r.rc, 1, r)
        self.assertIn("BB-SIX-ORPHELINE-001", r.stdout)


class E184RecuCommunDesEtapes(Base):
    def setUp(self) -> None:
        super().setUp()
        d = Docs()
        try:
            d.archive("six-de-chaque", {"Six_v1.0.md.txt": "# Six\n\nLe joueur pose six pions.\n"})
            d.commit("six")
            self.assertEqual(d.specctl("import", "--from", str(d.docs), "--json").rc, 0)
            shutil.copytree(d.usine / "specs", self.u.usine / "specs")
        finally:
            d.nettoyer()
        (self.u.usine / "blocks" / "evaluations").mkdir()
        (self.u.usine / "blocks" / "evaluations" / "BB-SIX-PATHFINDING-001.json").write_text(json.dumps(
            {"candidate": "BB-SIX-PATHFINDING-001", "date": "2026-11-22",
             "gates": {"security": {"critical": 0, "accepted": False}, "provenance": "known", "technical": "ok"},
             "scores": {k: {"score": 4, "preuve": f"mesure {k}"} for k in
                        ("adequation", "integration", "maintenance", "licence", "securite", "cout")}}))

    def test_resolve_recherche_evaluation_decision_dans_un_recu(self) -> None:
        recu = self.u.tmp / "recu.json"
        self.ok("search", "--scope", "internal", "--query", "path", "--project", "six-de-chaque", "--receipt", str(recu))
        r = self.u.bbctl("evaluate", "--candidate", "BB-SIX-PATHFINDING-001", "--receipt", str(recu), "--json")
        self.assertEqual(r.rc, 0, r)
        self.ok("decide", "--candidate", "BB-SIX-PATHFINDING-001", "--choice", "reuse", "--reason", "déjà au catalogue",
                "--receipt", str(recu))
        v = json.loads(recu.read_text())
        etapes = [e["step"] for e in v["steps"]]
        self.assertEqual(etapes, ["specctl resolve", "bbctl search --scope internal", "bbctl evaluate", "bbctl decide"])
        resolution = v["steps"][0]
        self.assertEqual((resolution["project"], resolution["status"]), ("six-de-chaque", "ok"))
        self.assertEqual([(s["specId"], s["version"]) for s in resolution["specs"]], [("SPEC-SIX-DE-CHAQUE", "1.0.0")])
        self.assertRegex(resolution["registryDigest"], r"^[0-9a-f]{64}$")
        self.assertEqual(v["steps"][1]["graphSha256"], sha(self.u.graphe.read_bytes()))
        self.assertEqual(v["steps"][3]["choice"], "reuse")
        self.assertTrue(all(e["at"] for e in v["steps"]))

    def test_projet_sans_spec_resolue_trace_dans_le_recu(self) -> None:
        recu = self.u.tmp / "recu.json"
        self.ok("search", "--scope", "internal", "--query", "path", "--project", "inconnu", "--receipt", str(recu))
        etape = json.loads(recu.read_text())["steps"][0]
        self.assertEqual(etape["step"], "specctl resolve")
        self.assertNotEqual(etape["status"], "ok")                             # témoin : jamais une résolution inventée


if __name__ == "__main__":
    unittest.main()
