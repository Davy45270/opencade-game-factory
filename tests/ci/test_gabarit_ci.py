"""Gabarit CI commun (écart 6 de l'analyse des écarts) : le jeu-témoin INCLUT la CI de l'usine, et toute dérive est vue.

Le jeu-témoin (`tests/fixtures/jeu-temoin`) porte les fichiers générés par `ci/woodpecker.py rendre --ecrire` ; ces tests
prouvent qu'il les utilise tels quels, puis que chaque écart (main, lock, gabarit, paramètre) rend `verifier` rouge.
Aucun réseau, aucun navigateur : le démarrage sous CSP n'est joué ici qu'en mode `--sec` (lecture de la politique)."""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[2]
OUTIL = RACINE / "ci" / "woodpecker.py"
TEMOIN = RACINE / "tests" / "fixtures" / "jeu-temoin"
NODE = shutil.which("node")


def lancer(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(OUTIL), *args], capture_output=True, text=True, timeout=60)


class JeuTemoin(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="usine-ci-"))
        self.jeu = self.tmp / "jeu"
        shutil.copytree(TEMOIN, self.jeu)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_le_jeu_temoin_utilise_le_gabarit_tel_quel(self) -> None:
        r = lancer("verifier", str(TEMOIN), "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(json.loads(r.stdout)["ok"])

    def test_la_ci_generee_porte_sbom_verifie_playwright_du_lock_et_csp(self) -> None:
        checks = (TEMOIN / ".woodpecker/checks.yml").read_text()
        e2e = (TEMOIN / ".woodpecker/e2e.yml").read_text()
        self.assertIn("node .woodpecker/usine/verifier-sbom.mjs sbom.json", checks)
        self.assertNotIn("grep -c CycloneDX", checks)
        self.assertIn("image: &node ", checks)                      # ancre lue par l'outil de publication
        self.assertIn("mcr.microsoft.com/playwright:v1.65.1-noble", e2e)  # = package-lock du témoin
        self.assertIn("version-playwright.mjs --verifier", e2e)
        self.assertIn("node .woodpecker/usine/demarrage-csp.mjs dist", e2e)
        self.assertIn("name: assets du jeu", checks)                # étape propre au jeu, par usine.json
        self.assertRegex(checks, r"\n      - npm test\n")              # suite unitaire COMPLÈTE en CI, sans filtre
        self.assertIn("git ls-files .codex-logs", checks)            # journaux d'agents jamais versionnés
        self.assertIn("event: push", e2e)                            # e2e (démarrage sous CSP compris) à chaque push
        for s in ("verifier-sbom.mjs", "version-playwright.mjs", "demarrage-csp.mjs"):
            self.assertTrue((TEMOIN / ".woodpecker/usine" / s).is_file(), s)

    def test_yaml_valide(self) -> None:
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML absent")
        for f in ("checks.yml", "e2e.yml"):
            doc = yaml.safe_load((TEMOIN / ".woodpecker" / f).read_text())
            self.assertIsInstance(doc["steps"], list, f)

    def test_modification_a_la_main_est_une_derive(self) -> None:
        f = self.jeu / ".woodpecker/checks.yml"
        f.write_text(f.read_text().replace("node .woodpecker/usine/verifier-sbom.mjs sbom.json", "grep -c CycloneDX sbom.json"))
        r = lancer("verifier", str(self.jeu))
        self.assertEqual(r.returncode, 1)
        self.assertIn("checks.yml", r.stdout)

    def test_playwright_monte_dans_le_lock_la_ci_est_perimee(self) -> None:
        lock = json.loads((self.jeu / "package-lock.json").read_text())
        lock["packages"]["node_modules/@playwright/test"]["version"] = "1.66.0"
        (self.jeu / "package-lock.json").write_text(json.dumps(lock))
        r = lancer("verifier", str(self.jeu))
        self.assertEqual(r.returncode, 1)
        self.assertIn("e2e.yml", r.stdout)
        self.assertEqual(lancer("rendre", str(self.jeu), "--ecrire").returncode, 0)
        self.assertIn("v1.66.0-noble", (self.jeu / ".woodpecker/e2e.yml").read_text())
        self.assertEqual(lancer("verifier", str(self.jeu)).returncode, 0)

    def test_script_commun_absent_est_une_derive(self) -> None:
        (self.jeu / ".woodpecker/usine/demarrage-csp.mjs").unlink()
        self.assertEqual(lancer("verifier", str(self.jeu)).returncode, 1)

    def test_lock_sans_playwright_source_indisponible(self) -> None:
        (self.jeu / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {"": {}}}))
        self.assertEqual(lancer("verifier", str(self.jeu)).returncode, 4)

    def test_parametre_inconnu_refuse(self) -> None:
        (self.jeu / ".woodpecker/usine.json").write_text(json.dumps({"images": "x"}))
        self.assertEqual(lancer("rendre", str(self.jeu)).returncode, 4)

    def test_usage(self) -> None:
        self.assertEqual(lancer("inventer", str(self.jeu)).returncode, 2)

    def test_aucune_reference_privee_dans_les_fichiers_generes(self) -> None:
        # Les fichiers générés partent dans des dépôts de jeux PUBLICS : ni ticket, ni chemin de machine.
        import re
        for chemin in list((TEMOIN / ".woodpecker").rglob("*")):
            if chemin.is_file() and chemin.name != "usine.json":
                t = chemin.read_text()
                self.assertIsNone(re.search(r"\bHL-\d+|/home/|homelab", t), f"{chemin.name} : référence privée")


