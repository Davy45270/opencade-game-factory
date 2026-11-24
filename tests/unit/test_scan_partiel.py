"""Un scan ou une sync `--only` ne doit pas effacer la mise à l'écart des copies divergentes des AUTRES jeux.

Défaut vu le 24/11 (HL-538, E072) : `generated/reports/migration.json` était réécrit avec les seuls dépôts du
dernier `--only`. `scan-repos --verify` lit ses `divergentCopies` (imported: false) pour ne pas compter en dérive
les copies laissées de côté exprès (7901d3c) : une sync des jeux A faisait donc réapparaître en dérive les copies
écartées des jeux B, et le cron de réconciliation repassait rouge sans aucune dérive réelle.
"""

import json
import unittest

from tests.acceptance import _contrat as C
from tests.unit import test_correctifs_inventaire as inventaire
from tools.core.exit_codes import ExitCode


class ScanPartielGardeLesEcarts(unittest.TestCase):
    setUp = inventaire.VerifyCopiesDivergentes.setUp
    _verify = inventaire.VerifyCopiesDivergentes._verify

    def _scanner_jeu_b(self):
        mirror = self.world.cache / "local" / "jeu-b.git"
        mirror.parent.mkdir(parents=True, exist_ok=True)
        self.world.git(self.world.depot("jeu-b"), "clone", "--mirror", "--no-local",
                       self.world.depot("jeu-b").as_uri(), str(mirror))
        result = self.world.scan("--no-fetch", "--only", "jeu-b")
        self.assertEqual(result.code, C.OK, str(result))

    def _ecarts(self):
        rapport = json.loads((self.world.registre / "generated" / "reports" / "migration.json").read_text())
        return {(repo["name"], item["provider"]) for repo in rapport["repositories"]
                for item in repo.get("divergentCopies", []) if item.get("imported") is False}

    def test_scan_only_d_un_autre_jeu_garde_les_ecarts(self):
        self.assertEqual(self._ecarts(), {("jeu-a", "github"), ("jeu-a", "forgejo")})
        self._scanner_jeu_b()
        self.assertEqual(self._ecarts(), {("jeu-a", "github"), ("jeu-a", "forgejo")})
        noms = [repo["name"] for repo in json.loads(
            (self.world.registre / "generated" / "reports" / "migration.json").read_text())["repositories"]]
        self.assertEqual(sorted(noms), ["jeu-a", "jeu-b"])

    def test_verify_reste_vert_apres_le_scan_d_un_autre_jeu(self):
        self._scanner_jeu_b()
        code, report = self._verify()
        self.assertEqual(report["drift"], [], report)
        self.assertEqual(code, ExitCode.OK, report)

    def test_un_jeu_rescanne_remplace_sa_propre_entree(self):
        # Le jeu rescanné n'apparaît qu'une fois : son entrée est remplacée, pas dupliquée.
        result = self.world.scan("--no-fetch", "--only", "jeu-a")
        self.assertEqual(result.code, C.OK, str(result))
        noms = [repo["name"] for repo in json.loads(
            (self.world.registre / "generated" / "reports" / "migration.json").read_text())["repositories"]]
        self.assertEqual(noms.count("jeu-a"), 1)


if __name__ == "__main__":
    unittest.main()
