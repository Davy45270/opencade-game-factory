"""La synchro part du main LOCAL : elle refuse de partir s'il diffère d'origin/main (26/11 : un main local en retard
de 60 commits ramenait l'ancienne licence et le nom complet de David sur 1 043 fiches)."""

import json
import subprocess
import sys
import unittest

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M


class SynchroMainAJour(unittest.TestCase):
    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        self.assertEqual(self.world.scan().code, 0)
        self.world.commiter_registre("Import de fixture")
        self.origine = self.world.racine / "origine.git"
        self.world.git(self.world.racine, "clone", "-q", "--bare", str(self.world.registre), str(self.origine))
        self.world.git(self.world.registre, "remote", "add", "origin", self.origine.as_uri())
        M.ajouter_commit(self.world, "jeu-a", {"public/assets/garde.png": M.png(M.uni(5, 6, (9, 99, 199, 255)))},
                         (), "2026-03-03T10:00:00Z", "Ajout pour la synchro")

    def sync(self):
        p = subprocess.run([sys.executable, str(self.world.registre / "assetctl"), "sync", "--branch", "sync/garde",
                            "--json"], cwd=self.world.registre, env=C.environnement(self.world.home),
                           capture_output=True, text=True, timeout=300)
        return p.returncode, json.loads(p.stdout)

    def branche(self):
        return self.world.git(self.world.registre, "for-each-ref", "--format=%(refname)", "refs/heads/sync/garde")

    def test_main_en_retard_sur_origin_refuse(self):
        travail = self.world.racine / "autre"
        self.world.git(self.world.racine, "clone", "-q", self.origine.as_uri(), str(travail))
        self.world.git(travail, "commit", "-q", "--allow-empty", "-m", "Fusion faite ailleurs")
        self.world.git(travail, "push", "-q", "origin", "main")
        main = self.world.git(self.world.registre, "rev-parse", "main")
        code, resultat = self.sync()
        self.assertEqual((code, resultat["error"]), (5, "sync-main-stale"), resultat)
        self.assertEqual(resultat["main"], main)
        self.assertNotEqual(resultat["originMain"], main)
        self.assertEqual(self.branche(), "")
        self.assertEqual(self.world.git(self.world.registre, "rev-parse", "main"), main)

    def test_main_en_avance_sur_origin_refuse(self):
        self.world.git(self.world.registre, "commit", "-q", "--allow-empty", "-m", "Commit local non publié")
        code, resultat = self.sync()
        self.assertEqual((code, resultat["error"]), (5, "sync-main-stale"), resultat)
        self.assertEqual(self.branche(), "")

    def test_origin_injoignable_refuse(self):
        self.world.git(self.world.registre, "remote", "set-url", "origin", (self.world.racine / "absent.git").as_uri())
        code, resultat = self.sync()
        self.assertEqual((code, resultat["error"]), (5, "sync-main-unverified"), resultat)
        self.assertEqual(self.branche(), "")

    def test_main_egal_a_origin_synchronise(self):
        code, resultat = self.sync()
        self.assertEqual(code, 0, resultat)
        self.assertEqual(self.branche(), "refs/heads/sync/garde")


if __name__ == "__main__":
    unittest.main()
