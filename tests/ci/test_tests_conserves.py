"""Oracle ARCH-001 E030 (HL-525), écrit AVANT le code : « les tests instables sont identifiés, non masqués ; aucune
suppression de test pour faire passer la CI ».

`ci/scripts/tests-conserves.mjs` (copié par le gabarit dans `.woodpecker/usine/`, étape « tests conservés » BLOQUANTE)
compare la base et HEAD :
  - un fichier de test supprimé (non renommé), ou moins de cas de test (`it(` / `test(`) qu'à la base : ÉCHEC ;
  - un test masqué de plus (`.skip`, `.only`, `.fixme`, `.todo`, `xit(`, `xdescribe(`) : ÉCHEC (un test instable se
    signale, il ne se masque pas) ;
  - dérogation : un commit de base..HEAD porte le trailer `Tests-Retires: HL-n 7-n` (décision tracée), dite au rapport ;
  - base absente : ÉCHEC explicite (rien de prouvé, pas de vert muet).
Rapport : tests-conserves-rapport.json.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = RACINE / "ci" / "scripts" / "tests-conserves.mjs"
NODE = shutil.which("node")
DEUX = "import { it } from 'vitest'\nit('a', () => {})\nit('b', () => {})\n"


def git(d: pathlib.Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(NODE, "node absent")
class E030TestsConserves(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="tests-conserves-"))
        self.jeu = self.tmp / "jeu"
        self.ecrire({"src/a.test.ts": DEUX, "tests/e2e/b.spec.ts": "test('c', async () => {})\n",
                     "src/a.ts": "export const a = 1\n"})
        git(self.jeu, "init", "-q", "-b", "main")
        self.base = self.commit()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ecrire(self, fichiers: dict[str, str]) -> None:
        for chemin, texte in fichiers.items():
            (self.jeu / chemin).parent.mkdir(parents=True, exist_ok=True)
            (self.jeu / chemin).write_text(texte)

    def commit(self, message: str = "c") -> str:
        git(self.jeu, "add", "-A")
        git(self.jeu, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.jeu, "rev-parse", "HEAD")

    def lancer(self, base: str | None = None) -> tuple[int, dict]:
        r = subprocess.run([NODE, str(SCRIPT), "--base", base or self.base], cwd=self.jeu, capture_output=True,
                           text=True, timeout=60)
        rapport = self.jeu / "tests-conserves-rapport.json"
        return r.returncode, (json.loads(rapport.read_text()) if rapport.is_file() else {"stdout": r.stdout})

    def test_ajout_de_tests_passe(self) -> None:
        self.ecrire({"src/a.test.ts": DEUX + "it('nouveau', () => {})\n", "src/a.ts": "export const a = 2\n"})
        self.commit()
        rc, rap = self.lancer()
        self.assertEqual((rc, rap["status"]), (0, "ok"), rap)
        self.assertEqual((rap["avant"]["cas"], rap["apres"]["cas"]), (3, 4))

    def test_fichier_de_test_supprime_echoue(self) -> None:
        (self.jeu / "tests/e2e/b.spec.ts").unlink()
        self.commit()
        rc, rap = self.lancer()
        self.assertEqual((rc, rap["status"]), (1, "tests-retires"), rap)
        self.assertEqual(rap["fichiersSupprimes"], ["tests/e2e/b.spec.ts"])

    def test_renommage_n_est_pas_une_suppression(self) -> None:
        git(self.jeu, "mv", "tests/e2e/b.spec.ts", "tests/e2e/c.spec.ts")
        self.commit()
        rc, rap = self.lancer()
        self.assertEqual((rc, rap["status"]), (0, "ok"), rap)

    def test_cas_retire_echoue(self) -> None:
        self.ecrire({"src/a.test.ts": "import { it } from 'vitest'\nit('a', () => {})\n"})
        self.commit()
        rc, rap = self.lancer()
        self.assertEqual((rc, rap["status"]), (1, "tests-retires"), rap)

    def test_test_masque_echoue(self) -> None:
        self.ecrire({"src/a.test.ts": "import { it } from 'vitest'\nit('a', () => {})\nit.skip('b', () => {})\n"})
        self.commit()
        rc, rap = self.lancer()
        self.assertEqual((rc, rap["status"]), (1, "tests-masques"), rap)
        self.assertEqual((rap["avant"]["masques"], rap["apres"]["masques"]), (0, 1))

    def test_derogation_tracee_par_trailer(self) -> None:
        (self.jeu / "tests/e2e/b.spec.ts").unlink()
        self.commit("retire b\n\nTests-Retires: HL-525 7-3300")
        rc, rap = self.lancer()
        self.assertEqual((rc, rap["status"]), (0, "derogation"), rap)
        self.assertEqual(rap["derogation"], "HL-525 7-3300")

    def test_base_absente_echoue(self) -> None:
        rc, rap = self.lancer("inexistante")
        self.assertEqual((rc, rap["status"]), (1, "base-indisponible"), rap)


class E030EtapeDuGabarit(unittest.TestCase):
    def test_etape_bloquante_avant_les_tests(self) -> None:
        checks = (RACINE / "ci" / "gabarit" / "checks.yml").read_text()
        self.assertIn("node .woodpecker/usine/tests-conserves.mjs", checks)
        self.assertLess(checks.index("name: tests conservés"), checks.index("name: test\n"))


if __name__ == "__main__":
    unittest.main()
