"""ARCH-001 DOC-001 (E041) et ARCH-14 (E069) : documentation générée depuis les sources, PR documentaires traçables
avec liens vers le registre, jamais d'écrasement d'un document humain. Fixtures seulement (dépôt git jetable, remote
nu local, faux serveur Forgejo)."""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "docs_generees.py"


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True,
                          capture_output=True, text=True).stdout.strip()


def ecrire(r: pathlib.Path, chemin: str, texte: str) -> None:
    (r / chemin).parent.mkdir(parents=True, exist_ok=True)
    (r / chemin).write_text(texte, encoding="utf-8")


ADR = "# ADR-0001 — Specs dans l'usine\n\n- **Statut :** approuvée\n- **Date :** 2026-11-19\n- **Approuvée par :** David\n"


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="docs-"))
        self.r = self.tmp / "usine"
        r = self.r
        ecrire(r, "specctl", "#!/usr/bin/env python3\n")
        ecrire(r, "bbctl", "#!/usr/bin/env python3\n")
        ecrire(r, "contracts/index.json", json.dumps({"regle": "ajout seul", "contrats": {
            "Release": {"version": "1.1.0", "schema": "contracts/schemas/release.json",
                        "historique": [{"version": "1.0.0"}, {"version": "1.1.0"}]}}}))
        ecrire(r, "docs/integration-decisions/ADR-0001-specs.md", ADR)
        ecrire(r, "specs/registry/SPEC-JEU-A.json", "{}")
        ecrire(r, "blocks/catalog/BB-JEU-A-MOTEUR-001.json", json.dumps({
            "id": "BB-JEU-A-MOTEUR-001", "kind": "game-local-module", "usedBy": ["jeu-a/apps/web", "jeu-b"],
            "specIds": ["SPEC-JEU-A"], "origin": {"licenseSpdx": "MIT"}, "decision": {"status": "decided", "choice": "reuse"}}))
        ecrire(r, ".woodpecker/specs.yml", "# Module specs : oracles.\n# Rejeu local : scripts/ci-local.sh specs\n"
               "when:\n  - event: [pull_request, manual]\nsteps:\n  - name: oracles\n    image: x\n")
        ecrire(r, "specs/registry/journal.jsonl", json.dumps({"at": "2026-11-21T10:00:00Z", "command": "import",
                                                              "specId": "SPEC-JEU-A"}) + "\n")
        git(r, "init", "-q", "-b", "main")
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", "base")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lancer(self, *a: str, env=None):
        p = subprocess.run([sys.executable, str(SCRIPT), "--racine", str(self.r), *a], capture_output=True, text=True,
                           env=env)
        return p.returncode, json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else None

    def page(self, nom: str) -> str:
        return (self.r / "generated/docs" / nom).read_text(encoding="utf-8")


class Generation(Base):
    def test_six_pages_depuis_les_sources(self) -> None:
        rc, out = self.lancer()
        self.assertEqual((rc, len(out["pages"])), (0, 6))
        for nom in ("architecture.md", "contrats.md", "adr.md", "dependances.md", "exploitation.md", "changelog.md"):
            self.assertTrue(self.page(nom).startswith("<!-- généré par scripts/docs_generees.py"), nom)
            self.assertIn("Sources :", self.page(nom))
        self.assertIn("| Release | 1.1.0 | `contracts/schemas/release.json` | 1.0.0, 1.1.0 |", self.page("contrats.md"))
        self.assertIn("| approuvée | 2026-11-19 | David |", self.page("adr.md"))
        self.assertIn("## jeu-a", self.page("dependances.md"))
        self.assertIn("Specs : SPEC-JEU-A", self.page("dependances.md"))
        self.assertIn("| BB-JEU-A-MOTEUR-001 | game-local-module | — | MIT | reuse |", self.page("dependances.md"))
        self.assertIn("Rejeu local : scripts/ci-local.sh specs", self.page("exploitation.md"))
        self.assertIn("`import` : 1 — SPEC-JEU-A", self.page("changelog.md"))

    def test_check_dit_la_peremption(self) -> None:
        self.lancer()
        self.assertEqual(self.lancer("--check")[0], 0)
        ecrire(self.r, "docs/integration-decisions/ADR-0001-specs.md", ADR.replace("approuvée", "remplacée"))
        rc, out = self.lancer("--check")
        self.assertEqual((rc, out["pages"]), (2, ["adr.md"]))

    def test_document_humain_jamais_ecrase(self) -> None:
        ecrire(self.r, "generated/docs/adr.md", "# Notes de David\n")
        rc, out = self.lancer()
        self.assertEqual((rc, out["status"]), (5, "refus"))
        self.assertEqual(self.page("adr.md"), "# Notes de David\n")
        self.assertFalse((self.r / "generated/docs/contrats.md").exists())      # garde avant toute écriture


class FauxForgejo(BaseHTTPRequestHandler):
    recus: list = []

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        FauxForgejo.recus.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(n))))
        self.send_response(201)
        self.end_headers()
        self.wfile.write(json.dumps({"number": 7}).encode())

    def log_message(self, *a):
        pass


class PrDocumentaire(Base):
    def test_pr_tracable_avec_sources_et_identifiants(self) -> None:
        nu = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(nu)], check=True)
        srv = HTTPServer(("127.0.0.1", 0), FauxForgejo)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        FauxForgejo.recus = []
        try:
            env = {**__import__("os").environ, "DOCS_FORGE_TOKEN": "jeton-de-test", "GIT_AUTHOR_NAME": "t",
                   "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
            rc, out = self.lancer("--pr", "--remote", str(nu), "--api", f"http://127.0.0.1:{srv.server_port}/api/v1",
                                  "--depot", "david/usine", env=env)
        finally:
            srv.shutdown()
        self.assertEqual((rc, out["status"], out["pr"]), (0, "pr-ouverte", 7))
        (chemin, auth, corps), = FauxForgejo.recus
        self.assertEqual((chemin, auth), ("/api/v1/repos/david/usine/pulls", "token jeton-de-test"))
        self.assertEqual((corps["head"], corps["base"]), (out["branche"], "main"))
        for attendu in ("Commit source : ", "`generated/docs/adr.md`", "docs/integration-decisions/ADR-0001-specs.md",
                        "ADR-0001", "BB-JEU-A-MOTEUR-001", "SPEC-JEU-A"):
            self.assertIn(attendu, corps["body"])
        fichiers = git(nu, "diff", "--name-only", "main", out["branche"]).splitlines() if False else \
            git(self.r, "diff", "--name-only", "main", out["branche"]).splitlines()
        self.assertEqual(sorted(fichiers), sorted(out["pages"]))                  # seules les pages, rien d'autre
        self.assertTrue(all(f.startswith("generated/docs/") for f in fichiers))
        self.assertEqual(git(nu, "rev-parse", out["branche"]), git(self.r, "rev-parse", out["branche"]))   # poussée

    def test_rien_a_proposer_quand_a_jour(self) -> None:
        self.lancer()
        git(self.r, "add", "generated")
        git(self.r, "commit", "-q", "-m", "docs")
        rc, out = self.lancer("--pr", "--remote", "inutile", "--api", "http://127.0.0.1:9", "--depot", "d/u")
        self.assertEqual((rc, out["status"]), (0, "a-jour"))


if __name__ == "__main__":
    unittest.main()
