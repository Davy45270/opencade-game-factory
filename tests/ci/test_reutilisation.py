"""Oracles BB-001 E190/E221 (HL-525), écrits AVANT le code : « reuse before build » dans la CI des jeux, en
AVERTISSEMENT (non bloquant, décision du coordinateur du 21/11 ; le blocage viendra plus tard).

- `ci/scripts/reutilisation.mjs` (copié par le gabarit dans `.woodpecker/usine/`) calcule les briques NOUVELLES entre
  la base et HEAD avec les mêmes clés que `bbctl gate` (npm avec version du lockfile, image Docker, module local
  `src/engines/<x>` ou `packages/<x>`), les compare à `.woodpecker/usine/briques.json` (clés décidées au catalogue et
  dérogations HL-n 7-n, écrit par l'usine à la génération) et écrit le rapport `reutilisation-rapport.json`.
- Code de sortie 0 dans tous les cas (avertissement) ; le rapport et le log disent ce qui n'est pas couvert.
- Parité : sur le même dépôt, la liste non couverte est celle de `bbctl gate`.
- Le gabarit porte l'étape ; le fichier généré ne contient que des clés (aucune donnée privée du catalogue).
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = RACINE / "ci" / "scripts" / "reutilisation.mjs"
NODE = shutil.which("node")


def git(d: pathlib.Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(NODE, "node absent")
class Reutilisation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="reutilisation-"))
        self.jeu = self.tmp / "jeu"
        self.ecrire({"package.json": json.dumps({"name": "jeu", "dependencies": {"phaser": "^3"}}),
                     "package-lock.json": json.dumps({"lockfileVersion": 3, "packages": {
                         "node_modules/phaser": {"version": "3.80.1"}}}),
                     "src/engines/combat/index.ts": "export const a = 1\n"})
        git(self.jeu, "init", "-q", "-b", "main")
        self.base = self.commit()
        self.ecrire({"package.json": json.dumps({"name": "jeu", "dependencies": {"phaser": "^3", "howler": "^2"},
                                                 "devDependencies": {"vitest": "^3"}}),
                     "package-lock.json": json.dumps({"lockfileVersion": 3, "packages": {
                         "node_modules/phaser": {"version": "3.80.1"}, "node_modules/howler": {"version": "2.2.4"},
                         "node_modules/vitest": {"version": "3.2.0"}}}),
                     "Dockerfile": "FROM node:22 AS build\nFROM nginx:1.27-alpine\nCOPY --from=build /a /b\n",
                     "src/engines/physique/index.ts": "export const g = 9.81\n"})
        self.tete = self.commit()
        (self.jeu / ".woodpecker" / "usine").mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ecrire(self, fichiers: dict[str, str]) -> None:
        for chemin, texte in fichiers.items():
            (self.jeu / chemin).parent.mkdir(parents=True, exist_ok=True)
            (self.jeu / chemin).write_text(texte)

    def commit(self) -> str:
        git(self.jeu, "add", "-A")
        git(self.jeu, "commit", "-q", "-m", "c")
        return git(self.jeu, "rev-parse", "HEAD")

    def briques(self, decided=(), derogations=None) -> None:
        (self.jeu / ".woodpecker/usine/briques.json").write_text(json.dumps(
            {"repo": "jeu", "decided": sorted(decided), "derogations": derogations or {}}))

    def lancer(self, *args: str) -> tuple[int, dict]:
        r = subprocess.run([NODE, str(SCRIPT), "--base", self.base, *args], cwd=self.jeu, capture_output=True,
                           text=True, timeout=60)
        rapport = self.jeu / "reutilisation-rapport.json"
        return r.returncode, (json.loads(rapport.read_text()) if rapport.is_file() else {"stdout": r.stdout, "stderr": r.stderr})

    def test_nouvelles_briques_non_couvertes_signalees_sans_bloquer(self) -> None:
        self.briques()
        rc, rap = self.lancer()
        self.assertEqual(rc, 0, rap)
        self.assertEqual(rap["mode"], "avertissement")
        self.assertEqual(rap["uncovered"], ["docker:nginx@1.27-alpine", "docker:node@22", "local:jeu:src/engines/physique",
                                            "npm:howler@2.2.4", "npm:vitest@3.2.0"])
        self.assertEqual((rap["base"], rap["head"]), (self.base, self.tete))

    def test_decision_et_derogation_couvrent(self) -> None:
        self.briques(decided=["npm:howler@2.2.4", "docker:node@22"],
                     derogations={"local:jeu:src/engines/physique": {"ref": "HL-525 7-3000", "expire": "2099-12-31"}, "npm:vitest@3.2.0": {"ref": "pas une ref", "expire": "2099-12-31"},
                                  "docker:nginx@1.27-alpine": {"ref": "HL-1 7-1", "expire": "2099-12-31"}})
        rc, rap = self.lancer()
        self.assertEqual(rap["uncovered"], ["npm:vitest@3.2.0"])
        self.assertEqual(sorted(rap["derogations"]), ["docker:nginx@1.27-alpine", "local:jeu:src/engines/physique"])

    def test_sans_fichier_briques_avertissement_explicite(self) -> None:
        rc, rap = self.lancer()
        self.assertEqual(rc, 0)
        self.assertEqual(rap["status"], "catalogue-indisponible")

    def test_base_introuvable_avertissement_explicite(self) -> None:
        self.briques()
        r = subprocess.run([NODE, str(SCRIPT), "--base", "inexistante"], cwd=self.jeu, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads((self.jeu / "reutilisation-rapport.json").read_text())["status"], "base-indisponible")

    def test_parite_avec_bbctl_gate(self) -> None:
        self.briques()
        _, rap = self.lancer()
        usine = self.tmp / "usine"
        (usine / "blocks" / "catalog").mkdir(parents=True)
        env = {**os.environ, "USINE_RACINE": str(usine)}
        r = subprocess.run([str(RACINE / "bbctl"), "gate", "--repo", str(self.jeu), "--base", self.base, "--json"],
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(rap["uncovered"], json.loads(r.stdout)["uncovered"], r.stderr[-300:])

    # E190/E221 (HL-525, lot usine3) : un jeu peut passer la barrière en BLOQUANT (`"reutilisation": "bloquant"` dans
    # .woodpecker/usine.json). Une brique nouvelle sans recherche documentée ni dérogation fait alors échouer la CI ; une
    # base ou un catalogue illisible aussi (rien n'est prouvé : pas de vert muet).
    def test_bloquant_echoue_sur_brique_non_couverte(self) -> None:
        self.briques(decided=["npm:howler@2.2.4"])
        rc, rap = self.lancer("--bloquant")
        self.assertEqual(rc, 1, rap)
        self.assertEqual((rap["mode"], rap["status"]), ("bloquant", "non-couvert"))
        self.assertIn("npm:vitest@3.2.0", rap["uncovered"])

    def test_bloquant_passe_quand_tout_est_decide_ou_deroge(self) -> None:
        self.briques(decided=["npm:howler@2.2.4", "docker:node@22", "docker:nginx@1.27-alpine", "npm:vitest@3.2.0"],
                     derogations={"local:jeu:src/engines/physique": {"ref": "HL-525 7-3000", "expire": "2099-12-31"}})
        rc, rap = self.lancer("--bloquant")
        self.assertEqual(rc, 0, rap)
        self.assertEqual((rap["mode"], rap["status"], rap["uncovered"]), ("bloquant", "ok", []))

    def test_bloquant_base_introuvable_echoue(self) -> None:
        self.briques()
        r = subprocess.run([NODE, str(SCRIPT), "--bloquant", "--base", "inexistante"], cwd=self.jeu, capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads((self.jeu / "reutilisation-rapport.json").read_text())["status"], "base-indisponible")

    def test_bloquant_sans_catalogue_echoue(self) -> None:
        rc, rap = self.lancer("--bloquant")
        self.assertEqual(rc, 1)
        self.assertEqual(rap["status"], "catalogue-indisponible")


class Gabarit(unittest.TestCase):
    def rendre_checks(self, params: dict | None) -> str:
        sys.path.insert(0, str(RACINE / "ci"))
        import woodpecker  # noqa: E402
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="gabarit-reut-"))
        try:
            shutil.copytree(RACINE / "tests" / "fixtures" / "jeu-temoin", tmp / "jeu")
            f = tmp / "jeu" / ".woodpecker" / "usine.json"
            p = json.loads(f.read_text()) if f.is_file() else {}
            p.pop("reutilisation", None)
            if params:
                p.update(params)
            f.write_text(json.dumps(p))
            return woodpecker.rendre(tmp / "jeu")[".woodpecker/checks.yml"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_etape_d_avertissement_par_defaut(self) -> None:
        checks = self.rendre_checks(None)
        self.assertIn("node .woodpecker/usine/reutilisation.mjs\n", checks)
        self.assertIn("name: réutilisation (avertissement)", checks)
        self.assertNotIn("--bloquant", checks)

    def test_etape_bloquante_sur_demande_du_jeu_en_historique_complet(self) -> None:
        checks = self.rendre_checks({"reutilisation": "bloquant"})
        self.assertIn("node .woodpecker/usine/reutilisation.mjs --bloquant", checks)
        self.assertIn("name: réutilisation (bloquant)", checks)
        self.assertIn("depth: 0", checks)                       # la base d'une PR est son merge-base avec la cible
        self.assertIn("fetch_target_branch: true", checks)

    def test_mode_de_reutilisation_inconnu_refuse(self) -> None:
        sys.path.insert(0, str(RACINE / "ci"))
        import woodpecker  # noqa: E402
        with self.assertRaises(woodpecker.Indisponible):
            self.rendre_checks({"reutilisation": "souple"})

    def test_briques_json_ne_porte_que_des_cles(self) -> None:
        sys.path.insert(0, str(RACINE / "ci"))
        import woodpecker  # noqa: E402
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="briques-"))
        try:
            v = woodpecker.briques_du_jeu(tmp, "jeu")
            self.assertEqual(set(v), {"repo", "decided", "derogations"})
            self.assertTrue(all(isinstance(k, str) and ":" in k for k in v["decided"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
