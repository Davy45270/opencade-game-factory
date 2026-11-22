"""Liste de souhaits Kenney / OpenGameArt (décision de David, HL-538 22/11) : un agent ajoute sans réseau ; seul David
récupère, depuis un terminal interactif ; licence prouvée dans l'archive avant tout import."""
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest import TestCase

from tests.unit.test_ext001 import CC0, ExterneFixture, png

RACINE = Path(__file__).resolve().parents[2]
PAGE = "https://kenney.nl/assets/kitchen-kit"


class Souhaits(ExterneFixture, TestCase):
    def ajouter(self, *extra, code=0, page=PAGE, provider="kenney"):
        return self.ext("souhait", "ajouter", "--provider", provider, "--page", page, "--license", "CC0-1.0",
                        "--raison", "fouet propre pour la cuisine", "--jeu", "cuisine", *extra, code=code)

    def archive(self, licence=CC0):
        chemin = self.dehors() / "kenney_kitchen-kit.zip"
        with zipfile.ZipFile(chemin, "w") as z:
            z.writestr("PNG/whisk.png", png((3, 3, 3, 255)))
            z.writestr("License.txt", licence)
        return chemin

    def test_ajout_sans_reseau_versionne_et_sans_doublon(self):
        cree = self.ajouter()
        self.assertEqual(cree["status"], "created")
        self.assertEqual(self.ajouter()["status"], "unchanged")
        liste = json.loads((self.root / "external" / "souhaits.json").read_text())
        (s,) = liste["souhaits"]
        self.assertEqual((s["page"], s["licenceAnnoncee"], s["jeux"], s["statut"]),
                         (PAGE, "CC0-1.0", ["cuisine"], "a-recuperer"))
        self.ajouter(page="https://example.com/x", code=2)
        self.ajouter(provider="opengameart", code=2)                      # page d'un autre site

    def test_hors_terminal_interactif_refus_net(self):
        self.ajouter()
        p = subprocess.run([sys.executable, str(RACINE / "regctl"), "souhaits", "recuperer", "--tous", "--oui"],
                           stdin=subprocess.PIPE, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("terminal interactif", p.stdout)
        from tools.external.souhaits import recuperer
        self.assertEqual(recuperer(self.root, set(), True, True, afficher=lambda *a: None, terminal=False), 2)
        self.assertEqual(self.externals(), {})

    def test_david_confirme_licence_prouvee_import_et_statut(self):
        from tools.external.souhaits import recuperer
        self.ajouter()
        archive = self.archive()
        reponses = iter(["o", str(archive)])
        prs = []
        code = recuperer(self.root, set(), True, False, demander=lambda q: next(reponses), afficher=lambda *a: None,
                         terminal=True, ouvrir_pr=prs.append)
        self.assertEqual(code, 0)
        (fiche,) = self.externals().values()
        self.assertEqual((fiche["license"], fiche["provenance"]["external"]["sourceUrl"]), ("CC0-1.0", PAGE))
        (s,) = json.loads((self.root / "external" / "souhaits.json").read_text())["souhaits"]
        self.assertEqual(s["statut"], "importe")
        self.assertEqual(len(prs), 1)

    def test_licence_annoncee_non_prouvee_rien_n_est_importe(self):
        from tools.external.souhaits import recuperer
        self.ajouter()
        archive = self.archive(licence="Free for personal use only.\n")
        reponses = iter([str(archive)])
        code = recuperer(self.root, set(), True, True, demander=lambda q: next(reponses), afficher=lambda *a: None,
                         terminal=True)
        self.assertEqual(code, 1)
        self.assertEqual(self.externals(), {})
        (s,) = json.loads((self.root / "external" / "souhaits.json").read_text())["souhaits"]
        self.assertEqual(s["statut"], "licence-non-prouvee")

    def test_refus_de_confirmation_rien_n_est_fait(self):
        from tools.external.souhaits import recuperer
        self.ajouter()
        code = recuperer(self.root, set(), True, False, demander=lambda q: "n", afficher=lambda *a: None, terminal=True)
        self.assertEqual(code, 1)
        self.assertEqual(self.externals(), {})
