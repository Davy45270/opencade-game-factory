"""AT-08 (matrice E118) : « une ressource à licence inconnue ne peut pas être exportée publiquement. »"""
from __future__ import annotations

from . import _contrat as C
from ._base import MondeScanne
from ._monde import BOITE_ETOILE, FOUET, PLANCHE


class AT08GardePublication(MondeScanne):
    """AT-08 / E118 — « AT-08 : une ressource à licence inconnue ne peut pas être exportée publiquement. »

    Intention : `publish --target public` d'un asset `license: unknown` rend le code 3 et n'écrit RIEN
    (ni dossier cible, ni catalogue) ; la garde n'est pas un refus aveugle : une découpe prouvée d'une
    planche citée par un fichier de provenance (région vérifiée) est `CC-BY-4.0` avec sa preuve et passe ;
    la même planche avec une boîte non conforme reste `unknown`."""

    def setUp(self):
        self.exiger_scan_ok()
        self.sha_planche = C.sha256_fichier(self.monde.depot("jeu-a") / PLANCHE)

    def _decoupe_prouvee(self) -> tuple[str, dict]:
        w, h, x, y = BOITE_ETOILE
        for asset_id, a in self.cadres_sur_planche("etoile", self.sha_planche):
            r = a.get("sourceRegion") or {}
            if (r.get("x"), r.get("y"), r.get("w"), r.get("h")) == (x, y, w, h) and r.get("verified") is True:
                return asset_id, a
        self.fail("aucune découpe prouvée de « etoile » (voir AT-06)")

    def test_licence_inconnue_refusee_sans_rien_ecrire(self):
        asset_id, fouet = self.asset("jeu-a", FOUET)
        self.assertEqual(fouet.get("license"), "unknown", "aucune preuve : la licence reste inconnue")
        dest = self.monde.racine / "export-public"
        catalogue = C.empreinte_arbre(self.reg / "catalog")
        r = self.ctl(C.cmd_publish([asset_id], "public", dest))
        self.exiger_code(r, C.REFUS)
        self.assertFalse(dest.exists() and any(dest.rglob("*")), "un refus ne doit rien écrire")
        self.assertEqual(catalogue, C.empreinte_arbre(self.reg / "catalog"))

    def test_lot_mixte_refuse_en_entier(self):
        prouve, _ = self._decoupe_prouvee()
        inconnu, _ = self.asset("jeu-a", FOUET)
        dest = self.monde.racine / "export-mixte"
        r = self.ctl(C.cmd_publish([prouve, inconnu], "public", dest))
        self.exiger_code(r, C.REFUS)
        self.assertFalse(dest.exists() and any(dest.rglob("*")), "rien d'écrit, même pas l'asset autorisé")

    def test_decoupe_prouvee_cc_by_passe(self):
        asset_id, a = self._decoupe_prouvee()
        self.assertEqual(a.get("license"), "CC-BY-SA-4.0")  # dessin de David : HL-538 7-3316 (CC-BY-4.0 avant le 24/11)
        self.assertTrue(a.get("licenseEvidence"), "une licence connue porte sa preuve")
        dest = self.monde.racine / "export-cc-by"
        r = self.ctl(C.cmd_publish([asset_id], "public", dest))
        self.exiger_code(r, C.OK)
        ecrits = [p for p in dest.rglob("*") if p.is_file()]
        self.assertTrue(ecrits, "l'export autorisé écrit le fichier et son manifeste")
        self.assertTrue(any(C.contient_texte(p.read_text(encoding="utf-8", errors="replace"), "CC-BY-SA-4.0")
                            for p in ecrits if p.suffix in (".json", ".md", ".txt")),
                        "le manifeste d'export cite la licence (attribution CC BY)")

    def test_boite_non_conforme_reste_inconnue(self):
        for asset_id, a in self.cadres_sur_planche("nuage", self.sha_planche):
            self.assertEqual(a.get("license"), "unknown", f"{asset_id} : région non vérifiée → unknown")

    def test_manifeste_de_licences(self):
        self.exiger_code(self.ctl(C.cmd_index()), C.OK)
        chemin = self.reg / C.MANIFESTE_LICENCES
        self.assertTrue(chemin.is_file(), f"{C.MANIFESTE_LICENCES} absent")
        manifeste = C.lire_json(chemin)
        asset_id, _ = self.asset("jeu-a", FOUET)
        lignes = C.dicts(manifeste, lambda d: d.get("id") == asset_id)
        self.assertTrue(lignes and all(d.get("publicExport") == "forbidden" for d in lignes), lignes)
