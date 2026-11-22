"""Oracle de la ligne E120 de la matrice game-factory (HL-525), REG-003, migration initiale étape 5 : « Construire le
graphe initial specs → jeux → building blocks → code → tests », prouvé par le rapport de migration
`specctl import --dry-run --report`. Écrit AVANT le code. Les briques sont lues dans le catalogue BB-001 de l'usine
(blocks/catalog) ; un maillon absent est dit (`missing`), jamais inventé."""
from __future__ import annotations

import json
import unittest

from .._outil import Docs


def brique(id_, spec, repo, path, tests):
    return {"id": id_, "name": id_.lower(), "kind": "game-local-module", "specIds": [spec], "usedBy": [repo],
            "origin": {"repo": repo, "path": path, "commitSha": "a" * 40, "licenseSpdx": "MIT", "repositoryUrl": None},
            "analysis": {"tests": tests}}


class E120GrapheInitial(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()
        cat = self.d.usine / "blocks" / "catalog"
        cat.mkdir(parents=True)
        for b in (brique("BB-JEU-A-COMBAT-001", "SPEC-JEU-A", "jeu-a", "src/engines/combat", ["src/engines/combat/c.test.ts"]),
                  brique("BB-JEU-A-SAVE-001", "SPEC-JEU-A", "jeu-a", "src/engines/save", [])):
            (cat / f"{b['id']}.json").write_text(json.dumps(b))

    def tearDown(self) -> None:
        self.d.nettoyer()

    def test_specs_jeux_briques_code_tests(self) -> None:
        r = self.d.specctl("import", "--from", str(self.d.docs), "--dry-run", "--report", "--json")
        self.assertEqual(r.rc, 0, r)
        g = {x["specId"]: x for x in r.json["report"]["graph"]}
        a = g["SPEC-JEU-A"]
        self.assertEqual(a["project"], "jeu-a")
        self.assertEqual([(b["block"], b["code"]["path"], b["tests"]) for b in a["blocks"]],
                         [("BB-JEU-A-COMBAT-001", "src/engines/combat", ["src/engines/combat/c.test.ts"]),
                          ("BB-JEU-A-SAVE-001", "src/engines/save", [])])
        self.assertEqual(a["missing"], ["tests:BB-JEU-A-SAVE-001"])
        self.assertEqual((g["SPEC-JEU-B"]["blocks"], g["SPEC-JEU-B"]["missing"]), ([], ["blocks"]))
        self.assertEqual(r.json["report"]["graphSummary"], {"specs": 2, "withBlocks": 1, "blocks": 2, "tested": 1})
        self.assertFalse((self.d.usine / "specs" / "registry").exists())      # dry-run : rien d'écrit


if __name__ == "__main__":
    unittest.main()
