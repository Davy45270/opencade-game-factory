"""Oracles des lignes E179 et E100 de la matrice game-factory (HL-525), écrits AVANT le code.

- E179 (BB-001, découverte, point 5) : conserver un graphe `brique → spécifications → dépôts consommateurs → tests →
  SBOM → releases`. `bbctl discover` relève les releases (tags atteignables depuis le commit lu) de chaque dépôt ;
  `bbctl index` écrit les arêtes tested-by, in-sbom et released-as dans dependency-graph.json.
- E100 (objectif P0 n° 3) : relier exigences, composants, code, tests, SBOM et releases — `bbctl trace <BB>` rend la
  chaîne complète d'une brique, exigences REG-003 de ses specs comprises.
"""
from __future__ import annotations

import json

from .test_bbctl_discover import Base as Decouverte, git


class Base(Decouverte):
    def setUp(self) -> None:
        super().setUp()
        d = self.depot("mono", {"src/engines/combat/attaque.test.ts": "import { attaque } from './index'\n"})
        git(d, "tag", "v1.0.0")
        self.depot("mono", {"src/games/gamma/autre.ts": "export const x = 2\n"})   # commit après le tag
        git(d, "tag", "brouillon", "HEAD~1")                                       # tag sur le même commit que v1.0.0
        self.sources.write_text(json.dumps({"schemaVersion": 1, "excluded": [], "sources": [
            {"name": "mono"}, {"name": "jeu-b"}]}))
        reg = self.u.usine / "specs" / "registry"
        reg.mkdir(parents=True, exist_ok=True)
        (reg / "SPEC-MONO.json").write_text(json.dumps({"id": "SPEC-MONO", "project": "mono", "requirements": [
            {"id": "REQ-MONO-E001", "matrixId": "E001", "statement": "Le joueur attaque.", "matrixStatus": "faite"}]}))
        for args in (("discover", "--repos", "authorized", "--sources", str(self.sources), "--clones",
                      str(self.clones)), ("link-specs",), ("index", "--out", str(self.u.tmp / "gen"))):
            r = self.u.bbctl(*args, "--json")
            self.assertEqual(r.rc, 0, r)
        (self.combat,) = [b for b in self.catalogue().values() if b["name"] == "combat"]

    def graphe(self) -> list[dict]:
        return json.loads((self.u.tmp / "gen" / "dependency-graph.json").read_text())["edges"]


class E179GrapheJusquAuxReleases(Base):
    def test_brique_specs_consommateurs_tests_sbom_releases(self) -> None:
        i = self.combat["id"]
        e = [{k: x[k] for k in ("from", "to", "type")} for x in self.graphe()]
        for attendu in ({"from": i, "to": "SPEC-MONO", "type": "specified-by"},
                        {"from": i, "to": "mono/alpha", "type": "used-by"},
                        {"from": i, "to": "test:mono/src/engines/combat/attaque.test.ts", "type": "tested-by"},
                        {"from": i, "to": f"sbom:{i}", "type": "in-sbom"},
                        {"from": "mono", "to": "release:mono@v1.0.0", "type": "released-as"},
                        {"from": "mono", "to": "release:mono@brouillon", "type": "released-as"}):
            self.assertIn(attendu, e)
        self.assertNotIn("release:jeu-b", json.dumps(e))                             # jeu-b sans tag : aucune release

    def test_releases_relevees_par_discover(self) -> None:
        etat = json.loads((self.u.usine / "blocks" / "discovery.json").read_text())
        self.assertEqual([r["tag"] for r in etat["mono"]["releases"]], ["brouillon", "v1.0.0"])
        self.assertRegex(etat["mono"]["releases"][0]["commitSha"], r"^[0-9a-f]{40}$")
        self.assertEqual(etat["jeu-b"]["releases"], [])


class E100TraceExigencesJusquAuxReleases(Base):
    def test_trace_complete(self) -> None:
        r = self.u.bbctl("trace", self.combat["id"], "--json")
        self.assertEqual(r.rc, 0, r)
        t = r.json
        self.assertEqual(t["requirements"], ["REQ-MONO-E001"])
        self.assertEqual(t["specs"], ["SPEC-MONO"])
        self.assertEqual(t["code"], {"repo": "mono", "path": "src/engines/combat", "commitSha": self.combat["origin"]["commitSha"]})
        self.assertEqual(t["tests"], ["mono/src/engines/combat/attaque.test.ts"])
        self.assertEqual(t["sbom"], {"bomRef": self.combat["id"]})
        self.assertEqual(sorted(t["consumers"]), ["mono/alpha", "mono/beta"])
        self.assertEqual([x["release"] for x in t["releases"]], ["mono@brouillon", "mono@v1.0.0"])
        self.assertEqual(t["missing"], [])

    def test_maillon_manquant_dit(self) -> None:
        (save,) = [b for b in self.catalogue().values() if b["name"] == "save"]
        t = self.u.bbctl("trace", save["id"], "--json").json
        self.assertIn("tests", t["missing"])                                     # jamais un test inventé
        self.assertEqual(self.u.bbctl("trace", "BB-ABSENT-001", "--json").rc, 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
