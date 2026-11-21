"""HL-538 : les usages des cadres livrés (scripts/importer_livre.py) survivent au scan du code des dépôts."""
import types
from unittest import TestCase

from tools.discovery.snapshots import DELIVERED_MARK, _reconcile_usages
from tools.publish.licenses import PRIVATE_LICENSES, public_allowed


def usage(evidence):
    return {"repo": "jeu", "provider": "forgejo", "game": "jeu", "scene": "public/assets/a.json", "commit": "a" * 40,
            "codeRef": {"path": "public/assets/a.json", "line": 3}, "importName": "sprite-x", "role": "atlas-frame",
            "assetPath": "public/assets/a.webp", "assetVersion": 1, "status": "active", "releases": [],
            "evidence": [evidence]}


class UsagesLivres(TestCase):
    def reconcilier(self, use):
        asset = {"id": "asset-sprite-x-0001", "usages": [use]}
        tree = {"public/assets/a.webp": types.SimpleNamespace(oid="b" * 40)}
        target = types.SimpleNamespace(changed=set())
        _reconcile_usages(asset, {("jeu", "forgejo"): ("c" * 40, tree)}, (), target)
        return asset["usages"]

    def test_usage_de_cadre_livre_garde_par_le_scan(self):
        livre = usage(f"{DELIVERED_MARK} : cadre sprite-x de public/assets/a.webp")
        self.assertEqual(self.reconcilier(livre), [livre])

    def test_usage_du_code_non_revu_retire_par_le_scan(self):
        self.assertEqual(self.reconcilier(usage("literal: public/assets/a.webp")), [])


PRIVEE = next(iter(PRIVATE_LICENSES))
PREUVE = {"method": "decision", "ref": "HL-538 7-3162", "decision": "test"}


def fiche(ident, sha, licence=PRIVEE, parent=None):
    a = {"id": ident, "sha256": sha, "license": licence, "licenseEvidence": PREUVE, "provenance": {"type": "repo-file"}}
    if parent:
        a["provenance"] = {"type": "derived", "derivedFrom": parent["id"], "parentId": parent["id"],
                           "parentVersion": 1, "parentSha256": parent["sha256"]}
    return a


class GardeCadreLivre(TestCase):
    """Un cadre livré (dérivé d'une découpe brute de David, même licence privée) passe vers un jeu de David seul."""
    brut = fiche("asset-sprite-x-0001", "1" * 64)
    cadre = fiche("asset-sprite-jeu-x-c-0001", "2" * 64, parent=brut)

    def garde(self, cadre, granted):
        return public_allowed(cadre, set(), {self.brut["id"]: self.brut}.get, granted)

    def test_cadre_derive_prive_passe_vers_un_jeu_de_david(self):
        self.assertTrue(self.garde(self.cadre, PRIVATE_LICENSES))

    def test_cadre_derive_prive_refuse_hors_jeu_de_david(self):
        self.assertFalse(self.garde(self.cadre, frozenset()))

    def test_cadre_derive_sous_une_autre_licence_refuse(self):
        self.assertFalse(self.garde({**self.cadre, "license": "CC0-1.0"}, PRIVATE_LICENSES))


import importlib.util as _iu  # noqa: E402
import json as _json  # noqa: E402
import tempfile as _tf  # noqa: E402
from pathlib import Path as _P  # noqa: E402

_spec = _iu.spec_from_file_location("importer_livre", _P(__file__).resolve().parents[2] / "scripts/importer_livre.py")
il = _iu.module_from_spec(_spec)
_spec.loader.exec_module(il)


class PorteeMonorepo(TestCase):
    """Un jeu d'un monorepo = son sous-dossier ; la coquille = tout le reste."""
    fichiers = ["src/games/a/x.png", "src/games/a/sous/y.png", "src/games/b/z.png", "public/icons/i.png", "src/main.ts"]
    profil = {"monorepo": "src/games"}

    def test_sous_jeu_limite_a_son_dossier(self):
        dans = il.portee("depot/a", self.profil, self.fichiers)
        self.assertEqual([f for f in self.fichiers if dans(f)], ["src/games/a/x.png", "src/games/a/sous/y.png"])

    def test_coquille_hors_des_dossiers_de_jeux(self):
        dans = il.portee("depot", self.profil, self.fichiers)
        self.assertEqual([f for f in self.fichiers if dans(f)], ["public/icons/i.png", "src/main.ts"])

    def test_sous_jeu_absent_refuse(self):
        with self.assertRaises(SystemExit):
            il.portee("depot/c", self.profil, self.fichiers)

    def test_depot_simple_tout_le_depot(self):
        dans = il.portee("jeu", {}, self.fichiers)
        self.assertTrue(all(dans(f) for f in self.fichiers))


