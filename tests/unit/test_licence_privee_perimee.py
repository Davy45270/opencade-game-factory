"""HL-538 7-3316 (David, 2026-11-22) : un provenance.json de jeu antérieur au 22/11 qui déclare encore la licence
privée de David est PÉRIMÉ et ne fait pas foi. Une découpe vérifiée d'une planche de David sort en CC-BY-SA-4.0,
attribuée à « Davy45270 », avec la décision 7-3316 pour preuve.

Rouge sur 525eccb (sync du 24/11) : la licence déclarée (`LicenseRef-David-Prive-Tous-Droits-Reserves`) était
recopiée telle quelle — 394 découpes de pestouille-rpg ressortaient « privées »."""
import json

from tests.acceptance import test_l7_correctifs as L7

PRIVEE = "LicenseRef-David-Prive-Tous-Droits-Reserves"


def _fichiers_jeu_prive():
    fichiers = L7._fichiers_jeu_l()
    provenance = json.loads(fichiers["assets/provenance.json"])
    for entree in provenance["assets"]:
        entree["licence"] = PRIVEE
    fichiers["assets/provenance.json"] = json.dumps(provenance, ensure_ascii=False, indent=2) + "\n"
    return fichiers


class LicencePriveePerimee(L7._Monde):
    def setUp(self):
        super().setUp()
        L7._ajouter_jeu(self, "jeu-l", _fichiers_jeu_prive())
        L7._scan(self)

    def test_decoupe_verifiee_sort_en_cc_by_sa_davy45270(self):
        _, fiche = L7._sprite(self, "sprite-l-conforme")
        self.assertEqual(fiche["provenance"].get("type"), "original-sheet-cut")
        self.assertEqual(fiche.get("license"), "CC-BY-SA-4.0", fiche.get("licenseEvidence"))
        self.assertIn("7-3316", fiche["licenseEvidence"]["ref"])
        self.assertIn("Davy45270", fiche["licenseEvidence"]["decision"])
        self.assertTrue(fiche["provenance"]["author"].startswith("Davy45270"), fiche["provenance"])

    def test_decoupe_non_verifiee_reste_unknown(self):
        _, fiche = L7._sprite(self, "sprite-l-ecart")
        self.assertEqual(fiche.get("license"), "unknown")
