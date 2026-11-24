"""`scan-repos --verify` ne doit pas inventorier la référence figée d'une copie divergente écartée (7901d3c).

Défaut vu le 24/11 (HL-538, E072) : la copie GitHub d'opencadkid (5d57bd8) est en retard sur la forge (485b812), donc
écartée ; sa référence reste figée au dernier commit importé, mais le catalogue ne garde plus d'emplacement à ce commit
(la source est rechargée depuis la copie qui fait foi). --verify inventoriait quand même ce commit figé et rendait
11 fichiers « oubliés » (code 1) : aucune dérive réelle, et le cron de réconciliation restait rouge.
Une copie écartée reste signalée dans `divergent` ; elle n'est ni inventoriée ni exigée.
"""

import argparse
import json
import shutil
import unittest
from unittest import mock

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M
from tests.unit.test_branche_defaut import ROUGE, _avec_copies_distantes, _miroir_local
from tools.core.exit_codes import ExitCode
from tools.discovery import scan
from tools.discovery.repos import Git


class VerifyCopieEcartee(unittest.TestCase):
    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        # Sans tag : seule la référence figée des copies écartées porte le commit d'origine (cas d'opencadkid).
        self.world.git(self.world.depot("jeu-a"), "tag", "-d", "v1.0")
        _avec_copies_distantes(self.world)
        _miroir_local(self.world)
        # 1. Les trois copies au même commit : toutes importées, références posées.
        result = self.world.scan("--no-fetch", "--only", "jeu-a")
        self.assertEqual(result.code, C.OK, str(result))
        # 2. La copie locale avance et change le fouet : GitHub et Forgejo, en retard, sont écartées.
        depot = self.world.depot("jeu-a")
        (depot / M.FOUET).write_bytes(M.png(M.uni(16, 16, ROUGE)))
        self.world.git(depot, "add", "--", M.FOUET)
        self.world.git(depot, "commit", "-q", "-m", "Local en avance", date="2026-03-02T10:00:00+00:00")
        shutil.rmtree(self.world.cache / "local" / "jeu-a.git")
        _miroir_local(self.world)
        result = self.world.scan("--no-fetch", "--only", "jeu-a")
        self.assertEqual(result.code, C.OK, str(result))

    def _verify(self):
        args = argparse.Namespace(command="scan-repos", verify=True, fetch=True, dry_run=False, only=["jeu-a"],
                                  provider=None, sources=None, cache=self.world.cache, job=None, log=None, json=True)
        root = self.world.registre
        copies = scan.preflight(root, args)
        mirrors = {provider: self.world.cache / provider / "jeu-a.git" for provider in ("github", "forgejo")}
        original = Git.remote_head

        def remote_head(git, copy):
            if copy.provider == "local":
                return original(git, copy)
            return git.run("rev-parse", "HEAD^{commit}", mirror=mirrors[copy.provider]).decode().strip(), "main"

        with mock.patch.object(Git, "remote_head", remote_head):
            return scan.run(root, args, copies)

    def _retirer(self, provider, toutes_copies=False):
        """Retire du catalogue les emplacements de la copie `provider` à son commit de référence : c'est l'état réel
        d'opencadkid (11 fiches gardaient, pour GitHub, un emplacement à un ancien commit 69948ce au lieu de 5d57bd8)."""
        refs = json.loads((self.world.registre / "catalog" / "scan-references.json").read_text())
        commit = next(r["commit"] for r in refs["references"] if r["name"] == "jeu-a" and r["provider"] == provider)
        for chemin in (self.world.registre / "catalog" / "assets").glob("*.json"):
            fiche = json.loads(chemin.read_text())
            avant = len(fiche["files"]["locations"])
            fiche["files"]["locations"] = [l for l in fiche["files"]["locations"]
                                           if not (l["commit"] == commit
                                                   and (toutes_copies or l.get("provider") == provider))]
            if len(fiche["files"]["locations"]) != avant:
                chemin.write_text(json.dumps(fiche))
        return commit

    def test_copie_ecartee_ni_inventoriee_ni_oubliee(self):
        ecartes = {(repo["name"], item["provider"]) for repo in json.loads(
            (self.world.registre / "generated" / "reports" / "migration.json").read_text())["repositories"]
            for item in repo.get("divergentCopies", []) if item.get("imported") is False}
        self.assertEqual(ecartes, {("jeu-a", "github"), ("jeu-a", "forgejo")})
        # Plus aucun emplacement au commit figé des copies écartées (aucune autre copie ne le porte, comme 5d57bd8).
        self._retirer("github", toutes_copies=True)
        code, report = self._verify()
        self.assertEqual(report["forgotten"], [], report)
        self.assertEqual(report["drift"], [], report)
        self.assertEqual(code, ExitCode.OK, report)

    def test_la_copie_qui_fait_foi_reste_inventoriee(self):
        # Un fichier de la copie importée absent du catalogue reste « oublié » : le contrôle n'est pas affaibli.
        tete = self._retirer("local")
        code, report = self._verify()
        self.assertIn({"repo": "jeu-a", "commit": tete, "path": M.FOUET}, report["forgotten"], report)
        self.assertEqual(code, ExitCode.CHECK_FAILED, report)


if __name__ == "__main__":
    unittest.main()
