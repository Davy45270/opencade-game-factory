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


class RegleExigences(TestCase):
    """Une règle déclarée n'accorde rien sans les preuves qu'elle exige ; un SHA-256 déclaré doit être celui livré."""
    preuve = {"method": "m", "ref": "r", "decision": "d"}
    profil = {"provenance_images": "prov.json",
              "images": [{"prefixe": "red/", "declaree": True, "origines": ["redessiné (marque)"],
                          "exige": ["planche", "planche_sha256"], "licence": "X", "auteur": "A",
                          "licence_preuve": preuve},
                         {"prefixe": "icons/", "declaree": True, "origines": ["dessiné dans le dépôt"],
                          "exige": ["sha256"], "licence": "X", "auteur": None, "licence_preuve": preuve}]}

    def test_redessin_sans_sha_de_planche_reste_inconnu(self):
        e = {"id": "r1", "origine": "redessiné (marque)", "planche": "P.png"}
        self.assertIsNone(il.regle_image(self.profil, "red/r1.svg", {"red/r1.svg": e}))
        r = il.regle_image(self.profil, "red/r1.svg", {"red/r1.svg": {**e, "planche_sha256": "ab"}})
        self.assertEqual((r["licence"], r["auteur"]), ("X", "A"))
        self.assertIn("SHA-256 ab", r["licence_preuve"]["ref"])

    def test_sha256_declare_doit_etre_celui_des_octets(self):
        octets = b"icone"
        e = {"fichier": "icons/i.png", "origine": "dessiné dans le dépôt", "auteur": "agent",
             "sha256": il.sha256(octets)}
        self.assertIsNone(il.regle_image(self.profil, "icons/i.png", {"icons/i.png": e}, b"autre"))
        self.assertIsNone(il.regle_image(self.profil, "icons/i.png", {"icons/i.png": e}))
        r = il.regle_image(self.profil, "icons/i.png", {"icons/i.png": e}, octets)
        self.assertEqual(r["auteur"], "agent")


class AppliquerRegle(TestCase):
    """Une licence prouvée n'est établie que sur la fiche repo-file de CE fichier de CE dépôt."""
    regle = {"licence": "X", "licence_preuve": {"method": "m", "ref": "r", "decision": "d"}, "auteur": "A"}

    def fiche(self, racine, aid, evidence, type_="repo-file"):
        (racine / "catalog/assets").mkdir(parents=True, exist_ok=True)
        (racine / "catalog/assets" / f"{aid}.json").write_text(il.json.dumps(
            {"id": aid, "license": "unknown", "provenance": {"type": type_, "author": "unknown", "evidence": evidence}}))

    def test_fiche_du_scan_de_ce_fichier_seulement(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.object(il, "REG", il.Path(d)):
            r = il.Path(d)
            self.fiche(r, "a", ["jeu@abc:public/i.png"])
            self.fiche(r, "b", ["autre@abc:public/i.png"])
            self.fiche(r, "c", ["jeu@abc:public/j.png"])
            self.fiche(r, "d", ["jeu@abc:public/i.png"], "external")
            fiches = {}
            self.assertTrue(il.appliquer_regle("a", self.regle, fiches, "jeu", "public/i.png"))
            self.assertEqual((fiches["a"]["license"], fiches["a"]["provenance"]["author"]), ("X", "A"))
            for aid in "bcd":
                self.assertFalse(il.appliquer_regle(aid, self.regle, fiches, "jeu", "public/i.png"))


class BrutParBoite(TestCase):
    """Deux atlas reprennent le même dessin : la découpe brute de l'un sert à l'autre (même planche, même boîte)."""
    def brut(self, element, boite, ev):
        w, h, x, y = boite
        return {"family": {"sprite": {"frameName": element}}, "provenance": {"type": "original-sheet-cut"},
                "sourceRegion": {"evidence": ev, "w": w, "h": h, "x": x, "y": y}}

    def test_repli_par_boite_et_planche(self):
        fiches = {"b": self.brut("p", [2, 3, 4, 5], "q.provenance.lot-aaaaaaaaaaaa.decoupe.json · SHA-256 x · planche P1")}
        self.assertIsNone(il.brut_de(fiches, "u.provenance.json", "p"))
        self.assertEqual(il.brut_de(fiches, "u.provenance.json", "p", [2, 3, 4, 5], "P1"), "b")
        self.assertIsNone(il.brut_de(fiches, "u.provenance.json", "p", [2, 3, 4, 6], "P1"))
        self.assertIsNone(il.brut_de(fiches, "u.provenance.json", "p", [2, 3, 4, 5], "P2"))


class PlancheSansDimensions(TestCase):
    """Une planche connue sans dimensions reçoit celles mesurées sur les mêmes octets ; jamais écrasées sinon."""
    def test_dimensions_completees_pas_ecrasees(self):
        from tools.extract.sheets import sheet_record
        cible = types.SimpleNamespace(sheet_ids={"d": "s"}, sheets={"s": {"id": "s", "dimensions": None}}, ids=None)
        self.assertEqual(sheet_record(cible, "d", "n", {"width": 4, "height": 3}, "e")["dimensions"],
                         {"width": 4, "height": 3})
        self.assertEqual(sheet_record(cible, "d", "n", {"width": 9, "height": 9}, "e")["dimensions"],
                         {"width": 4, "height": 3})


class DerivesDePlanche(TestCase):
    """Un dérivé déclaré prend la licence de sa planche seulement si la planche citée a les octets cités."""
    def test_derive_declare_et_planche_verifiee(self):
        import tempfile
        e = {"id": "carton", "origine": {"planche": "P.webp", "sha256": il.sha256(b"planche")},
             "derives": [{"fichier": "icons/i.png"}]}
        d = il.declarations_derivees(e)
        self.assertEqual(d[0]["fichier"], "icons/i.png")
        self.assertEqual(il.declarations_derivees({"id": "x", "origine": "planche"}), [])
        with tempfile.TemporaryDirectory() as rep:
            (il.Path(rep) / "P.webp").write_bytes(b"planche")
            profil = {"provenance_images": "p.json", "planches": rep,
                      "images": [{"prefixe": "icons/", "declaree": True, "origines": ["dérivé"],
                                  "exige": ["planche", "planche_sha256"], "planche_verifiee": True, "licence": "CC",
                                  "auteur": "A", "licence_preuve": {"method": "m", "ref": "r", "decision": "d"}}]}
            self.assertEqual(il.regle_image(profil, "icons/i.png", {"icons/i.png": d[0]})["licence"], "CC")
            (il.Path(rep) / "P.webp").write_bytes(b"autre")
            self.assertIsNone(il.regle_image(profil, "icons/i.png", {"icons/i.png": d[0]}))


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