class TablesDeProvenance(TestCase):
    """provenance.json (un dessin = planche + boîte) → une table de découpe par atlas."""

    def test_une_table_par_atlas(self):
        with _tf.TemporaryDirectory() as d:
            (_P(d) / "prov.json").write_text(_json.dumps([
                {"id": "lit", "atlas": "p01", "origine": {"planche": "P1.webp", "boite": [10, 20, 1, 2], "marge": 6}},
                {"id": "son", "origine": "Synthétisé"},
                {"id": "pot", "atlas": "p02", "origine": {"planche": "P2.webp", "boite": [5, 5, 0, 0]}}]))
            t = il.tables_des_atlas(_P(d), {"parents": "provenance", "provenance": "prov.json"})
        self.assertEqual(sorted(t), ["p01", "p02"])
        rel, nom, table, _ = t["p01"]
        self.assertEqual((rel, nom, table["planche"]), ("prov.json", "p01.provenance.json", "P1.webp"))
        self.assertEqual(table["elements"], [{"id": "lit", "boite": [10, 20, 1, 2], "marge": 6, "transformations": []}])

    def test_atlas_melant_deux_planches_refuse(self):
        with _tf.TemporaryDirectory() as d:
            (_P(d) / "prov.json").write_text(_json.dumps([
                {"id": "a", "atlas": "p01", "origine": {"planche": "P1.webp", "boite": [1, 1, 0, 0]}},
                {"id": "b", "atlas": "p01", "origine": {"planche": "P2.webp", "boite": [1, 1, 0, 0]}}]))
            with self.assertRaises(SystemExit):
                il.tables_des_atlas(_P(d), {"parents": "provenance", "provenance": "prov.json"})


class RegleImage(TestCase):
    def test_sans_regle_aucune_licence_inventee(self):
        self.assertIsNone(il.regle_image({}, "public/icons/i.png"))
        r = {"prefixe": "public/photos/", "licence": "CC0-1.0"}
        self.assertIs(il.regle_image({"images": [r]}, "public/photos/x.webp"), r)
        self.assertIsNone(il.regle_image({"images": [r]}, "public/icons/i.png"))


class ModulesDeDessin(TestCase):
    """Un jeu dessiné par le code : ses modules DRAW, et ceux qu'il importe (de proche en proche)."""

    def test_modules_du_jeu_et_importes(self):
        with _tf.TemporaryDirectory() as d:
            racine = _P(d)
            fichiers = {
                "src/games/a/scene.ts": "import { dessine } from '../../ui/peintre';\nimport './regles';\n",
                "src/games/a/regles.ts": "export const x = 1;\n",
                "src/ui/peintre.ts": "export function dessine(c) { c.getContext('2d'); }\n",
                "src/ui/autre.ts": "const g = this.add.graphics();\n",
                "src/games/b/scene.ts": "const g = this.add.graphics();\n",
                "tests/outil.ts": "x.getContext('2d')\n",
            }
            for f, texte in fichiers.items():
                (racine / f).parent.mkdir(parents=True, exist_ok=True)
                (racine / f).write_text(texte)
            dans = il.portee("depot/a", {"monorepo": "src/games"}, list(fichiers))
            self.assertEqual(il.modules_de_dessin(racine, list(fichiers), dans), ["src/ui/peintre.ts"])
            dans_b = il.portee("depot/b", {"monorepo": "src/games"}, list(fichiers))
            self.assertEqual(il.modules_de_dessin(racine, list(fichiers), dans_b), ["src/games/b/scene.ts"])


class RegleDeclaree(TestCase):
    """Une règle « declaree » ne vaut que pour une image déclarée par le jeu avec une origine admise."""
    preuve = {"method": "m", "ref": "r", "decision": "d"}
    profil = {"provenance_images": "prov.json",
              "images": [{"prefixe": "assets/cutouts/", "declaree": True, "origines": ["planche"], "licence": "X",
                          "licence_preuve": preuve}]}

    def test_declaree_planche_admise_avec_sa_reference(self):
        r = il.regle_image(self.profil, "assets/cutouts/t/sprite-a.png",
                           {"sprite-a": {"id": "sprite-a", "origine": "planche", "planche": "P.png", "planche_sha256": "f"}})
        self.assertEqual(r["licence"], "X")
        self.assertIn("sprite-a", r["licence_preuve"]["ref"])

    def test_absente_ou_redessinee_reste_inconnue(self):
        self.assertIsNone(il.regle_image(self.profil, "assets/cutouts/t/sprite-b.png", {}))
        self.assertIsNone(il.regle_image(self.profil, "assets/cutouts/t/sprite-c.png",
                                         {"sprite-c": {"id": "sprite-c", "origine": "redessiné (marque)"}}))
