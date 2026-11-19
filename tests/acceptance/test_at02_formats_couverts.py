"""AT-02 (matrice E112) : « 100 % des ressources des formats pris en charge sont importées ou signalées en exception. »"""
from __future__ import annotations

from . import _contrat as C
from ._base import MondeScanne
from ._monde import FORMATS_JEU_A, TEXTURES, TRONQUE, FOUET, NIVEAU


class AT02FormatsCouverts(MondeScanne):
    """AT-02 / E112 — « AT-02 : 100 % des ressources des formats pris en charge sont importées ou signalées
    en exception. »

    Intention : chaque fichier d'un format pris en charge (PNG avec et sans alpha, JPEG, WebP, GIF animé,
    SVG, Aseprite, atlas hash et array, Tiled, WAV, OGG, police, shader, module de dessin par code) est
    soit un emplacement du catalogue, soit une ligne de `exceptions.json` ; le PNG tronqué est une
    exception comptée dans la couverture ; le second scan indépendant ne trouve rien d'oublié."""

    def _catalogue_et_exceptions(self):
        catalogue = [*C.assets(self.reg).values(), *C.planches(self.reg).values()]
        exceptions = C.lire_json(C.rapport(self.reg, "exceptions"))
        return catalogue, exceptions

    def test_chaque_fichier_importe_ou_en_exception(self):
        self.exiger_scan_ok()
        catalogue, exceptions = self._catalogue_et_exceptions()
        manquants = [p for p in FORMATS_JEU_A
                     if not C.contient_valeur(catalogue, p) and not C.contient_valeur(exceptions, p)]
        self.assertEqual(manquants, [], "ni importés ni en exception")

    def test_png_tronque_en_exception_et_compte_dans_la_couverture(self):
        self.exiger_scan_ok()
        catalogue, exceptions = self._catalogue_et_exceptions()
        self.assertTrue(C.contient_valeur(exceptions, TRONQUE), "PNG tronqué absent de exceptions.json")
        self.assertFalse(any(e.get("path") == TRONQUE for e in C.emplacements(catalogue)),
                         "un PNG illisible ne doit pas devenir un asset")
        couverture = C.lire_json(C.rapport(self.reg, "coverage"))
        png = [d for d in C.dicts(couverture) if "png" in [str(v).lower().lstrip(".") for v in d.values()]
               or "png" in d]
        self.assertTrue(png, "la couverture doit avoir une ligne par format (png)")
        self.assertTrue(any(isinstance(v, int) and not isinstance(v, bool) and v >= 1
                            for d in png for v in C.parcourir(d)),
                        "l'exception PNG doit être comptée dans la couverture")

    def test_images_mesurees_pas_inventees(self):
        self.exiger_scan_ok()
        _, fouet = self.asset("jeu-a", FOUET)
        self.assertEqual((fouet["dimensions"]["width"], fouet["dimensions"]["height"]), (32, 48))
        self.assertIs(fouet["alpha"], True)
        _, niveau = self.asset("jeu-a", NIVEAU)
        self.assertIs(niveau["alpha"], False, "PNG RGB sans alpha")
        self.assertEqual(fouet["sha256"], C.sha256_fichier(self.monde.depot("jeu-a") / FOUET))

    def test_asset_dessine_par_code(self):
        self.exiger_scan_ok()
        codes = [a for a in C.assets(self.reg).values()
                 if C.contient_valeur(a, "code-generated") and C.contient_texte(a, TEXTURES)]
        self.assertTrue(codes, f"generateTexture dans {TEXTURES} → un asset de famille code-generated")

    def test_second_scan_rien_oublie(self):
        self.exiger_scan_ok()
        r = self.ctl(C.cmd_verify(self.monde.cache))
        self.exiger_code(r, C.OK)
        verify = C.lire_json(self.reg / C.RAPPORT_VERIFY)
        self.assertEqual(verify.get("forgotten"), [], verify)


class AT02TemoinOubli(MondeScanne):
    """AT-02 / E112 — témoin rouge : un asset retiré à la main du catalogue DOIT apparaître dans
    `forgotten` du second scan (sinon `--verify` ne prouve rien)."""

    def test_verify_trouve_un_blob_oublie(self):
        self.assertEqual(self.scan.code, C.OK, str(self.scan))
        asset_id, _ = self.asset("jeu-a", NIVEAU)
        (self.reg / C.DOSSIER_ASSETS / f"{asset_id}.json").unlink()
        r = self.ctl(C.cmd_verify(self.monde.cache))
        self.exiger_code(r, C.ECHEC)
        verify = C.lire_json(self.reg / C.RAPPORT_VERIFY)
        self.assertTrue(C.contient_valeur(verify.get("forgotten"), NIVEAU), verify)
