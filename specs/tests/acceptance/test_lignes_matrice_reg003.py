"""Oracles ligne par ligne de la matrice game-factory (HL-525) pour REG-003 : une classe par ligne `E nnn`, qui
rejoue le CRITÈRE de la ligne tel qu'il est écrit, de bout en bout par la CLI `specctl` (ou la CI de l'usine).

Vus rouges sur 7ddccbb (usine avant PR #16) : les commandes et contrôles n'y existaient pas. Contrat d'appel :
specs/tests/_outil.py (USINE_RACINE temporaire, homelab-docs jetable, jamais le dépôt réel).
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import unittest

from .._outil import RACINE, SPEC_A_V11, SPECCTL, Docs, git

REF = "HL-525 7-2955"


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()
        r = self.d.specctl("import", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 0, r)
        self.reg = self.d.usine / "specs" / "registry"

    def tearDown(self) -> None:
        self.d.nettoyer()

    def ok(self, *args: str) -> dict:
        r = self.d.specctl(*args, "--json")
        self.assertEqual(r.rc, 0, r)
        return r.json

    def jeu(self) -> tuple[pathlib.Path, str]:
        """Dépôt de jeu jetable dont la PR porte la spec résolue aujourd'hui (fichier écrit par le gabarit CI)."""
        depot = self.d.tmp / "jeu-a"
        depot.mkdir()
        git(depot, "init", "-q", "-b", "main")
        f = depot / ".woodpecker" / "usine" / "spec.json"
        f.parent.mkdir(parents=True)
        spec = self.ok("resolve", "--project", "jeu-a")["specs"][0]
        f.write_text(json.dumps({"project": "jeu-a", "specId": spec["specId"], "version": spec["version"], "status": "ok"}))
        git(depot, "add", ".")
        git(depot, "commit", "-q", "-m", "verrou")
        return depot, git(depot, "rev-parse", "HEAD")


