"""Une copie GitHub PRIVÉE illisible faute de jeton est « non vérifiable (dette E006) », pas une panne du contrôle.

Décision du 24/11 (HL-538, E072). La source `asset` est un dépôt GitHub privé, et le jeton GitHub à privilèges
minimaux est reporté (E006, « plus tard » de David). Un cron de réconciliation rouge en permanence pour cette raison
masquerait toute nouvelle dérive. `scan-repos --verify` range donc cette copie dans `unverifiable` : elle est
affichée dans le rapport, ne fait pas échouer le contrôle, et revient dans le verdict dès qu'elle est lisible.
Avec un jeton fourni, un échec reste une erreur : seule l'absence de jeton est une dette connue.
"""

import argparse
import json
import os
import unittest
from unittest import mock

from tests.acceptance import _contrat as C
from tests.unit import test_correctifs_inventaire as inventaire
from tests.unit.test_branche_defaut import _sources
from tools.core.exit_codes import ExitCode
from tools.discovery import scan
from tools.discovery.repos import Git, GitError


class SourcePriveeNonVerifiable(unittest.TestCase):
    setUp = inventaire.VerifyCopiesDivergentes.setUp

    def _privee(self):
        def mutate(document):
            source = next(e for e in document["sources"] if e["name"] == "jeu-a")
            next(c for c in source["copies"] if c["provider"] == "github")["visibility"] = "private"
        _sources(self.world, mutate)

    def _verify(self, github_lisible):
        args = argparse.Namespace(command="scan-repos", verify=True, fetch=True, dry_run=True, only=["jeu-a"],
                                  provider=None, sources=None, cache=self.world.cache, job=None, log=None, json=True)
        root = self.world.registre
        copies = scan.preflight(root, args)
        mirrors = {provider: self.world.cache / provider / "jeu-a.git" for provider in ("github", "forgejo")}
        original = Git.remote_head

        def remote_head(git, copy):
            if copy.provider == "local":
                return original(git, copy)
            if copy.provider == "github" and not github_lisible:
                raise GitError("Git ls-remote a échoué (code 128).")
            return git.run("rev-parse", "HEAD^{commit}", mirror=mirrors[copy.provider]).decode().strip(), "main"

        with mock.patch.object(Git, "remote_head", remote_head):
            return scan.run(root, args, copies)

    def _sans_jeton(self):
        env = {k: v for k, v in os.environ.items() if k != "ASSETCTL_GITHUB_TOKEN" and not k.startswith("GIT_CONFIG_")}
        return mock.patch.dict(os.environ, env, clear=True)

    def test_privee_sans_jeton_non_verifiable_sans_echec(self):
        self._privee()
        with self._sans_jeton():
            code, report = self._verify(github_lisible=False)
        self.assertEqual(report["errors"], [], report)
        self.assertEqual([(u["name"], u["provider"]) for u in report["unverifiable"]], [("jeu-a", "github")], report)
        self.assertIn("E006", report["unverifiable"][0]["reason"])
        self.assertEqual(code, ExitCode.OK, report)

    def test_avec_jeton_l_echec_reste_une_erreur(self):
        self._privee()
        with self._sans_jeton(), mock.patch.dict(os.environ, {"ASSETCTL_GITHUB_TOKEN": "x" * 40}):
            code, report = self._verify(github_lisible=False)
        self.assertEqual(report["unverifiable"], [], report)
        self.assertIn(("jeu-a", "github"), [(e["name"], e["provider"]) for e in report["errors"]], report)

    def test_publique_illisible_reste_une_erreur(self):
        with self._sans_jeton():
            code, report = self._verify(github_lisible=False)
        self.assertEqual(report["unverifiable"], [], report)
        self.assertIn(("jeu-a", "github"), [(e["name"], e["provider"]) for e in report["errors"]], report)

    def test_redevenue_lisible_elle_revient_dans_le_verdict(self):
        self._privee()
        with self._sans_jeton():
            code, report = self._verify(github_lisible=True)
        self.assertEqual(report["unverifiable"], [], report)
        self.assertEqual(report["errors"], [], report)
        self.assertIn(("jeu-a", "github"), [(d["name"], d["provider"]) for d in report["divergent"]], report)


if __name__ == "__main__":
    unittest.main()
