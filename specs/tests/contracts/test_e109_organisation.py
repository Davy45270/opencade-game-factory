"""REG-003 § 3 (ARCH-001 E109) : l'organisation du module `specs/` de l'usine suit l'arborescence de la spec.

    registry/{games,platform,shared,decisions}/   manifests/projects/
    schemas/{specification,requirement,dependency,implementation,decision}.schema.json
    tools/specctl/   migrations/{drive,github}/   generated/{search-index,dependency-graph,coverage}/
    tests/{contracts,import,integration,acceptance}/   AGENTS.md  README.md

Les workflows `.github/workflows/{validate,resolve,impact,export}.yml` sont des étapes Woodpecker (.woodpecker/specs.yml),
écart validé par David (HL-525 7-2955, HL-538 condition 2)."""
from __future__ import annotations

import json
import pathlib
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[3]
SPECS = RACINE / "specs"


class OrganisationReg003(unittest.TestCase):
    def test_arborescence_de_la_spec(self) -> None:
        dossiers = [f"registry/{d}" for d in ("games", "platform", "shared", "decisions")] + [
            "manifests/projects", "tools/specctl", "migrations/drive", "migrations/github"] + [
            f"generated/{d}" for d in ("search-index", "dependency-graph", "coverage")] + [
            f"tests/{d}" for d in ("contracts", "import", "integration", "acceptance")]
        self.assertEqual([d for d in dossiers if not (SPECS / d).is_dir()], [])
        self.assertEqual([f for f in ("AGENTS.md", "README.md") if not (SPECS / f).is_file()], [])

    def test_cinq_schemas(self) -> None:
        for nom in ("specification", "requirement", "dependency", "implementation", "decision"):
            f = SPECS / "schemas" / f"{nom}.schema.json"
            self.assertTrue(f.is_file(), f)
            self.assertIn("$schema", json.loads(f.read_text(encoding="utf-8")))

    def test_index_generes_dans_leur_dossier(self) -> None:
        for d in ("search-index", "dependency-graph", "coverage"):
            self.assertTrue((SPECS / "generated" / d / f"{d}.json").is_file(), d)
        self.assertFalse((RACINE / "generated" / "specs").exists(), "ancien emplacement generated/specs")

    def test_ancien_emplacement_vide(self) -> None:
        self.assertFalse((SPECS / "specctl").exists())
        self.assertFalse((RACINE / "tests" / "specs").exists())

    def test_workflows_woodpecker_validate_resolve_impact_export(self) -> None:
        texte = (RACINE / ".woodpecker" / "specs.yml").read_text(encoding="utf-8")
        for etape in ("validate", "resolve", "impact", "export"):
            self.assertIn(f"- name: {etape}", texte)


if __name__ == "__main__":
    unittest.main()
