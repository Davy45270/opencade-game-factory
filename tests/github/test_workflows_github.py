"""Oracles ARCH-001/REG-003/BB-001 E110, E138, E207 (énoncés tels qu'écrits, David 22/11 : « on utilise github »),
écrits AVANT les fichiers : workflows `.github` validate/resolve/impact/export, bbctl consommé par GitHub Actions,
propriétaires du code. Woodpecker reste en plus. La protection de branche se mesure sur GitHub (API), pas ici."""
from __future__ import annotations

import os
import pathlib
import subprocess
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[2]
WF = RACINE / ".github" / "workflows" / "usine.yml"


class WorkflowsGitHub(unittest.TestCase):
    def test_e110_validate_resolve_impact_export(self) -> None:
        t = WF.read_text(encoding="utf-8")
        for c in ("./specctl --json validate", "./specctl --json resolve --project", "./specctl --json impact --spec",
                  "./specctl --json export --format json"):
            self.assertIn(c, t)
        self.assertIn("pull_request", t)

    def test_e207_bbctl_consomme_par_github_actions(self) -> None:
        t = WF.read_text(encoding="utf-8")
        self.assertIn("./bbctl validate --all --json", t)
        self.assertIn("python3 -m unittest discover -s tests/blocks", t)

    def test_e138_proprietaires_du_code(self) -> None:
        t = (RACINE / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        self.assertRegex(t, r"(?m)^\*\s+@Davy45270\s*$")

    def test_yaml_valide(self) -> None:
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML absent")
        d = yaml.safe_load(WF.read_text(encoding="utf-8"))
        self.assertIn("jobs", d)


    def test_les_etapes_du_registre_passent_sur_les_vraies_fiches(self) -> None:
        """Rejoue le `run` de chaque étape du job registre, tel quel, sur le dépôt (22/11 : le premier passage sur
        GitHub a échoué sur SPEC-ECHECS, spec sans version, alors que les tests ne lisaient que le texte)."""
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML absent")
        job = yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]["registre"]
        etapes = [e for e in job["steps"] if e.get("name") in ("validate", "resolve", "impact", "export")]
        self.assertEqual([e["name"] for e in etapes], ["validate", "resolve", "impact", "export"])
        try:
            for e in etapes:
                r = subprocess.run(["bash", "-e", "-c", e["run"]], cwd=RACINE, capture_output=True, text=True,
                                   env=dict(os.environ, GITHUB_STEP_SUMMARY=os.devnull))
                self.assertEqual(r.returncode, 0, f"{e['name']} : {r.stdout[-400:]} {r.stderr[-400:]}")
                if e["name"] == "resolve":
                    self.assertIn("::warning", r.stdout)        # une spec sans version est SIGNALÉE, pas tue
        finally:
            (RACINE / "registre-export.json").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
