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


PRIVEE = "LicenseRef-David-Prive-Tous-Droits-Reserves"
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


class LicencesDeclareesParLeJeu(TestCase):
    """Capsule : inventaire (fichier, SHA-256, planche) et liste d'identifiants ; la licence déclarée doit être celle
    de la règle, le titulaire aussi ; un fichier non déclaré reste inconnu."""
    preuve = {"method": "m", "ref": "r", "decision": "d"}

    def test_inventaire_et_liste(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as rep:
            r = il.Path(rep)
            (r / "inv.json").write_text(json.dumps({"fichiers": [
                {"chemin": "a/s.png", "sha256": il.sha256(b"s"), "licence": "CC BY 4.0",
                 "planche": {"fichier": "P.png", "sha256": il.sha256(b"P")}},
                {"chemin": "a/t.png", "sha256": il.sha256(b"t"), "licence": "Autre",
                 "planche": {"fichier": "P.png", "sha256": il.sha256(b"P")}}]}))
            (r / "lic.json").write_text(json.dumps({"titulaire": "D", "licence": "CC BY 4.0", "assets": ["u"]}))
            (r / "P.png").write_bytes(b"P")
            profil = {"planches": rep, "declarations_licence": [{"fichier": "inv.json", "format": "inventaire"},
                                                                 {"fichier": "lic.json", "format": "liste"}],
                      "images": [{"prefixe": "a/run/", "declaree": True, "origines": ["licences.json"],
                                  "licence_declaree": "CC BY 4.0", "titulaire": "D", "licence": "CC", "auteur": "A",
                                  "licence_preuve": self.preuve},
                                 {"prefixe": "a/", "declaree": True, "origines": ["inventaire"],
                                  "licence_declaree": "CC BY 4.0", "exige": ["planche", "planche_sha256", "sha256"],
                                  "planche_verifiee": True, "licence": "CC", "auteur": "A",
                                  "licence_preuve": self.preuve}]}
            d = il.declarations_licence(r, profil)
            self.assertIn("inv.json", il.regle_image(profil, "a/s.png", d, b"s")["licence_preuve"]["ref"])
            self.assertIsNone(il.regle_image(profil, "a/s.png", d, b"autre"))
            self.assertIsNone(il.regle_image(profil, "a/t.png", d, b"t"))          # licence déclarée différente
            self.assertEqual(il.regle_image(profil, "a/run/u.webp", d)["licence"], "CC")
            self.assertIsNone(il.regle_image(profil, "a/run/v.webp", d))           # identifiant non déclaré
            self.assertIsNone(il.regle_image({**profil, "images": [{**profil["images"][0], "titulaire": "X"}]},
                                             "a/run/u.webp", d))
            (r / "P.png").write_bytes(b"autre planche")
            self.assertIsNone(il.regle_image(profil, "a/s.png", d, b"s"))


class CadreDeclare(TestCase):
    """Un cadre réemployé sans licence ne la reçoit que si sa fiche n'est employée que par ce dépôt."""
    regle = {"licence": "X", "licence_preuve": {"method": "m", "ref": "r", "decision": "d"}, "auteur": "A"}

    def test_fiche_partagee_refusee(self):
        import json, tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.object(il, "REG", il.Path(d)):
            (il.Path(d) / "catalog/assets").mkdir(parents=True)
            for aid, depots in (("a", ["jeu"]), ("b", ["jeu", "autre"]), ("c", [])):
                (il.Path(d) / "catalog/assets" / f"{aid}.json").write_text(json.dumps(
                    {"id": aid, "license": "unknown", "provenance": {"type": "derived"},
                     "usages": [{"repo": r} for r in depots]}))
            fiches = {}
            self.assertTrue(il.appliquer_regle_cadre("a", self.regle, fiches, "jeu"))
            self.assertEqual(fiches["a"]["license"], "X")
            self.assertFalse(il.appliquer_regle_cadre("b", self.regle, fiches, "jeu"))
            self.assertFalse(il.appliquer_regle_cadre("c", self.regle, fiches, "jeu"))


class Materialiser(TestCase):
    """Une fiche sans fichier reçoit ses octets au registre seulement s'ils ont son SHA-256."""
    def test_octets_de_la_fiche_seulement(self):
        import json, tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.object(il, "REG", il.Path(d)):
            r = il.Path(d)
            (r / "catalog/assets").mkdir(parents=True)
            (r / "sprites").mkdir()
            fiches = {}
            for aid, reg in (("a", None), ("b", "sprites/b.png")):
                fiches[aid] = {"id": aid, "sha256": il.sha256(b"png"), "format": "png",
                               "files": {"registry": reg, "locations": []}}
                (r / "catalog/assets" / f"{aid}.json").write_text(json.dumps(fiches[aid]))
            compte = {}
            self.assertFalse(il.materialiser("a", b"autre", fiches, compte))
            self.assertTrue(il.materialiser("a", b"png", fiches, compte))
            self.assertEqual((r / "sprites/a.png").read_bytes(), b"png")
            self.assertEqual(fiches["a"]["files"]["registry"], "sprites/a.png")
            self.assertFalse(il.materialiser("b", b"png", fiches, compte))


class TracerDerives(TestCase):
    """Un dérivé du scan sans parent reçoit derivedFrom = la source déclarée (SVG aux mêmes octets), avec reçu."""
    def test_redessin_vers_son_svg(self):
        import json, tempfile, types
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.object(il, "REG", il.Path(d)):
            r = il.Path(d)
            (r / "catalog/assets").mkdir(parents=True)
            (r / "clone/src").mkdir(parents=True)
            (r / "clone/src/x.svg").write_bytes(b"<svg/>")
            (r / "clone/prov.json").write_text(json.dumps({"assets": [
                {"id": "sprite-x", "origine": "redessiné (marque)", "svg": "src/x.svg"},
                {"id": "sprite-y", "origine": "redessiné (marque)", "svg": "src/absent.svg"}]}))
            fiches = {"svg": {"id": "svg", "sha256": il.sha256(b"<svg/>"), "variants": []},
                      "dx": {"id": "dx", "provenance": {"type": "derived", "author": "A"}},
                      "dy": {"id": "dy", "provenance": {"type": "derived", "author": "A"}}}
            for aid, a in fiches.items():
                (r / "catalog/assets" / f"{aid}.json").write_text(json.dumps(a))
            (r / "recu.json").write_text(json.dumps({"results": ["svg", "autre"]}))
            compte = {}
            with mock.patch.object(il, "recu_motive", lambda *a, **k: (r / "recu.json", [])):
                il.tracer_derives(types.SimpleNamespace(jeu="jeu"), "s" * 40, {"provenance_derives": "prov.json"},
                                  r / "clone", r, fiches, {il.sha256(b"<svg/>"): ["svg"]},
                                  [("a.png#sprite-x", "dx"), ("a.png#sprite-y", "dy")], compte)
            self.assertEqual(fiches["dx"]["provenance"]["derivedFrom"], "svg")
            self.assertEqual([c["assetId"] for c in fiches["dx"]["creation"]["searchReceipt"]["rejectedCandidates"]],
                             ["svg", "autre"])
            self.assertNotIn("derivedFrom", fiches["dy"]["provenance"])
            self.assertEqual(fiches["svg"]["variants"], ["dx"])
            self.assertEqual(compte, {"derives_traces": 1})


class CatalogueDeDavid(TestCase):
    """Catalogue d'assets de David : MIT par fichier (SHA-256 abrégé ou pixels de la copie) ; auteur inconnu refusé."""
    def test_catalogue_assets(self):
        import io, json, tempfile
        from unittest import mock
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            r = il.Path(d)
            buf = io.BytesIO(); Image.new("RGBA", (3, 2), (9, 8, 7, 255)).save(buf, format="PNG"); png = buf.getvalue()
            buf2 = io.BytesIO(); Image.new("RGBA", (3, 2), (9, 8, 7, 255)).save(buf2, format="PNG", optimize=True,
                                                                               compress_level=0)
            (r / "copie.png").write_bytes(png)
            cat = {"entrees": [
                {"id": "A", "droits": il.MIT_DAVID + " pour cet usage)", "auteur": "outil IA sur commande de David",
                 "fichiers": [{"source": "~/Projets/jeux/J/a.png", "sha256": il.sha256(png)[:16], "copie": "copie.png"}]},
                {"id": "B", "droits": il.MIT_DAVID + " pour cet usage)", "auteur": "inconnu — source non retrouvée",
                 "fichiers": [{"source": "~/Projets/jeux/J/b.png", "sha256": il.sha256(png)[:16]}]}]}
            (r / "catalogue.json").write_text(json.dumps(cat))
            with mock.patch.object(il, "CATALOGUE_DAVID", str(r / "catalogue.json")):
                profil = il.profil_monorepo("J", [])
                profil["declarations_licence"][0]["racine"] = "~/Projets/jeux/J/"
                dec = il.declarations_licence(r, profil)
                regle = il.regle_image(profil, "a.png", dec, png)
                self.assertEqual((regle["licence"], regle["auteur"]), ("MIT", "outil IA sur commande de David"))
                self.assertEqual(regle["copies"], [("j", "a.png"), ("j", "b.png"), ("jeux-assets", "copie.png")])
                if buf2.getvalue() != png:
                    self.assertEqual(il.regle_image(profil, "a.png", dec, buf2.getvalue())["licence"], "MIT")
                autre = io.BytesIO(); Image.new("RGBA", (3, 2), (1, 2, 3, 255)).save(autre, format="PNG")
                self.assertIsNone(il.regle_image(profil, "a.png", dec, autre.getvalue()))
                self.assertIsNone(il.regle_image(profil, "b.png", dec, png))
                self.assertIsNone(il.regle_image(profil, "c.png", dec, png))


class CopieDuCatalogue(TestCase):
    """La fiche de la copie déclarée par le catalogue (dépôt jeux-assets) reçoit la licence ; une autre copie, non."""
    regle = {"licence": "MIT", "licence_preuve": {"method": "m", "ref": "r", "decision": "d"}, "auteur": "A"}

    def test_copie_jeux_assets(self):
        import json, tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.object(il, "REG", il.Path(d)):
            (il.Path(d) / "catalog/assets").mkdir(parents=True)
            for aid, ev in (("a", "jeux-assets@x:objets/b.webp"), ("b", "jeux-assets@x:objets/autre.webp")):
                (il.Path(d) / "catalog/assets" / f"{aid}.json").write_text(json.dumps(
                    {"id": aid, "license": "unknown", "provenance": {"type": "repo-file", "evidence": [ev]}}))
            fiches = {}
            autres = [("jeux-assets", "objets/b.webp")]
            self.assertTrue(il.appliquer_regle("a", self.regle, fiches, "jeu", "src/b.webp", autres))
            self.assertFalse(il.appliquer_regle("b", self.regle, fiches, "jeu", "src/b.webp", autres))


class FicheDuCatalogueDeDavid(TestCase):
    """HL-538 (22/11, décors de Paris) : une fiche importée du catalogue de David (type generated, preuve
    catalogue.json@) ne reçoit une licence que d'une règle dont l'origine admise est ce catalogue."""
    du_catalogue = {"licence": "MIT", "origines": ["catalogue"], "auteur": "A",
                    "licence_preuve": {"method": "m", "ref": "r", "decision": "d"}}

    def test_regle_du_catalogue_seulement(self):
        import json, tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.object(il, "REG", il.Path(d)):
            (il.Path(d) / "catalog/assets").mkdir(parents=True)
            for aid, ev in (("a", "catalogue.json@da58e8e"), ("b", "catalogue.json@da58e8e"), ("c", "autre@x:y.webp")):
                (il.Path(d) / "catalog/assets" / f"{aid}.json").write_text(json.dumps(
                    {"id": aid, "license": "unknown", "provenance": {"type": "generated", "evidence": [ev]}}))
            fiches = {}
            self.assertFalse(il.appliquer_regle("b", {**self.du_catalogue, "origines": ["planche"]}, fiches, "jeu",
                                                "src/p.webp"))
            self.assertFalse(il.appliquer_regle("c", self.du_catalogue, fiches, "jeu", "src/p.webp"))
            self.assertTrue(il.appliquer_regle("a", self.du_catalogue, fiches, "jeu", "src/p.webp"))
            self.assertEqual(fiches["a"]["license"], "MIT")


class ConditionsDeSourceTierces(TestCase):
    """HL-538 (22/11, photos NASA/JPL/MESSENGER) : publiables à travers un jeu de David seulement, jamais dérivées
    sous une autre licence ; chaque photo de petit-astronome a sa licence de source et son crédit exact."""
    def test_garde(self):
        from tools.publish.licenses import THIRD_PARTY_GAME_ONLY
        from tools.core.schemas import schemas
        enum = schemas().validator("asset").schema["$defs"]["license"]["enum"]
        for lic in THIRD_PARTY_GAME_ONLY:
            self.assertIn(lic, enum)
            self.assertTrue((_P(__file__).resolve().parents[2] / "LICENSES" / f"{lic}.txt").is_file())
            photo = fiche("asset-image-photo-0001", "3" * 64, licence=lic)
            self.assertTrue(public_allowed(photo, set(), {}.get, PRIVATE_LICENSES))
            self.assertFalse(public_allowed(photo, set(), {}.get, frozenset()))

    def test_huit_photos(self):
        regles = {r["prefixe"]: r for r in il.PROFILS["petit-astronome"]["images"]}
        for nom in ("mercure", "venus", "terre", "mars", "jupiter", "saturne", "uranus", "neptune"):
            r = il.regle_image(il.PROFILS["petit-astronome"], f"public/discovery/photos/{nom}.webp")
            self.assertIs(r, regles[f"public/discovery/photos/{nom}.webp"])
            self.assertTrue(r["licence"].startswith("LicenseRef-"))
            self.assertIn(r["auteur"], r["licence_preuve"]["ref"])
        self.assertEqual(il.regle_image(il.PROFILS["petit-astronome"], "public/discovery/photos/mercure.webp")["licence"],
                         "LicenseRef-MESSENGER-Usage-Statement")


class ImagesRuntimeDeCapsule(TestCase):
    """HL-538 (22/11) : credits.webp et sprite-aide-accueil.webp, rejoués à l'identique par scripts/assets-runtime.py,
    passent AVANT la règle runtime/ qui exige une déclaration ; un autre fichier runtime non déclaré reste inconnu."""
    def test_regles(self):
        p = il.PROFILS["capsule-panic"]
        for f in ("packages/assets/runtime/credits.webp", "packages/assets/runtime/sprite-aide-accueil.webp"):
            self.assertEqual(il.regle_image(p, f)["licence"], "CC-BY-4.0")
        self.assertIsNone(il.regle_image(p, "packages/assets/runtime/sprite-inconnu.webp", {}))


class PlanchesEnPlusieursDossiers(TestCase):
    """Les planches v2 de Pestouille (2026-11-21) vivent dans un autre dossier que les v1 : le profil en liste deux."""
    def test_premier_dossier_qui_contient_la_planche(self):
        import tempfile
        with tempfile.TemporaryDirectory() as v1, tempfile.TemporaryDirectory() as v2:
            (il.Path(v1) / "a.png").write_bytes(b"v1")
            (il.Path(v2) / "b.png").write_bytes(b"v2")
            profil = {"planches": [v1, v2]}
            self.assertEqual(il.chemin_planche(profil, "a.png"), il.Path(v1) / "a.png")
            self.assertEqual(il.chemin_planche(profil, "b.png"), il.Path(v2) / "b.png")
            self.assertEqual(il.chemin_planche(profil, "c.png"), il.Path(v1) / "c.png")
            self.assertEqual(il.chemin_planche({"planches": v1}, "a.png"), il.Path(v1) / "a.png")
            self.assertEqual(il.chemin_planche({}, "a.png"), il.Path("/nonexistent/a.png"))

    def test_profil_pestouille_trouve_les_planches_v2(self):
        profil = il.PROFILS["pestouille-rpg"]
        self.assertIsInstance(profil["planches"], list)
        self.assertTrue(any(str(d).endswith("v2-2026-11-21/Pestouille") for d in profil["planches"]))
