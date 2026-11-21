"""Oracles du lot 3 REG-003 (HL-525), écrits AVANT le code : index générés reconstructibles (§ 3, T10) et SBOM de
specctl avec licences des dépendances (§ 9).

Index : `specctl index --out <dossier>` écrit search-index.json, dependency-graph.json et coverage.json, octet pour
octet identiques d'une reconstruction à l'autre ; `--check` compare au dossier existant sans rien écrire (périmé = 2).
SBOM : `specctl sbom --out <fichier>` décrit la fermeture des dépendances Python de specctl (CycloneDX 1.5), chaque
composant avec sa licence lue dans les métadonnées installées ; une licence hors politique rend 2.
"""
from __future__ import annotations

import json
import shutil
import unittest

from ._outil import Docs

FICHIERS = ("coverage.json", "dependency-graph.json", "search-index.json")


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()
        r = self.d.specctl("import", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 0, r)
        self.out = self.d.tmp / "generated-specs"

    def tearDown(self) -> None:
        self.d.nettoyer()

    def octets(self) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in sorted(self.out.iterdir())}


class IndexReconstructibles(Base):
    def test_T10_restauration_des_index_memes_resultats(self) -> None:
        r = self.d.specctl("index", "--out", str(self.out), "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), list(FICHIERS))
        avant = self.octets()
        shutil.rmtree(self.out)                                               # index perdus
        self.assertEqual(self.d.specctl("index", "--out", str(self.out), "--json").rc, 0)
        self.assertEqual(self.octets(), avant)                                # reconstruits à l'identique

    def test_contenu_des_index(self) -> None:
        self.d.specctl("index", "--out", str(self.out), "--json")
        recherche = json.loads((self.out / "search-index.json").read_text())
        self.assertIn("REQ-JEU-A-E002", {e["id"] for e in recherche["entries"]})
        graphe = json.loads((self.out / "dependency-graph.json").read_text())
        self.assertEqual(sorted(n["id"] for n in graphe["nodes"]), ["SPEC-JEU-A", "SPEC-JEU-B"])
        couverture = json.loads((self.out / "coverage.json").read_text())
        self.assertEqual(couverture["SPEC-JEU-A"]["applicable"], 2)

    def test_check_detecte_un_index_perime_sans_ecrire(self) -> None:
        self.d.specctl("index", "--out", str(self.out), "--json")
        self.assertEqual(self.d.specctl("index", "--out", str(self.out), "--check", "--json").rc, 0)
        (self.out / "coverage.json").write_text("{}\n")
        r = self.d.specctl("index", "--out", str(self.out), "--check", "--json")
        self.assertEqual(r.rc, 2, r)
        self.assertEqual(r.json["stale"], ["coverage.json"])
        self.assertEqual((self.out / "coverage.json").read_text(), "{}\n")     # --check n'écrit jamais

    def test_check_index_absent(self) -> None:
        r = self.d.specctl("index", "--out", str(self.out), "--check", "--json")
        self.assertEqual(r.rc, 2, r)


class SbomSpecctl(Base):
    def test_sbom_fermeture_et_licences(self) -> None:
        f = self.d.tmp / "specctl.cdx.json"
        r = self.d.specctl("sbom", "--out", str(f), "--json")
        self.assertEqual(r.rc, 0, r)
        bom = json.loads(f.read_text())
        self.assertEqual((bom["bomFormat"], bom["specVersion"]), ("CycloneDX", "1.5"))
        noms = {c["name"].lower() for c in bom["components"]}
        self.assertIn("jsonschema", noms)
        self.assertIn("referencing", noms)                                    # dépendance transitive, pas seulement directe
        for c in bom["components"]:
            self.assertTrue(c["purl"].startswith("pkg:pypi/"), c)
            self.assertTrue(c.get("licenses"), c)                             # chaque licence est relevée

    def test_licence_hors_politique_non_conforme(self) -> None:
        f = self.d.tmp / "specctl.cdx.json"
        r = self.d.specctl("sbom", "--out", str(f), "--allow", "GPL-3.0-only", "--json")
        self.assertEqual(r.rc, 2, r)
        self.assertTrue(r.json["violations"], r)


if __name__ == "__main__":
    unittest.main()
