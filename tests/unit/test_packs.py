"""REG-09 (E109) packs d'assets versionnés et export contrôlé ; EXT-13 (E171) crédits générés à l'export.

Un pack est une liste figée {id, version, sha256, licence} sous un nom et une version semver : une version publiée est
immuable. L'export public refuse tout le pack si UNE ressource n'a pas de licence vérifiée (AT-08), et il écrit les
crédits (THIRD_PARTY_ASSETS.md), le manifeste de provenance, les textes de licence et le verrou du pack.
"""
import json
from unittest import TestCase

from tests.unit.test_ext001 import CC0, ExterneFixture, png
from tests.unit.test_oracles import ASSET_ID

CC_BY4 = "Creative Commons Attribution 4.0 International\nhttps://creativecommons.org/licenses/by/4.0/\n"


class Packs(ExterneFixture, TestCase):
    def importer(self, pack_id, couleur, licence="CC0-1.0", texte=CC0):
        self.pack(pack_id, {f"{pack_id}.png": png(couleur), "License.txt": texte}, license_spdx=licence)
        self.ext("import", "--plan", str(self.plan(pack_id)[0]))
        return next(i for i, a in self.externals().items() if a["provenance"]["external"]["externalPackId"] == pack_id)

    def pk(self, *args, code=0):
        resultat = self.cli("pack", *args)
        self.assertEqual(resultat[0], code, resultat[1])
        return resultat[1]

    def test_version_de_pack_figee_et_immuable(self):
        a = self.importer("kit-a", (10, 10, 10, 255))
        b = self.importer("kit-b", (20, 20, 20, 255), "CC-BY-4.0", CC_BY4)
        cree = self.pk("build", "cuisine", "--version", "1.0.0", "--asset", a, "--asset", b)
        self.assertEqual(cree["status"], "created")
        fichier = json.loads((self.root / "catalog" / "packs" / "cuisine" / "1.0.0.json").read_text())
        self.assertEqual([x["id"] for x in fichier["assets"]], sorted([a, b]))
        self.assertEqual(self.pk("build", "cuisine", "--version", "1.0.0", "--asset", a, "--asset", b)["status"],
                         "unchanged")
        refus = self.pk("build", "cuisine", "--version", "1.0.0", "--asset", a, code=5)
        self.assertEqual(refus["error"], "version-immutable")
        self.assertEqual(self.pk("build", "cuisine", "--version", "1.1.0", "--asset", a)["status"], "created")

    def test_export_public_refuse_si_une_licence_est_inconnue(self):
        a = self.importer("kit-a", (10, 10, 10, 255))
        self.pk("build", "melange", "--version", "1.0.0", "--asset", a, "--asset", ASSET_ID)
        destination = self.dehors() / "export"
        refus = self.pk("export", "melange", "--version", "1.0.0", "--target", "public", "--dest", str(destination),
                        code=3)
        self.assertIn(ASSET_ID, json.dumps(refus))
        self.assertFalse(destination.exists() and any(destination.iterdir()))

    def test_export_public_credits_provenance_licences_et_verrou(self):
        a = self.importer("kit-a", (10, 10, 10, 255))
        b = self.importer("kit-b", (20, 20, 20, 255), "CC-BY-4.0", CC_BY4)
        self.pk("build", "cuisine", "--version", "1.0.0", "--asset", a, "--asset", b)
        destination = self.dehors() / "export"
        res = self.pk("export", "cuisine", "--version", "1.0.0", "--target", "public", "--dest", str(destination))
        self.assertEqual(res["assets"], 2)
        credits = (destination / "THIRD_PARTY_ASSETS.md").read_text()
        self.assertIn("kenney / kit-b", credits)
        self.assertIn("CC-BY-4.0", credits)
        verrou = json.loads((destination / "pack.lock.json").read_text())
        self.assertEqual((verrou["name"], verrou["version"]), ("cuisine", "1.0.0"))
        self.assertTrue(list((destination / "LICENSES").glob("*.txt")))
        provenance = json.loads((destination / "provenance.json").read_text())
        self.assertEqual(sorted(r["id"] for r in provenance["assets"]), sorted([a, b]))

    def test_export_refuse_un_pack_dont_un_asset_a_change(self):
        a = self.importer("kit-a", (10, 10, 10, 255))
        self.pk("build", "cuisine", "--version", "1.0.0", "--asset", a)
        chemin = self.root / "catalog" / "packs" / "cuisine" / "1.0.0.json"
        pack = json.loads(chemin.read_text())
        pack["assets"][0]["sha256"] = "0" * 64
        chemin.write_text(json.dumps(pack))
        refus = self.pk("export", "cuisine", "--version", "1.0.0", "--target", "private", "--dest",
                        str(self.dehors() / "x"), code=5)
        self.assertEqual(refus["error"], "pack-stale")
