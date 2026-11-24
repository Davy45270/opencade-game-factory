"""HL-538 7-3316 (David, 2026-11-22) : les dessins de David sont sous CC BY-SA 4.0, attribués à « Davy45270 ».

Seule une licence non libre bloque encore la publication publique : un dessin de David passe la garde du registre
vers une destination publique quelconque (aucune autorisation de jeu), une licence non libre reste refusée."""
import glob
import json
import pathlib
import unittest

from tools.publish.licenses import PRIVATE_LICENSES, is_david_drawing, public_allowed

ROOT = pathlib.Path(__file__).resolve().parents[2]


def fiches(dossier):
    return [json.loads(pathlib.Path(p).read_text(encoding="utf-8")) for p in sorted(glob.glob(str(ROOT / "catalog" / dossier / "*.json")))]


class LicenceCcBySa(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = {a["id"]: a for a in fiches("assets")}
        cls.planches = {s["sha256"].lower() for s in fiches("sheets")}
        # Dessin de David (règle unique `is_david_drawing`) : hors icônes dessinées par du code (licence du code, MIT) et
        # hors fiches encore `unknown` (licence non prouvée, jamais publiée), depuis le retrait du nom complet du 24/11.
        cls.dessins = [a for a in cls.assets.values() if is_david_drawing(a) and a["license"] != "unknown"]

    def test_plus_aucune_licence_privee_au_catalogue(self):
        for dossier in ("assets", "sheets"):
            restes = [f["id"] for f in fiches(dossier) if f.get("license") == "LicenseRef-David-Prive-Tous-Droits-Reserves"]
            self.assertEqual(restes, [], dossier)

    def test_dessins_de_david_en_cc_by_sa_attribues_davy45270(self):
        self.assertGreater(len(self.dessins), 2000)
        for a in self.dessins:
            self.assertEqual(a["license"], "CC-BY-SA-4.0", a["id"])
            self.assertIn("7-3316", a["licenseEvidence"]["ref"], a["id"])
            self.assertIn("Davy45270", a["licenseEvidence"]["decision"], a["id"])
        self.assertTrue((ROOT / "LICENSES" / "CC-BY-SA-4.0.txt").is_file())
        self.assertIn("Davy45270", (ROOT / "ATTRIBUTION.md").read_text(encoding="utf-8"))

    def test_dessins_publiables_en_public_sans_autorisation_de_jeu(self):
        refuses = [a["id"] for a in self.dessins if a["sha256"].lower() not in self.planches
                   and a.get("publicExport") != "forbidden"
                   and not public_allowed(a, self.planches, self.assets.get, frozenset())]
        self.assertEqual(refuses, [])

    def test_licence_non_libre_toujours_refusee_en_public(self):
        a = dict(self.dessins[0], license="LicenseRef-David-Prive-Tous-Droits-Reserves")
        self.assertIn(a["license"], PRIVATE_LICENSES)
        self.assertFalse(public_allowed(a, set(), self.assets.get, frozenset()))


if __name__ == "__main__":
    unittest.main()
