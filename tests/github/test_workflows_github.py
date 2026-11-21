"""Oracles ARCH-001/REG-003/BB-001 E110, E138, E207 (énoncés tels qu'écrits, David 22/11 : « on utilise github »),
écrits AVANT les fichiers : workflows `.github` validate/resolve/impact/export, bbctl consommé par GitHub Actions,
propriétaires du code. Woodpecker reste en plus. La protection de branche se mesure sur GitHub (API), pas ici."""
from __future__ import annotations

import pathlib
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


if __name__ == "__main__":
    unittest.main()
