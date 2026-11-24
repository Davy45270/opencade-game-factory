"""HL-538 7-3316, arbitrage du 2026-11-24 : TOUS les dessins de David (Cozy et Capsule compris) sont en CC-BY-SA-4.0,
attribués à « Davy45270 ». Son nom complet n'apparaît dans aucun fichier du dépôt (vie privée) ; il n'est connu que
par son empreinte (`licenses.DAVID_FULL_NAME_SHA256`).

Rouge sur 350bd5e3 : 1 386 fiches en CC-BY-4.0 (Capsule Panic, Cozy Room Sort, Six de chaque) et 1 334 fiches portant
le nom complet."""
import glob
import hashlib
import json
import pathlib
import subprocess
import unittest
from unittest import mock

from tools.publish import licenses

ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMOIN = "David Témoin"  # nom témoin : le vrai nom complet n'est écrit nulle part


def fiches(dossier):
    for p in sorted(glob.glob(str(ROOT / "catalog" / dossier / "**" / "*.json"), recursive=True)):
        yield p, json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


class DessinsDeDavid(unittest.TestCase):
    def test_aucun_nom_complet_dans_le_depot(self):
        """Tout fichier suivi (catalogue, generated/, scripts, tests…), reconnu par l'empreinte du nom."""
        suivis = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.split(b"\0")
        restes = []
        for nom in filter(None, suivis):
            chemin = ROOT / nom.decode()
            if not chemin.is_file():
                continue
            texte = chemin.read_bytes().decode("utf-8", errors="ignore")
            if "avid" in texte and licenses.without_full_name(texte) != texte:
                restes.append(nom.decode())
        self.assertEqual(restes, [])

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
        empreinte = hashlib.sha256(TEMOIN.lower().encode()).hexdigest()
        with mock.patch.object(licenses, "DAVID_FULL_NAME_SHA256", empreinte):
            fiche = {"license": "CC-BY-4.0", "licenseEvidence": {"method": "m", "ref": "r", "decision": "d"},
                     "provenance": {"author": f"{TEMOIN} (LICENCES.md du jeu)",
                                    "evidence": [f"par {TEMOIN.upper()}", "david  témoin", "David Autre"]},
                     "versions": [{"license": "CC-BY-4.0"}]}
            licenses.david_drawing(fiche)
            self.assertNotIn("émoin", json.dumps(fiche, ensure_ascii=False).lower())
            self.assertEqual(fiche["provenance"]["evidence"], ["par Davy45270", "Davy45270", "David Autre"])
            self.assertEqual((fiche["license"], fiche["versions"][0]["license"]), ("CC-BY-SA-4.0", "CC-BY-SA-4.0"))
            self.assertIn("7-3316", fiche["licenseEvidence"]["ref"])
            icone = {"license": "MIT", "provenance": {"author": f"{TEMOIN} (icônes dessinées par le code de x)"}}
            licenses.david_drawing(icone)
            self.assertEqual((icone["license"], icone["provenance"]["author"]),
                             ("MIT", "Davy45270 (icônes dessinées par le code de x)"))
