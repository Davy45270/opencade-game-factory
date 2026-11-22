"""Oracles ligne par ligne de la matrice game-factory (HL-525), ARCH-001, écrits AVANT le code.

- E065 (ARCH-10, « GOV gates et dérogations : refus/exception auditables ») : une dérogation BB-001
  (`blocks/derogations.json`) porte une ÉCHÉANCE `expire` (AAAA-MM-JJ). Sans échéance, échéance passée ou illisible :
  la dérogation ne couvre rien, et le refus est DIT (`refusedDerogations`, motif) et journalisé. Même règle dans le
  fichier exporté vers la CI d'un jeu (`briques_du_jeu`) et dans `reutilisation.mjs` (échéance relue le jour de la CI).
- E003 (« ne créer qu'après avoir démontré que la capacité n'existe pas ou que l'étendre ne suffit pas ») : `bbctl
  decide --choice build` relève les briques existantes de même nom et même écosystème. S'il y en a, la décision exige
  `--why-not-extend` (pourquoi étendre l'existant ne suffit pas) ; elle consigne `alternatives` (vide = rien
  d'existant, la recherche est prouvée par `searchGraphSha256`).
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from ._outil import RACINE, Usine, fiche

FUTUR, PASSE = "2099-12-31", "2020-01-01"
NODE = shutil.which("node")
SCRIPT = RACINE / "ci" / "scripts" / "reutilisation.mjs"


def git(d: pathlib.Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


class Depot(unittest.TestCase):
    """Un jeu qui ajoute deux briques : le module local `physique` et la dépendance howler."""

    def setUp(self) -> None:
        self.u = Usine()
        self.depot = self.u.tmp / "jeu"
        self.ecrire({"package.json": json.dumps({"dependencies": {"phaser": "3.80.1"}}),
                     "src/engines/combat/index.ts": "export const a = 1\n"})
        git(self.depot, "init", "-q", "-b", "main")
        self.base = self.commit()
        self.ecrire({"package.json": json.dumps({"dependencies": {"phaser": "3.80.1", "howler": "2.2.4"}}),
                     "src/engines/physique/index.ts": "export const g = 9.81\n"})
        self.tete = self.commit()

    def tearDown(self) -> None:
        self.u.nettoyer()

    def ecrire(self, fichiers: dict[str, str]) -> None:
        for chemin, texte in fichiers.items():
            (self.depot / chemin).parent.mkdir(parents=True, exist_ok=True)
            (self.depot / chemin).write_text(texte)

    def commit(self) -> str:
        git(self.depot, "add", "-A")
        git(self.depot, "commit", "-q", "-m", "c")
        return git(self.depot, "rev-parse", "HEAD")

    def derogations(self, entrees: dict) -> None:
        (self.u.usine / "blocks" / "derogations.json").write_text(json.dumps(entrees))

    def gate(self):
        return self.u.bbctl("gate", "--repo", str(self.depot), "--base", self.base, "--head", self.tete, "--json")


class E065DerogationsAEcheance(Depot):
    PHYS, HOWLER = "local:jeu:src/engines/physique", "npm:howler@unresolved"

    def test_derogation_a_echeance_future_couvre(self) -> None:
        self.derogations({k: {"ref": "HL-525 7-3000", "reason": "prototype", "expire": FUTUR}
                          for k in (self.PHYS, self.HOWLER)})
        r = self.gate()
        self.assertEqual((r.rc, r.json["uncovered"]), (0, []), r)
        self.assertEqual([d["expire"] for d in r.json["derogations"]], [FUTUR, FUTUR])

    def test_sans_echeance_ou_echue_refusee_et_dite(self) -> None:
        self.derogations({self.PHYS: {"ref": "HL-525 7-3000", "reason": "prototype"},
                          self.HOWLER: {"ref": "HL-525 7-3001", "reason": "son", "expire": PASSE}})
        r = self.gate()
        self.assertEqual(r.rc, 1, r)
        self.assertEqual(r.json["uncovered"], [self.PHYS, self.HOWLER])
        refus = {d["key"]: d for d in r.json["refusedDerogations"]}
        self.assertEqual(set(refus), {self.PHYS, self.HOWLER})
        self.assertEqual(refus[self.PHYS]["motif"], "sans-echeance")
        self.assertEqual((refus[self.HOWLER]["motif"], refus[self.HOWLER]["expire"]), ("echue", PASSE))
        journal = [json.loads(l) for l in (self.u.usine / "blocks" / "journal.jsonl").read_text().splitlines()]
        self.assertEqual(sorted(journal[-1]["refusedDerogations"]), [self.PHYS, self.HOWLER])

    def test_echeance_illisible_refusee(self) -> None:
        self.derogations({self.PHYS: {"ref": "HL-525 7-3000", "reason": "prototype", "expire": "bientôt"},
                          self.HOWLER: {"ref": "HL-525 7-3000", "reason": "son", "expire": FUTUR}})
        r = self.gate()
        self.assertEqual((r.rc, r.json["uncovered"]), (1, [self.PHYS]), r)
        self.assertEqual(r.json["refusedDerogations"][0]["motif"], "echeance-illisible")

    def test_export_vers_la_ci_du_jeu_sans_derogation_echue(self) -> None:
        sys.path.insert(0, str(RACINE / "ci"))
        import woodpecker  # noqa: E402
        self.derogations({self.PHYS: {"ref": "HL-525 7-3000", "reason": "prototype", "expire": FUTUR},
                          self.HOWLER: {"ref": "HL-525 7-3001", "reason": "son", "expire": PASSE},
                          "npm:ms@2.1.3": {"ref": "HL-525 7-3002", "reason": "x"}})
        v = woodpecker.briques_du_jeu(self.u.usine, "jeu")
        self.assertEqual(v["derogations"], {self.PHYS: {"ref": "HL-525 7-3000", "expire": FUTUR}})


@unittest.skipUnless(NODE, "node absent")
class E065EcheanceRelueParLaCiDuJeu(Depot):
    """L'échéance est relue le jour de la CI : un briques.json généré avant l'échéance ne couvre plus rien après."""

    def lancer(self, derogations: dict) -> dict:
        (self.depot / ".woodpecker/usine").mkdir(parents=True, exist_ok=True)
        (self.depot / ".woodpecker/usine/briques.json").write_text(json.dumps(
            {"repo": "jeu", "decided": ["npm:howler@unresolved"], "derogations": derogations}))
        r = subprocess.run([NODE, str(SCRIPT), "--bloquant", "--base", self.base], cwd=self.depot, capture_output=True,
                           text=True, timeout=60)
        rap = json.loads((self.depot / "reutilisation-rapport.json").read_text())
        rap["rc"] = r.returncode
        return rap

    def test_echeance_future_couvre(self) -> None:
        rap = self.lancer({"local:jeu:src/engines/physique": {"ref": "HL-525 7-3000", "expire": FUTUR}})
        self.assertEqual((rap["rc"], rap["status"], rap["derogations"]), (0, "ok", ["local:jeu:src/engines/physique"]))

    def test_echue_ou_sans_echeance_fait_echouer(self) -> None:
        for entree, motif in (({"ref": "HL-525 7-3000", "expire": PASSE}, "echue"), ("HL-525 7-3000", "sans-echeance")):
            rap = self.lancer({"local:jeu:src/engines/physique": entree})
            self.assertEqual((rap["rc"], rap["uncovered"]), (1, ["local:jeu:src/engines/physique"]), rap)
            self.assertEqual(rap["refusedDerogations"], [{"key": "local:jeu:src/engines/physique", "motif": motif}])


class E003BuildApresDemonstration(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()
        d = self.u.usine / "blocks" / "evaluations"
        d.mkdir(parents=True)
        from .test_bbctl_acceptation import evaluation
        for cand in ("BB-SIX-PATHFINDING-001", "BB-CAP-PATHFINDING-001", "BB-ECHECS-HORLOGE-001"):
            (d / f"{cand}.json").write_text(json.dumps(evaluation(candidate=cand), ensure_ascii=False))
        self.u.poser(fiche("BB-CAP-PATHFINDING-001", usedBy=["capsule-panic"],
                           origin={"repositoryUrl": None, "repo": "capsule-panic", "path": "src/game/grid-path.ts",
                                   "licenseSpdx": "MIT", "commitSha": None}))
        self.u.poser(fiche("BB-ECHECS-HORLOGE-001", name="Horloge de partie", usedBy=["echecs"]))

    def tearDown(self) -> None:
        self.u.nettoyer()

    def decide(self, cand: str, *extra: str):
        return self.u.bbctl("decide", "--candidate", cand, "--choice", "build", "--reason", "besoin propre", *extra,
                            "--json")

    def lire(self, cand: str) -> dict:
        return json.loads((self.u.usine / "blocks" / "catalog" / f"{cand}.json").read_text())

    def test_build_avec_existant_semblable_exige_pourquoi_ne_pas_etendre(self) -> None:
        r = self.decide("BB-CAP-PATHFINDING-001")
        self.assertEqual(r.rc, 3, r)
        self.assertIn("BB-SIX-PATHFINDING-001", r.json["error"])
        self.assertEqual(self.lire("BB-CAP-PATHFINDING-001")["decision"]["status"], "pending")   # rien n'est écrit
        r = self.decide("BB-CAP-PATHFINDING-001", "--why-not-extend", "grille hexagonale, l'existante est carrée")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(self.lire("BB-CAP-PATHFINDING-001")["decision"]["alternatives"],
                         [{"block": "BB-SIX-PATHFINDING-001", "whyNotExtend": "grille hexagonale, l'existante est carrée"}])

    def test_build_sans_existant_consigne_aucune_alternative(self) -> None:
        r = self.decide("BB-ECHECS-HORLOGE-001")
        self.assertEqual(r.rc, 0, r)
        d = self.lire("BB-ECHECS-HORLOGE-001")["decision"]
        self.assertEqual(d["alternatives"], [])
        self.assertRegex(d["searchGraphSha256"], r"^[0-9a-f]{64}$")

    def test_why_not_extend_hors_build_refuse(self) -> None:
        r = self.u.bbctl("decide", "--candidate", "BB-ECHECS-HORLOGE-001", "--choice", "defer", "--reason", "plus tard",
                         "--why-not-extend", "x", "--json")
        self.assertEqual(r.rc, 2, r)


if __name__ == "__main__":
    unittest.main()
