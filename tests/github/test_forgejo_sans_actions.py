"""Anomalie HL-525 (lot usine3) : sur la forge, chaque commit portait des statuts « usine / registre » et « usine /
briques » restés en attente pour toujours.

Cause : Forgejo Actions lit le PREMIER dossier qui existe parmi `.forgejo/workflows`, `.gitea/workflows` et
`.github/workflows`. Faute des deux premiers, il prenait `.github/workflows/usine.yml` (le workflow GitHub de la copie
publique) et créait un statut par job ; aucun runner Forgejo ne porte `ubuntu-24.04`, d'où « en attente ».
La CI de la forge est Woodpecker. Correctif : un dossier `.forgejo/workflows` versionné SANS aucun .yml : Forgejo s'y
arrête et ne lance rien ; GitHub, lui, garde son workflow.
"""
from __future__ import annotations

import pathlib
import subprocess
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[2]


class ForgejoSansActions(unittest.TestCase):
    def suivis(self, dossier: str) -> list[str]:
        r = subprocess.run(["git", "-C", str(RACINE), "ls-files", "--", dossier], capture_output=True, text=True,
                           check=True)
        return [l for l in r.stdout.splitlines() if l]

    def test_dossier_forgejo_versionne_et_sans_workflow(self) -> None:
        fichiers = self.suivis(".forgejo/workflows")
        self.assertTrue(fichiers, ".forgejo/workflows absent du dépôt : Forgejo retombe sur .github/workflows")
        self.assertFalse([f for f in fichiers if f.endswith((".yml", ".yaml"))], fichiers)

    def test_aucun_dossier_gitea(self) -> None:
        self.assertFalse([f for f in self.suivis(".gitea/workflows") if f.endswith((".yml", ".yaml"))])

    def test_le_workflow_github_reste(self) -> None:
        self.assertIn(".github/workflows/usine.yml", self.suivis(".github/workflows"))


if __name__ == "__main__":
    unittest.main()
