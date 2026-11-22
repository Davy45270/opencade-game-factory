"""Oracles BB-001 lot 3 (HL-525), écrits AVANT le code : adoption tracée, écritures sûres et auditées, contrôle
« reuse before build », événements OPS-001.

- `bbctl adopt --candidate <BB> --used-by <projet> --version <v> --pr <url> --tests <réf> [--sbom <réf>]` (§ 11) :
  exige une décision reuse/adapt/wrap/fork et un TCO complet (§ 6) ; sans SBOM l'adoption est REFUSÉE (T11, code 3) ;
  sinon statut `adopted`, verrou de version, SBOM, usedBy et trace de l'adoption dans la fiche.
- `--expect <sha256 de la fiche>` sur decide et adopt : une fiche modifiée entre-temps n'est jamais écrasée (T13,
  code 5). Toute écriture va au journal `blocks/journal.jsonl` (empreintes avant/après).
- `bbctl gate --repo <dépôt> --base <réf> [--head <réf>]` (§ 5, BB-08) : chaque brique NOUVELLE entre base et tête
  (module local, dépendance directe) doit avoir une décision enregistrée au catalogue ou une dérogation approuvée
  (`blocks/derogations.json`, référence HL-n 7-n) ; sinon code 1 (T08). Une dérogation passe, et c'est écrit (T09).
- Événements FactoryEvent (`bb.decided`, `bb.adopted`, `bb.blocked`) vers la Tour, même dépôt opt-in que specctl
  (TOWER_DIR / TOWER_TRACE_ID), corrélés par trace et par `buildingBlockRefs` (T14).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import unittest

from ._outil import Usine, fiche
from .test_bbctl_acceptation import evaluation

BB = "BB-SIX-PATHFINDING-001"
TCO = {k: {"estimation": "2 j", "hypothese": f"hypothèse {k}"} for k in
       ("integration", "adaptation", "maintenance", "misesAJour", "tests", "detteSecurite", "sortie")}
CHAMPS = {"agentId", "buildingBlockRefs", "commitSha", "eventId", "eventType", "evidence", "executionId", "metadata",
          "occurredAt", "parentExecutionId", "portfolioId", "projectId", "pullRequestId", "receivedAt", "runId",
          "schemaVersion", "source", "specRefs", "status", "taskId", "traceId", "workflowId", "workflowVersion"}


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()
        self.tour = self.u.tmp / "tour"
        self.tour.mkdir()

    def tearDown(self) -> None:
        os.environ.pop("TOWER_DIR", None)
        os.environ.pop("TOWER_TRACE_ID", None)
        self.u.nettoyer()

    def poser_eval(self, cand: str = BB, **change) -> None:
        d = self.u.usine / "blocks" / "evaluations"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{cand}.json").write_text(json.dumps(evaluation(candidate=cand, **change), ensure_ascii=False))

    def chemin(self, cand: str = BB) -> pathlib.Path:
        return self.u.usine / "blocks" / "catalog" / f"{cand}.json"

    def lire(self, cand: str = BB) -> dict:
        return json.loads(self.chemin(cand).read_text())

    def empreinte(self, cand: str = BB) -> str:
        return hashlib.sha256(self.chemin(cand).read_bytes()).hexdigest()

    def decider(self, *extra: str, cand: str = BB, choix: str = "reuse"):
        return self.u.bbctl("decide", "--candidate", cand, "--choice", choix, "--reason", "même grille", *extra, "--json")

    def adopter(self, *extra: str):
        return self.u.bbctl("adopt", "--candidate", BB, "--used-by", "capsule-panic", "--version", "1.2.0",
                            "--pr", "https://forgejo.example/pr/1", "--tests", "tests/path.test.ts", *extra, "--json")

    def journal(self) -> list[dict]:
        f = self.u.usine / "blocks" / "journal.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.is_file() else []


class Adoption(Base):
    def setUp(self) -> None:
        super().setUp()
        self.poser_eval(tco=TCO)
        self.assertEqual(self.decider().rc, 0)

    def test_T11_sans_sbom_adoption_refusee(self) -> None:
        avant = self.empreinte()
        r = self.adopter()
        self.assertEqual(r.rc, 3, r)
        self.assertEqual(r.json["status"], "safety-refusal")
        self.assertIn("SBOM", r.json["error"])
        self.assertEqual(self.empreinte(), avant)

    def test_adoption_complete_et_tracee(self) -> None:
        r = self.adopter("--sbom", "capsule-panic@abc123:sbom.json")
        self.assertEqual(r.rc, 0, r)
        f = self.lire()
        self.assertEqual((f["quality"]["status"], f["quality"]["sbomRef"], f["origin"]["version"]),
                         ("adopted", "capsule-panic@abc123:sbom.json", "1.2.0"))
        self.assertIn("capsule-panic", f["usedBy"])
        self.assertEqual(f["adoptions"][0]["pr"], "https://forgejo.example/pr/1")
        self.assertEqual(f["adoptions"][0]["tests"], "tests/path.test.ts")
        self.assertEqual(self.u.bbctl("validate", "--all", "--json").rc, 0)

    def test_adoption_sans_decision_de_reutilisation_refusee(self) -> None:
        self.assertEqual(self.decider(choix="build").rc, 0)
        self.assertEqual(self.adopter("--sbom", "s").rc, 3)

    def test_tco_incomplet_refuse(self) -> None:
        self.poser_eval(tco={k: v for k, v in TCO.items() if k != "sortie"})
        r = self.adopter("--sbom", "s")
        self.assertEqual(r.rc, 1, r)
        self.assertIn("sortie", r.json["error"])

    def test_T13_fiche_modifiee_entre_temps_jamais_ecrasee(self) -> None:
        vu = self.empreinte()
        f = self.lire()
        f["capabilities"] = ["grid-pathfinding", "diagonales"]                  # un autre agent écrit
        self.chemin().write_text(json.dumps(f, ensure_ascii=False, indent=1))
        apres = self.empreinte()
        r = self.decider("--expect", vu, choix="adapt")
        self.assertEqual(r.rc, 5, r)
        self.assertEqual(self.empreinte(), apres)
        self.assertEqual(self.decider("--expect", apres, choix="adapt").rc, 0)

    def test_journal_d_audit(self) -> None:
        self.adopter("--sbom", "s")
        lignes = self.journal()
        self.assertEqual([(l["command"], l["blockId"]) for l in lignes], [("decide", BB), ("adopt", BB)])
        self.assertTrue(all(len(l["sha256After"]) == 64 and l["sha256Before"] != l["sha256After"] for l in lignes))

    def test_T14_decisions_correlables_dans_la_tour(self) -> None:
        os.environ["TOWER_DIR"] = str(self.tour)
        os.environ["TOWER_TRACE_ID"] = "bb001-T14"
        self.decider(choix="adapt")
        self.adopter("--sbom", "s")
        evs = [json.loads(l) for l in (self.tour / "inbox.jsonl").read_text().splitlines()]
        self.assertEqual([e["eventType"] for e in evs], ["bb.decided", "bb.adopted"])
        for e in evs:
            self.assertLessEqual(set(e), CHAMPS, e)
            self.assertEqual((e["traceId"], e["buildingBlockRefs"], e["source"]), ("bb001-T14", [BB], "bbctl"))

    def test_decision_rattachee_au_depot_de_la_brique(self) -> None:
        # Tranche ARCH-12 : usedBy[0] valait « six-de-chaque/apps/web » sur les fiches découvertes ; la Tour lisait un
        # second projet dans la trace et la déclarait incohérente. Le projet est le dépôt d'origine de la brique.
        f = self.lire()
        f["usedBy"] = ["six-de-chaque/apps/web", "six-de-chaque/tests/e2e"]
        self.chemin().write_text(json.dumps(f, ensure_ascii=False, indent=1))
        os.environ["TOWER_DIR"] = str(self.tour)
        self.decider(choix="adapt")
        (e,) = [json.loads(l) for l in (self.tour / "inbox.jsonl").read_text().splitlines()]
        self.assertEqual((e["eventType"], e["projectId"]), ("bb.decided", "six-de-chaque"))

    def test_BB10_evenement_relie_aux_specifications(self) -> None:
        f = self.lire()
        f["specIds"] = ["SPEC-SIX-DE-CHAQUE"]                                   # lien REG-003 porté par la fiche
        self.chemin().write_text(json.dumps(f, ensure_ascii=False, indent=1))
        os.environ["TOWER_DIR"] = str(self.tour)
        self.adopter("--sbom", "s")
        (e,) = [json.loads(l) for l in (self.tour / "inbox.jsonl").read_text().splitlines()]
        self.assertEqual((e["specRefs"], e["buildingBlockRefs"]), (["SPEC-SIX-DE-CHAQUE"], [BB]))


def git(d: pathlib.Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


class Gate(Base):
    def setUp(self) -> None:
        super().setUp()
        self.depot = self.u.tmp / "jeu"
        self.ecrire({"package.json": json.dumps({"dependencies": {"phaser": "3.80.1"}}),
                     "src/engines/combat/index.ts": "export const a = 1\n"})
        git(self.depot, "init", "-q", "-b", "main")
        self.base = self.commit()
        self.ecrire({"package.json": json.dumps({"dependencies": {"phaser": "3.80.1", "howler": "2.2.4"}}),
                     "src/engines/physique/index.ts": "export const g = 9.81\n"})
        self.tete = self.commit()

    def ecrire(self, fichiers: dict[str, str]) -> None:
        for chemin, texte in fichiers.items():
            (self.depot / chemin).parent.mkdir(parents=True, exist_ok=True)
            (self.depot / chemin).write_text(texte)

    def commit(self) -> str:
        git(self.depot, "add", "-A")
        git(self.depot, "commit", "-q", "-m", "c")
        return git(self.depot, "rev-parse", "HEAD")

    def gate(self):
        return self.u.bbctl("gate", "--repo", str(self.depot), "--base", self.base, "--head", self.tete, "--json")

    def test_T08_creation_sans_recherche_echoue(self) -> None:
        r = self.gate()
        self.assertEqual(r.rc, 1, r)
        self.assertEqual(r.json["uncovered"], ["local:jeu:src/engines/physique", "npm:howler@unresolved"])

    def test_decision_enregistree_couvre(self) -> None:
        sources = self.u.tmp / "sources.json"
        sources.write_text(json.dumps({"sources": [{"name": "jeu", "copies": [{"provider": "local", "path": str(self.depot)}]}]}))
        self.assertEqual(self.u.bbctl("discover", "--repos", "authorized", "--sources", str(sources), "--json").rc, 0)
        ids = json.loads((self.u.usine / "blocks" / "ids.json").read_text())
        for cle in ("local:jeu:src/engines/physique", "npm:howler@unresolved"):
            o = self.lire(ids[cle])["origin"]
            o["licenseSpdx"] = "MIT"
            f = self.lire(ids[cle]) | {"origin": o}
            self.chemin(ids[cle]).write_text(json.dumps(f))
            self.poser_eval(ids[cle])
            self.assertEqual(self.decider(cand=ids[cle], choix="build").rc, 0)
        r = self.gate()
        self.assertEqual((r.rc, r.json["uncovered"]), (0, []), r)

    def test_T09_derogation_approuvee_passe_avec_audit(self) -> None:
        d = self.u.usine / "blocks" / "derogations.json"
        d.write_text(json.dumps({"local:jeu:src/engines/physique": {"ref": "HL-525 7-3000", "reason": "prototype"},
                                 "npm:howler@unresolved": {"ref": "pas une référence", "reason": "x"}}))
        r = self.gate()
        self.assertEqual(r.rc, 1, r)                                             # référence invalide : pas de dérogation
        self.assertEqual(r.json["uncovered"], ["npm:howler@unresolved"])
        d.write_text(json.dumps({k: {"ref": "HL-525 7-3000", "reason": "prototype"}
                                 for k in ("local:jeu:src/engines/physique", "npm:howler@unresolved")}))
        r = self.gate()
        self.assertEqual(r.rc, 0, r)
        self.assertEqual([x["key"] for x in r.json["derogations"]], ["local:jeu:src/engines/physique", "npm:howler@unresolved"])
        self.assertEqual(self.journal()[-1]["command"], "gate")

    def test_T14_blocage_emis(self) -> None:
        os.environ["TOWER_DIR"] = str(self.tour)
        os.environ["TOWER_TRACE_ID"] = "bb001-T08"
        self.gate()
        (e,) = [json.loads(l) for l in (self.tour / "inbox.jsonl").read_text().splitlines()]
        self.assertEqual((e["eventType"], e["status"]), ("bb.blocked", "blocked"))

    def test_base_inconnue(self) -> None:
        r = self.u.bbctl("gate", "--repo", str(self.depot), "--base", "inexistante", "--json")
        self.assertEqual(r.rc, 2, r)


if __name__ == "__main__":
    unittest.main()
