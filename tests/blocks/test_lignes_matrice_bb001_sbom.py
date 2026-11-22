"""Oracles ligne par ligne de la matrice game-factory (HL-525), BB-001 § 9 et BB-09, écrits AVANT le code.

- E222 (BB-09) : SBOM CycloneDX des briques — chaque brique avec sa version (purl si elle est connue), sa licence, et
  les dépendances de chaque dépôt consommateur ; une version non résolue est DITE (jamais inventée).
- E210 : SPDX, SBOM, scan de vulnérabilités (trivy sur ce SBOM dans la CI de l'usine), dépendances épinglées.
"""
from __future__ import annotations

import json
import unittest

from ._outil import RACINE, Usine, fiche


def externe(id_, nom, version, licence, users):
    return fiche(id_, name=nom, kind="external-library", usedBy=users,
                 origin={"repositoryUrl": None, "licenseSpdx": licence, "commitSha": None, "version": version},
                 quality={"status": "discovered", "sbomRef": None, "securityReportRef": None},
                 discovery={"key": f"npm:{nom}@{version or 'unresolved'}", "ecosystem": "npm"})


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()
        self.u.poser(externe("BB-NPM-PHASER-001", "phaser", "3.80.1", "MIT", ["capsule-panic", "six-de-chaque"]))
        self.u.poser(externe("BB-NPM-HOWLER-001", "howler", None, "UNKNOWN", ["capsule-panic"]))
        self.out = self.u.tmp / "sbom.cdx.json"

    def tearDown(self) -> None:
        self.u.nettoyer()

    def sbom(self):
        r = self.u.bbctl("sbom", "--out", str(self.out), "--json")
        self.assertEqual(r.rc, 0, r)
        return r.json, json.loads(self.out.read_text())


class E222SbomVersionsEtDependances(Base):
    def test_composants_versions_purl_et_dependances(self) -> None:
        rapport, doc = self.sbom()
        self.assertEqual((doc["bomFormat"], doc["specVersion"]), ("CycloneDX", "1.5"))
        comps = {c["bom-ref"]: c for c in doc["components"]}
        phaser = comps["BB-NPM-PHASER-001"]
        self.assertEqual((phaser["version"], phaser["purl"]), ("3.80.1", "pkg:npm/phaser@3.80.1"))
        self.assertEqual(phaser["licenses"], [{"license": {"id": "MIT"}}])
        howler = comps["BB-NPM-HOWLER-001"]
        self.assertNotIn("purl", howler)                                       # version inconnue : pas de purl inventé
        self.assertNotIn("version", howler)
        self.assertEqual(rapport["unversioned"], ["BB-NPM-HOWLER-001"])
        self.assertEqual(rapport["licenseUnknown"], ["BB-NPM-HOWLER-001"])
        deps = {d["ref"]: d["dependsOn"] for d in doc["dependencies"]}
        self.assertEqual(deps["repo:capsule-panic"], ["BB-NPM-HOWLER-001", "BB-NPM-PHASER-001"])
        self.assertEqual(deps["repo:six-de-chaque"], ["BB-NPM-PHASER-001", "BB-SIX-PATHFINDING-001"])
        self.assertEqual(comps["BB-SIX-PATHFINDING-001"]["properties"][0], {"name": "bbctl:kind", "value": "game-local-module"})

    def test_deterministe(self) -> None:
        self.sbom()
        avant = self.out.read_bytes()
        self.sbom()
        self.assertEqual(self.out.read_bytes(), avant)


class E210ScanDansLaCiDeLUsine(unittest.TestCase):
    def test_sbom_des_briques_scanne_par_trivy_en_ci(self) -> None:
        texte = (RACINE / ".woodpecker" / "modules.yml").read_text()
        etapes = texte.split("\n  - name: ")
        sbom = next(e for e in etapes if e.startswith("sbom-briques"))
        self.assertIn("./bbctl sbom --out sbom-briques.cdx.json", sbom)
        scan = next(e for e in etapes if e.startswith("scan-briques"))
        self.assertIn("aquasec/trivy", scan)
        self.assertIn("trivy sbom", scan)
        self.assertIn("sbom-briques.cdx.json", scan)
        self.assertLess(texte.index("name: sbom-briques"), texte.index("name: scan-briques"))


if __name__ == "__main__":
    unittest.main()
