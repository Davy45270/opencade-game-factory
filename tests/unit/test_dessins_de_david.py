"""HL-538 7-3316, arbitrage du 2026-11-24 : TOUS les dessins de David (Cozy et Capsule compris) sont en CC-BY-SA-4.0,
attribués à « Davy45270 ». Son nom complet n'apparaît dans aucune fiche du catalogue (vie privée).

Rouge sur 350bd5e3 : 1 386 fiches en CC-BY-4.0 (Capsule Panic, Cozy Room Sort, Six de chaque) et 1 334 fiches portant
le nom complet."""
import glob
import json
import pathlib
import unittest

from tools.publish import licenses

ROOT = pathlib.Path(__file__).resolve().parents[2]
NOM_COMPLET = licenses.DAVID_FULL_NAME


def fiches(dossier):
    for p in sorted(glob.glob(str(ROOT / "catalog" / dossier / "**" / "*.json"), recursive=True)):
        yield p, json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


class DessinsDeDavid(unittest.TestCase):
    def test_aucun_nom_complet_au_catalogue(self):
        restes = [p for p in glob.glob(str(ROOT / "catalog" / "**" / "*.json"), recursive=True)
                  if NOM_COMPLET in pathlib.Path(p).read_text(encoding="utf-8")]
        self.assertEqual(len(restes), 0, restes[:5])

    def test_dessin_de_david_cc_by_sa_davy45270(self):
        ecarts, n = [], 0
        for dossier in ("assets", "sheets"):
            for _, f in fiches(dossier):
                if not licenses.is_david_drawing(f) or f.get("license") == "unknown":
                    continue
                n += 1
                auteur = f["provenance"]["author"]
                if f["license"] != "CC-BY-SA-4.0" or not auteur.startswith(licenses.DAVID_ATTRIBUTION):
                    ecarts.append((f["id"], f["license"], auteur[:40]))
                elif "7-3316" not in f["licenseEvidence"]["ref"]:
                    ecarts.append((f["id"], "preuve", f["licenseEvidence"]["ref"][:40]))
        self.assertGreater(n, 4000)
        self.assertEqual(ecarts, [], f"{len(ecarts)} écarts")

    def test_plus_aucune_decision_cc_by_du_19_11(self):
        restes = [f["id"] for _, f in fiches("assets") if f.get("license") == "CC-BY-4.0"
                  and (f.get("licenseEvidence") or {}).get("decision") == licenses.DAVID_DECISION]
        self.assertEqual(restes, [])

    def test_normaliseur(self):
        fiche = {"license": "CC-BY-4.0", "licenseEvidence": {"method": "m", "ref": "r", "decision": "d"},
                 "provenance": {"author": f"{NOM_COMPLET} (LICENCES.md du jeu)", "evidence": [f"par {NOM_COMPLET}"]},
                 "versions": [{"license": "CC-BY-4.0"}]}
        licenses.david_drawing(fiche)
        self.assertNotIn(NOM_COMPLET, json.dumps(fiche, ensure_ascii=False))
        self.assertEqual((fiche["license"], fiche["versions"][0]["license"]), ("CC-BY-SA-4.0", "CC-BY-SA-4.0"))
        self.assertIn("7-3316", fiche["licenseEvidence"]["ref"])
        icone = {"license": "MIT", "provenance": {"author": f"{NOM_COMPLET} (icônes dessinées par le code de x)"}}
        licenses.david_drawing(icone)
        self.assertEqual((icone["license"], icone["provenance"]["author"]),
                         ("MIT", "Davy45270 (icônes dessinées par le code de x)"))