class E096AgentsSimultanesEtSpecsPerimees(Base):
    """REG-003 § 1 : agents simultanés sur plusieurs dépôts ; travaux sur spec périmée empêchés."""

    def test_deux_agents_simultanes_puis_pr_sur_spec_perimee_bloquee(self) -> None:
        import os
        env = {**os.environ, "USINE_RACINE": str(self.d.usine)}
        ps = [subprocess.Popen([str(SPECCTL), "import", "--from", str(self.d.docs), "--json"], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
        self.assertTrue(all(p.wait(timeout=120) in (0, 5) for p in ps))
        self.assertEqual(self.d.specctl("validate", "--json").rc, 0)          # aucune écriture perdue ni corrompue
        depot, commit = self.jeu()
        self.assertEqual(self.ok("verify", "--project", "jeu-a", "--commit", commit, "--repo", str(depot))["status"], "ok")
        self.d.archive("jeu-a", {"Jeu_A_v1.1.md.txt": SPEC_A_V11})
        self.d.commit("v1.1")
        self.d.specctl("import", "--from", str(self.d.docs), "--json")           # v1.1 : 5 = arbitrage requis
        self.ok("arbitrer", "--spec", "SPEC-JEU-A", "--version", "1.1.0", "--ref", REF)
        r = self.d.specctl("verify", "--project", "jeu-a", "--commit", commit, "--repo", str(depot), "--json")
        self.assertEqual((r.rc, r.json["status"]), (2, "outdated"), r)       # le travail sur l'ancienne version est bloqué


class E103SourceDeVeriteFederee(Base):
    """§ 2 : une origine canonique éditable par spec, l'archive figée ; pas de duplication éditable."""

    def test_une_origine_editable_et_copie_refusee(self) -> None:
        for s in self.ok("verify")["specs"]:
            self.assertEqual((s["editableOrigin"], s["archive"]["frozen"]), ("usine", True), s)
        f = self.reg / "games" / "SPEC-JEU-A.json"
        v = json.loads(f.read_text())
        v["content"] = (self.d.docs / "specs/jeu-a-sources/Jeu_A_v1.0.md.txt").read_text()
        f.write_text(json.dumps(v, ensure_ascii=False))
        self.assertEqual(self.d.specctl("verify", "--json").rc, 2)            # témoin : copie éditable du texte


class E105IdentifiantsJamaisRecycles(Base):
    """§ 2 : identifiants stables, jamais recyclés (registre d'IDs en ajout seul, contrôlé contre la base)."""

    def test_identifiant_reattribue_ou_retire_refuse(self) -> None:
        git(self.d.usine, "init", "-q", "-b", "main")
        git(self.d.usine, "add", "specs")
        git(self.d.usine, "commit", "-q", "-m", "base")
        self.assertEqual(self.d.specctl("validate", "--base", "HEAD", "--json").rc, 0)
        ids = json.loads((self.reg / "ids.json").read_text())
        self.assertTrue(all(k.startswith(("SPEC-", "REQ-")) for k in ids), ids)
        ids["REQ-JEU-A-E002"] = "SPEC-JEU-B"                                  # recyclage vers une autre spec
        (self.reg / "ids.json").write_text(json.dumps(ids))
        self.assertEqual(self.d.specctl("validate", "--base", "HEAD", "--json").rc, 2)
        del ids["REQ-JEU-A-E002"]                                             # ou retrait
        (self.reg / "ids.json").write_text(json.dumps(ids))
        self.assertEqual(self.d.specctl("validate", "--base", "HEAD", "--json").rc, 2)


class E139JournalProvenanceClassification(Base):
    """§ 9 : journal d'audit, provenance des imports, classification public/privé par document."""

    def test_journal_provenance_et_visibilite(self) -> None:
        journal = [json.loads(l) for l in (self.reg / "journal.jsonl").read_text().splitlines()]
        self.assertEqual(sorted(l["specId"] for l in journal), ["SPEC-JEU-A", "SPEC-JEU-B"])
        for spec in self.d.registre().values():
            self.assertIn(spec["visibility"], ("private", "public"))
            origine = spec["canonical"]["importedFrom"]
            self.assertEqual(origine["repo"], "homelab-docs")
            self.assertRegex(origine["commitSha"], r"^[0-9a-f]{40}$")            # commit immuable de la source
            for doc in (d for v in spec["versions"] for d in v["documents"]):
                self.assertRegex(doc["sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(all(p["repo"] == "homelab-docs" and p["path"] for p in doc["provenances"]), doc)
        self.ok("statuer", "--spec", "SPEC-JEU-B", "--visibility", "public", "--ref", REF)
        export = self.d.specctl("export", "--format", "json", "--public", "--json").stdout
        self.assertIn("SPEC-JEU-B", export)
        self.assertNotIn("SPEC-JEU-A", export)                                # privée par défaut : jamais exportée
        self.assertEqual(json.loads((self.reg / "journal.jsonl").read_text().splitlines()[-1])["command"], "statuer")


class E147E101ControleEnPr(unittest.TestCase):
    """REG-06 : PR refusée sans résolution des specs ; objectif 4 : consultation préalable imposée via specctl.

    Deux portes : le gabarit CI des jeux (étape « spec résolue » AVANT lint, tests et build) et la CI de l'usine
    elle-même, dont chaque PR résout la spec de l'usine (SPEC-GAME-FACTORY) avant ses oracles."""

    @staticmethod
    def etapes(texte: str) -> list[tuple[str, str]]:
        """(nom, corps) des étapes d'un workflow Woodpecker, dans l'ordre (sans PyYAML : absent du venv des specs)."""
        blocs = re.split(r"(?m)^  - name: ", texte.split("\nsteps:\n", 1)[1])[1:]
        return [(b.split("\n", 1)[0].strip(), b) for b in blocs]

    def test_ci_de_l_usine_resout_sa_spec_sur_chaque_pr(self) -> None:
        texte = (RACINE / ".woodpecker" / "specs.yml").read_text()
        self.assertRegex(texte.split("\nsteps:\n", 1)[0], r"event: \[pull_request")
        etapes = dict(self.etapes(texte))
        noms = list(etapes)
        self.assertIn("resolve", noms)
        self.assertIn("./specctl --json resolve --project game-factory", etapes["resolve"])
        self.assertNotIn("when:", etapes["resolve"])                      # jamais sautée, PR comprise
        self.assertLess(noms.index("resolve"), noms.index("oracles-specctl"))

    def test_spec_de_l_usine_resolue_sur_le_registre_reel(self) -> None:
        r = subprocess.run([str(SPECCTL), "--json", "resolve", "--project", "game-factory"], capture_output=True,
                           text=True, timeout=60, cwd=str(RACINE))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([s["specId"] for s in json.loads(r.stdout)["specs"]], ["SPEC-GAME-FACTORY"])

    def test_gabarit_des_jeux_consulte_la_spec_avant_tout_build(self) -> None:
        texte = (RACINE / "ci" / "gabarit" / "checks.yml").read_text()
        self.assertIn("pull_request", texte.split("\nsteps:\n", 1)[0])
        noms = [n for n, _ in self.etapes(texte)]
        for apres in ("lint", "typecheck", "test", "build"):
            self.assertLess(noms.index("spec résolue"), noms.index(apres))
        script = (RACINE / "ci" / "scripts" / "spec-resolue.mjs").read_text()
        self.assertIn("process.exit(1)", script)                               # non résolue = PR rouge


class E151RechercheIndexReconstructible(Base):
    """REG-10 (P1) : recherche ; index reconstructible (même résultat après perte de l'index)."""

    def test_recherche_identique_apres_reconstruction(self) -> None:
        out = self.d.tmp / "gen"
        self.ok("index", "--out", str(out))
        avant = (out / "search-index" / "search-index.json").read_bytes()
        trouve = self.ok("search", "tuile")
        self.assertIn("REQ-JEU-A-E001", json.dumps(trouve))
        (out / "search-index" / "search-index.json").unlink()
        self.assertEqual(self.d.specctl("index", "--out", str(out), "--check", "--json").rc, 2)   # perdu = signalé
        self.ok("index", "--out", str(out))
        self.assertEqual((out / "search-index" / "search-index.json").read_bytes(), avant)


class E153ImpactAvanceExportable(Base):
    """REG-12 (P1) : impact avancé ; graphe et rapports exportables."""

    def test_graphe_et_rapports_exportes(self) -> None:
        self.ok("relier", "--spec", "SPEC-JEU-B", "--type", "consumes", "--target", "SPEC-JEU-A")
        impact = self.ok("impact", "--spec", "SPEC-JEU-A")
        self.assertIn("SPEC-JEU-B", json.dumps(impact["consumers"]))
        out = self.d.tmp / "gen"
        self.ok("index", "--out", str(out))
        graphe = json.loads((out / "dependency-graph" / "dependency-graph.json").read_text())
        self.assertIn({"from": "SPEC-JEU-B", "target": "SPEC-JEU-A", "type": "consumes"},
                      [{k: e[k] for k in ("from", "target", "type")} for e in graphe["edges"]])
        self.assertIn("SPEC-JEU-A", (out / "coverage" / "coverage.json").read_text())
        md = self.ok("export", "--format", "markdown")["markdown"]
        self.assertIn("## SPEC-JEU-A", md)


if __name__ == "__main__":
    unittest.main()
