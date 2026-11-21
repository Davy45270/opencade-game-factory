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
