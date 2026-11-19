"""L8 — Correctifs différés (HL-538).

Constat remonté par les agents de Cozy et de Six (19/11) : `assetctl check-lock <chemin relatif>` résout le chemin
depuis le dossier du registre, pas depuis le répertoire courant de l'appelant (rc 4, « No such file »).

Contrat (coordinateur, HL-538, 19/11) : « les chemins relatifs se résolvent depuis le répertoire courant, avec un
test ». Boîte noire : `assetctl` lancé par sous-processus avec `cwd` = le dépôt du jeu. Fixtures synthétiques seulement.
"""

import subprocess
import sys
import unittest

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M

DEST = "public/assets/reutilise/fouet.png"


def _depuis(world, cwd, args):
    p = subprocess.run([sys.executable, str(world.registre / C.ASSETCTL), *args], cwd=cwd,
                       env=C.environnement(world.home), capture_output=True, text=True, timeout=C.DELAI)
    return C.Resultat(p.returncode, p.stdout, p.stderr, args)


class L8CheminsRelatifsDepuisLeRepertoireCourant(unittest.TestCase):
    """Contrat : un chemin relatif passé à la CLI (ici le lock de `check-lock`) se résout depuis le répertoire
    courant de l'appelant. Témoin : le même lock en chemin absolu rend 0."""

    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        r = self.world.scan()
        self.assertEqual(r.code, C.OK, f"fixture : scan\n{r}")
        self.world.commiter_registre("Catalogue importé")
        fouet = [i for i, a in C.assets(self.world.registre).items()
                 if any(l.get("repo") == "jeu-a" and l.get("path") == M.FOUET for l in a["files"]["locations"])]
        self.assertEqual(len(fouet), 1, fouet)
        self.jeu_b = self.world.depot("jeu-b")
        r = self.world.ctl(C.cmd_usage_add(fouet[0], "jeu-b", "Menu", "sprite", self.jeu_b, DEST, C.OPTION_CIBLE_PRIVEE))
        self.assertEqual(r.code, C.OK, f"fixture : usage add\n{r}")
        r = self.world.ctl(C.cmd_materialize(fouet[0], self.jeu_b / DEST, C.OPTION_CIBLE_PRIVEE))
        self.assertEqual(r.code, C.OK, f"fixture : materialize\n{r}")

    def test_temoin_chemin_absolu(self):
        r = _depuis(self.world, self.jeu_b, C.cmd_check_lock(self.jeu_b / C.LOCK_JEU))
        self.assertEqual(r.code, C.OK, f"témoin : chemin absolu\n{r}")

    def test_chemin_relatif_depuis_le_depot_du_jeu(self):
        r = _depuis(self.world, self.jeu_b, ["check-lock", C.LOCK_JEU, "--json"])
        self.assertEqual(r.code, C.OK, "un chemin relatif se résout depuis le répertoire courant de l'appelant, "
                                       f"pas depuis le registre\n{r}")


if __name__ == "__main__":
    unittest.main()
