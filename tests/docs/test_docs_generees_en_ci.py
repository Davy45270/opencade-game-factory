"""Anomalie HL-525 (lot usine3) : `scripts/docs_generees.py --check` ne tournait dans aucun pipeline, et les pages
`dependances.md` et `exploitation.md` étaient périmées sur main sans que personne ne le voie.

- un pipeline Woodpecker exécute `scripts/docs_generees.py --check` (code 2 si une page est périmée ou absente) ;
- les pages commitées de `generated/docs/` sont à jour au commit testé.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[2]


class DocsGenereesEnCI(unittest.TestCase):
    def test_un_pipeline_execute_le_controle(self) -> None:
        import yaml
        trouves = []
        for f in sorted((RACINE / ".woodpecker").glob("*.yml")):
            for etape in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("steps") or []:
                if any("scripts/docs_generees.py --check" in str(c) for c in etape.get("commands") or []):
                    trouves.append(f"{f.name}:{etape['name']}")
        self.assertTrue(trouves, "aucune étape Woodpecker ne lance scripts/docs_generees.py --check")

    def test_pages_generees_a_jour(self) -> None:
        r = subprocess.run([sys.executable, str(RACINE / "scripts" / "docs_generees.py"), "--check"],
                           capture_output=True, text=True, timeout=120, cwd=RACINE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