@unittest.skipUnless(NODE, "node absent")
class ScriptsCommuns(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="usine-csp-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def csp(self, html: str, *opts: str) -> int:
        (self.tmp / "index.html").write_text(html)
        return subprocess.run([NODE, str(RACINE / "ci/scripts/demarrage-csp.mjs"), str(self.tmp), "--sec", *opts],
                              capture_output=True, timeout=30).returncode

    def test_demarrage_sans_csp_de_production_refuse(self) -> None:
        self.assertEqual(self.csp("<html><head></head><body>x</body></html>"), 1)

    def test_demarrage_csp_meta_lue(self) -> None:
        self.assertEqual(self.csp('<html><head><meta http-equiv="Content-Security-Policy" content="default-src \'self\'">'
                                  "</head></html>"), 0)

    def test_demarrage_csp_en_entete_seule(self) -> None:
        self.assertEqual(self.csp("<html></html>", "--csp", "default-src 'self'"), 0)

    def test_version_playwright_verifie_l_image(self) -> None:
        v = RACINE / "ci/scripts/version-playwright.mjs"
        lock = str(TEMOIN / "package-lock.json")
        ok = subprocess.run([NODE, str(v), "--lock", lock, "--verifier", "mcr.microsoft.com/playwright:v1.65.1-noble"], capture_output=True)
        ko = subprocess.run([NODE, str(v), "--lock", lock, "--verifier", "mcr.microsoft.com/playwright:v1.64.1-noble"], capture_output=True)
        self.assertEqual((ok.returncode, ko.returncode), (0, 1))

    def test_verifier_sbom_refuse_un_faux_sbom(self) -> None:
        f = self.tmp / "sbom.json"
        f.write_text('{"error":"CycloneDX failed"}')
        r = subprocess.run([NODE, str(RACINE / "ci/scripts/verifier-sbom.mjs"), str(f)], capture_output=True)
        self.assertEqual(r.returncode, 1)

    # Garde « identifiant de ticket » (relevé de Cozy, 19/11) : CC-BY-4.0 était pris pour un ticket (motif BY-4).
    # Les identifiants de licence SPDX connus sont exclus PAR LISTE ; le motif de ticket n'est pas élargi.
    def garde(self, *lignes: str) -> list[bool]:
        f = self.tmp / "lignes.json"
        f.write_text(json.dumps(list(lignes)))
        code = ("import { estTicket } from " + json.dumps((RACINE / "ci/scripts/garde-ticket.mjs").as_uri()) + ";"
                "import { readFileSync } from 'node:fs';"
                "console.log(JSON.stringify(JSON.parse(readFileSync(process.argv[1], 'utf8')).map(estTicket)));")
        r = subprocess.run([NODE, "--input-type=module", "-e", code, str(f)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_garde_ticket_licences_spdx_passent(self) -> None:
        self.assertEqual(self.garde('"licence": "CC-BY-4.0",', "Assets : CC-BY-SA-4.0.", "GPL-3.0-or-later", "code MIT, assets CC-BY-4.0"),
                         [False, False, False, False])

    def test_garde_ticket_tickets_restent_refuses(self) -> None:
        self.assertEqual(self.garde("voir HL-123", "QWK-012 : score", "CC-BY-4.0 et HL-9", "XCC-BY-4.0", "CC-BY-4"),
                         [True, True, True, True, True])

    def test_garde_ticket_cli(self) -> None:
        (self.tmp / "ok.txt").write_text("licence CC-BY-4.0\n")
        (self.tmp / "ko.txt").write_text("ligne propre\nréf HL-42\n")
        r = subprocess.run([NODE, str(RACINE / "ci/scripts/garde-ticket.mjs"), str(self.tmp / "ok.txt"), str(self.tmp / "ko.txt")],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout.strip()), (1, f"{self.tmp / 'ko.txt'}:2"))


if __name__ == "__main__":
    unittest.main()
