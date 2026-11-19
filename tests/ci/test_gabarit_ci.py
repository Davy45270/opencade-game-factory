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

    # --- revue Codex 3 (19/11) : sorties résiduelles, liens symboliques, injection YAML, cohérence Python/JS ---
    def parametres(self, **p) -> None:
        f = self.jeu / ".woodpecker/usine.json"
        f.write_text(json.dumps({**json.loads(f.read_text()), **p}))

    def test_e2e_desactive_mais_ancien_e2e_yml_present_est_une_derive(self) -> None:
        self.parametres(e2e=False)
        r = lancer("verifier", str(self.jeu))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("e2e.yml", r.stdout)

    def test_workflow_ou_script_surnumeraire_est_une_derive(self) -> None:
        (self.jeu / ".woodpecker/autre.yml").write_text("steps: []\n")
        (self.jeu / ".woodpecker/usine/ancien.mjs").write_text("// ancien\n")
        r = lancer("verifier", str(self.jeu))
        self.assertEqual(r.returncode, 1)
        self.assertIn("autre.yml", r.stdout)
        self.assertIn("ancien.mjs", r.stdout)

    def test_fichier_genere_en_lien_symbolique_est_une_derive(self) -> None:
        f = self.jeu / ".woodpecker/checks.yml"
        copie = self.tmp / "copie.yml"
        copie.write_text(f.read_text()); f.unlink(); f.symlink_to(copie)
        r = lancer("verifier", str(self.jeu))
        self.assertEqual(r.returncode, 1)
        self.assertIn("lien", r.stdout)

    def test_ecrire_ne_suit_pas_un_lien_hors_du_jeu(self) -> None:
        f = self.jeu / ".woodpecker/checks.yml"
        dehors = self.tmp / "dehors.yml"
        dehors.write_text("intact\n"); f.unlink(); f.symlink_to(dehors)
        r = lancer("rendre", str(self.jeu), "--ecrire")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(dehors.read_text(), "intact\n")

    def test_e2e_commande_multiligne_refusee(self) -> None:
        self.parametres(e2e_commande="npx playwright test\n    privileged: true")
        self.assertEqual(lancer("rendre", str(self.jeu)).returncode, 4)

    def test_node_image_qui_sort_du_scalaire_refusee(self) -> None:
        self.parametres(node_image="node:26\n    privileged: true")
        self.assertEqual(lancer("rendre", str(self.jeu)).returncode, 4)

    def test_checks_extra_qui_ajoute_un_attribut_a_build_refuse(self) -> None:
        self.parametres(checks_extra="    privileged: true\n")
        self.assertEqual(lancer("rendre", str(self.jeu)).returncode, 4)

    def test_e2e_commande_avec_deux_points_reste_une_chaine(self) -> None:
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML absent")
        self.parametres(e2e_commande="npx playwright test --grep 'a: b'")
        self.assertEqual(lancer("rendre", str(self.jeu), "--ecrire").returncode, 0)
        doc = yaml.safe_load((self.jeu / ".woodpecker/e2e.yml").read_text())
        self.assertEqual(doc["steps"][0]["commands"][-1], "npx playwright test --grep 'a: b'")

    def test_etapes_du_jeu_apres_les_controles_communs(self) -> None:
        checks = (TEMOIN / ".woodpecker/checks.yml").read_text()
        self.assertGreater(checks.index("name: assets du jeu"), checks.index("name: journaux d'agents hors dépôt"))

    def test_version_playwright_premiere_valeur_non_exacte_refusee_comme_en_js(self) -> None:
        lock = json.loads((self.jeu / "package-lock.json").read_text())
        lock["packages"]["node_modules/@playwright/test"]["version"] = "^1.65.0"
        lock["packages"]["node_modules/playwright"] = {"version": "1.65.1"}
        (self.jeu / "package-lock.json").write_text(json.dumps(lock))
        self.assertEqual(lancer("verifier", str(self.jeu)).returncode, 4)

    def test_aucune_reference_privee_dans_les_fichiers_generes(self) -> None:
        # Les fichiers générés partent dans des dépôts de jeux PUBLICS : ni ticket, ni chemin de machine.
        import re
        for chemin in list((TEMOIN / ".woodpecker").rglob("*")):
            if chemin.is_file() and chemin.name != "usine.json":
                t = chemin.read_text()
                # revue Codex 6 (19/11) : ni nom d'hôte, ni domaine, ni adresse du réseau du homelab
                self.assertIsNone(re.search(r"\bHL-\d+|/home/|homelab|tank01|zalman|contabo|harbor|pingfr|duckdns|dav123|192\.168\.", t, re.I),
                                  f"{chemin.name} : référence privée")


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

    def test_demarrage_csp_commentee_ne_compte_pas(self) -> None:
        self.assertEqual(self.csp('<html><head><!-- <meta http-equiv="Content-Security-Policy" content="default-src \'self\'"> -->'
                                  "</head></html>"), 1)

    def test_demarrage_csp_attributs_dans_l_autre_ordre(self) -> None:
        self.assertEqual(self.csp('<html><head><meta content="default-src \'self\'" http-equiv="Content-Security-Policy"></head></html>'), 0)

    def test_demarrage_csp_politique_entiere_avec_apostrophes(self) -> None:
        (self.tmp / "index.html").write_text('<meta http-equiv="Content-Security-Policy" content="default-src \'self\'; script-src \'self\'">')
        r = subprocess.run([NODE, str(RACINE / "ci/scripts/demarrage-csp.mjs"), str(self.tmp), "--sec"], capture_output=True, text=True, timeout=30)
        self.assertIn("script-src 'self'", r.stdout)

    def test_serveur_csp_ne_sert_rien_hors_de_dist(self) -> None:
        import urllib.error
        import urllib.request
        dist = self.tmp / "dist"; dist.mkdir()
        (dist / "index.html").write_text('<meta http-equiv="Content-Security-Policy" content="default-src \'self\'">ok')
        dehors = self.tmp / "secret.txt"; dehors.write_text("SECRET")
        (dist / "lien.txt").symlink_to(dehors)
        (self.tmp / "rep").mkdir(); (self.tmp / "rep/index.html").write_text("DEHORS")
        (dist / "rep").symlink_to(self.tmp / "rep")
        p = subprocess.Popen([NODE, str(RACINE / "ci/scripts/demarrage-csp.mjs"), str(dist), "--servir"], stdout=subprocess.PIPE, text=True)
        try:
            url = ""
            for _ in range(5):
                ligne = p.stdout.readline()
                if ligne.startswith("servi sur "):
                    url = ligne.split()[-1]; break
            self.assertTrue(url, "pas d'URL")
            def code(chemin):
                try:
                    return urllib.request.urlopen(url + chemin, timeout=5).status
                except urllib.error.HTTPError as e:
                    return e.code
            self.assertEqual((code(""), code("lien.txt"), code("rep/"), code("%E0%A4%A")), (200, 403, 403, 400))
            self.assertIsNone(p.poll(), "le serveur est tombé")
        finally:
            p.kill(); p.wait()

    def test_verifier_sbom_version_inconnue_et_composant_sans_type(self) -> None:
        f = self.tmp / "sbom.json"
        base = {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": [{"type": "library", "name": "vite", "version": "8.3.6"}]}
        def rc(b):
            f.write_text(json.dumps(b))
            return subprocess.run([NODE, str(RACINE / "ci/scripts/verifier-sbom.mjs"), str(f)], capture_output=True).returncode
        self.assertEqual((rc(base), rc({**base, "specVersion": "1.9"}), rc({**base, "components": [{"name": "vite"}]}),
                          rc({**base, "components": [{"type": "truc", "name": "vite"}]})), (0, 1, 1, 1))

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

    def test_garde_ticket_variantes_hors_liste_et_tickets_colles(self) -> None:
        # revue Codex 5 (19/11, n°6) : borne droite « . » + chiffre, « _ » des deux côtés
        self.assertEqual(self.garde("CC-BY-4.0.1", "CC-BY-4.0_AB-9", "AB-9_CC-BY-4.0", "x_AB-12", "AB-12_x"),
                         [True, True, True, True, True])
        self.assertEqual(self.garde("licence CC-BY-4.0.", "CC-BY-4.0, MIT", "(CC-BY-SA-4.0)"), [False, False, False])

    def test_garde_ticket_cli(self) -> None:
        (self.tmp / "ok.txt").write_text("licence CC-BY-4.0\n")
        (self.tmp / "ko.txt").write_text("ligne propre\nréf HL-42\n")
        r = subprocess.run([NODE, str(RACINE / "ci/scripts/garde-ticket.mjs"), str(self.tmp / "ok.txt"), str(self.tmp / "ko.txt")],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout.strip()), (1, f"{self.tmp / 'ko.txt'}:2"))


if __name__ == "__main__":
    unittest.main()
