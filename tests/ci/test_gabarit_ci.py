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


if __name__ == "__main__":
    unittest.main()
