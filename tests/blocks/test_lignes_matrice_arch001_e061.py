"""Oracle de ligne de la matrice game-factory (HL-525), écrit AVANT le code.

- E061 (ARCH-06, « Référencement solutions BB-001 : code, licence, SBOM et consommateurs ») : un workflow ou un script
  découvert dans un dépôt porte la licence déclarée par ce dépôt (champ `license` SPDX du package.json racine), comme
  ses modules locaux. Sans déclaration lisible, la licence reste `UNKNOWN` : elle n'est jamais inventée.
"""
from __future__ import annotations

import json

from .test_bbctl_discover import Base as Decouverte


class E061LicenceDuDepotPourWorkflowsEtScripts(Decouverte):
    def setUp(self) -> None:
        super().setUp()
        self.depot("mono", {
            "package.json": json.dumps({"name": "mono", "license": "MIT"}),
            ".woodpecker/checks.yml": "steps:\n  - name: test\n",
            "scripts/publier.sh": "#!/bin/sh\necho publier\n",
        })
        self.depot("jeu-p", {
            "package.json": json.dumps({"name": "jeu-p", "license": "licence maison"}),
            ".woodpecker/checks.yml": "steps:\n  - name: test\n",
            "scripts/publier.sh": "#!/bin/sh\necho publier\n",
        })
        self.sources.write_text(json.dumps({"schemaVersion": 1, "excluded": [], "sources": [
            {"name": "mono"}, {"name": "jeu-p"}]}))
        r = self.decouvrir()
        self.assertEqual(r.rc, 0, r)

    def licences(self, repo: str) -> dict:
        return {b["kind"]: b["origin"]["licenseSpdx"] for b in self.catalogue().values()
                if b["origin"].get("repo") == repo and b["kind"] in ("workflow", "cli-tool")}

    def test_workflow_et_script_heritent_la_licence_du_depot(self) -> None:
        self.assertEqual(self.licences("mono"), {"workflow": "MIT", "cli-tool": "MIT"})

    def test_licence_non_spdx_jamais_inventee(self) -> None:
        self.assertEqual(self.licences("jeu-p"), {"workflow": "UNKNOWN", "cli-tool": "UNKNOWN"})


if __name__ == "__main__":
    import unittest
    unittest.main()
