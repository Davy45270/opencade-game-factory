"""Défauts vus à l'inventaire réel du 19/11 (HL-538), tests écrits avant le correctif (auteur : Claude).

1. `generated/reports/licenses-unknown.json` changeait d'ORDRE entre deux imports identiques (AT-04 exige des
   sorties identiques à l'octet) : le rapport doit être trié par ID.
2. `scan-repos --verify` classait en « dérive » (code 1) les copies divergentes que le scan n'importe pas
   exprès (7901d3c) : elles doivent apparaître comme `divergent`, sans faire échouer le contrôle.
"""

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M
from tests.unit.test_branche_defaut import ROUGE, _avec_copies_distantes, _miroir_local
from tools.core.exit_codes import ExitCode
from tools.discovery import scan
from tools.discovery.repos import Git
from tools.index import reports


def _asset(asset_id):
    return {"id": asset_id, "license": "unknown", "usages": [],
            "files": {"locations": [{"repo": "jeu", "path": f"{asset_id}.png"}]}}


class RapportLicencesDeterministe(unittest.TestCase):
    def _emettre(self, root, assets):
        reports.emit(root, [], [], [], assets, (), [], (), ())
        return (root / "generated" / "reports" / "licenses-unknown.json").read_bytes()

    def test_ordre_des_assets_sans_effet_sur_le_rapport(self):
        ids = ["asset-image-c-0001", "asset-image-a-0001", "asset-image-b-0001"]
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            first = self._emettre(Path(one), [_asset(i) for i in ids])
            second = self._emettre(Path(two), [_asset(i) for i in reversed(ids)])
        self.assertEqual(first, second, "deux imports identiques doivent donner le même rapport à l'octet")
        self.assertEqual([a["id"] for a in json.loads(first)["assets"]], sorted(ids))


class VerifyCopiesDivergentes(unittest.TestCase):
    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        _avec_copies_distantes(self.world)
        depot = self.world.depot("jeu-a")
        (depot / M.FOUET).write_bytes(M.png(M.uni(16, 16, ROUGE)))
        self.world.git(depot, "add", "--", M.FOUET)
        self.world.git(depot, "commit", "-q", "-m", "Local en avance", date="2026-03-02T10:00:00+00:00")
        self.ahead = self.world.git(depot, "rev-parse", "HEAD")
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
            commit = git.run("rev-parse", "HEAD^{commit}", mirror=mirrors[copy.provider]).decode().strip()
            return commit, "main"

        with mock.patch.object(Git, "remote_head", remote_head):
            return scan.run(root, args, copies)

    def test_copie_divergente_classee_divergente_pas_derive(self):
        code, report = self._verify()
        self.assertEqual(report["drift"], [], report)
        self.assertIn({"name": "jeu-a", "provider": "local", "remoteCommit": self.ahead},
                      [{k: d[k] for k in ("name", "provider", "remoteCommit")} for d in report.get("divergent", [])])
        self.assertEqual(code, ExitCode.OK, report)

    def test_vraie_derive_toujours_signalee(self):
        # La copie GitHub importée avance après le scan : c'est une dérive, code 1.
        mirror = self.world.cache / "github" / "jeu-a.git"
        self.world.git(mirror, "fetch", "-q", str(self.world.depot("jeu-a")), "+refs/heads/main:refs/heads/main")
        code, report = self._verify()
        self.assertIn("github", [d["provider"] for d in report["drift"]], report)
        self.assertEqual(code, ExitCode.CHECK_FAILED, report)


if __name__ == "__main__":
    unittest.main()
