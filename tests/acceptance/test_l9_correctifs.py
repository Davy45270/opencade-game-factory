"""L9 — Ressources générées par code, et version d'ImageMagick au format réel (HL-538).

1. Ressources générées par code. Spec ORIGINALE, § 1 : « Périmètre : images, sprites, animations, atlases,
   tilesets, tilemaps, SVG, polices, sons, musiques, shaders et ressources générées par code. Chaque famille
   utilise un schéma spécialisé, avec un noyau de métadonnées commun. » Décision de David (HL-535 7-3026,
   HL-534 7-3027), relayée par le coordinateur le 19/11 : « un lot "ressources générées par code" (schéma
   spécialisé, comme le veut la spec ; provenance = générateur et commit ; pas de découpe à vérifier, la licence
   est celle du dépôt du jeu) ».

   Cas réel qui motive le lot : six-de-chaque (18c9ede) livre 4 images produites par du code du dépôt,
   `apps/web/public/art/glyphs.svg` (sortie exacte de `glyphSheet()`, `packages/renderer-pixi/src/art.ts`) et 3
   icônes PWA (`scripts/make-icons.js`, via rsvg-convert). Le jeu tient cette table dans son propre test
   (`tests/assets-provenance.test.ts` : générateur + fragments que le générateur doit contenir). Inventaire figé
   du 19/11 (registre a7ed5da) : les 4 sont `repo-file`, `unknown`, `needs-review`.

   Contrat (aucun dépôt de jeu modifié : la déclaration est une configuration du REGISTRE, comme `pathAliases`) :
   dans `catalog/sources.json`, une source peut porter
   `generatedResources: [{"path": <chemin ou motif à un seul *>, "generator": <chemin>, "mentions": [<fragment>…]}]`.
   Au commit importé, une image du dépôt qui correspond à une entrée est une ressource générée par code SI ET
   SEULEMENT SI le générateur existe à ce même commit et contient chacun des fragments déclarés (`mentions` non
   vide). Alors :
   - `provenance.type == "code-generated"` et `provenance.generator == {"path", "commit", "sha256"}` (chemin du
     générateur, commit importé, SHA-256 des octets du générateur à ce commit) ;
   - aucune région ni découpe : pas de `sourceSheetId`, aucune région de planche ne cite l'asset ;
   - licence = celle du dépôt : identifiant SPDX lu dans `LICENSE` (et/ou `package.json` `license` ; s'ils
     divergent, aucune licence) ; `licenseEvidence` cite `LICENSE` ; statut hors `needs-review` ;
   - la garde publique accepte l'asset (`materialize` vers une cible publique : 0) ; `validate` : 0.
   Sinon (générateur absent, fragment absent, dépôt sans licence déterminable) : rien n'est attribué (`unknown`),
   et une limite nommée dans `generated/reports/scan-limits.json` cite le chemin de l'image. Une image NON
   déclarée n'est jamais devinée « générée ». Générateur et sortie modifiés par un commit ultérieur : nouvelle
   version du même asset, dont `provenance.generator.commit` est le nouveau commit.

2. Version d'ImageMagick au format réel. La recette de pestouille-rpg (e664288, `assets/provenance.json`)
   déclare `"outils": {"magick": "7.1.2-35"}` (format d'ImageMagick : `N.N.N-N`). Le registre de L7/L8 ne
   reconnaît que `N.N.N` (`tools/extract/magick.py`, `VERSION`) : la déclaration réelle est ignorée en silence
   et l'inventaire figé du 19/11 mesure les 176 régions de pestouille avec Pillow (62 ≤ 0,02, 114 au-dessus),
   alors que la chaîne magick de la recette les donne toutes ≤ 0,011. L'oracle L7 n'utilisait que `N.N.N` :
   c'est l'oracle qui avait un trou. Contrat : `N.N.N` ET `N.N.N-N` déclarent une version ; la règle de majeure
   (L7) est inchangée ; `"fixture"` et toute autre forme ne déclarent rien.

Boîte noire : `assetctl` par sous-processus, fixtures synthétiques seulement.
"""

import hashlib
import json
import unittest

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M
from tests.acceptance import test_l6_correctifs as L6
from tests.acceptance import test_l7_correctifs as L7

import numpy as np

LICENCE_MIT = """MIT License

Copyright (c) 2026 Fixture

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

GENERATEUR_ICONES = """// Icônes PWA de fixture (comme six-de-chaque scripts/make-icons.js)
for (const [nom, taille] of [['192', 192], ['512', 512]]) {
    rendre(taille, `public/icons/jeu-g-${nom}.png`);
}
"""
GENERATEUR_ART = """// Planche de glyphes de fixture (comme six-de-chaque packages/renderer-pixi/src/art.ts)
export function glyphSheet() { return '<svg/>'; }   // écrit dans public/art/glyphs.svg
"""
GLYPHES = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
           '<symbol id="lune" viewBox="0 0 24 24"><path d="M14 2A9 9 0 1 0 21 17Z" fill="currentColor"/></symbol>'
           '</svg>\n')

DECLARATION = [
    {"path": "public/icons/jeu-g-*.png", "generator": "scripts/make-icons.js",
     "mentions": ["public/icons/jeu-g-${nom}.png", "['192', 192"]},
    {"path": "public/art/glyphs.svg", "generator": "src/art.ts", "mentions": ["export function glyphSheet()"]},
    {"path": "public/art/sans-generateur.png", "generator": "scripts/absent.js", "mentions": ["sans-generateur"]},
    {"path": "public/art/non-mentionne.png", "generator": "scripts/make-icons.js", "mentions": ["non-mentionne"]},
]


def _image(couleur, taille=48) -> bytes:
    a = np.zeros((taille, taille, 4), np.int32)
    a[4:taille - 4, 4:taille - 4] = (*couleur, 255)
    return M.png(a)


def _fichiers_jeu_g(licence=True) -> dict:
    fichiers = {
        "package.json": json.dumps({"name": "jeu-g", "private": True, **({"license": "MIT"} if licence else {})}) + "\n",
        "scripts/make-icons.js": GENERATEUR_ICONES,
        "src/art.ts": GENERATEUR_ART,
        "public/icons/jeu-g-192.png": _image((200, 120, 30), 48),
        "public/icons/jeu-g-512.png": _image((30, 120, 200), 64),
        "public/art/glyphs.svg": GLYPHES,
        "public/art/sans-generateur.png": _image((90, 200, 90), 40),
        "public/art/non-mentionne.png": _image((200, 90, 200), 44),
        "public/art/orphelin.png": _image((10, 10, 220), 36),
    }
    if licence:
        fichiers["LICENSE"] = LICENCE_MIT
    return fichiers


def _sha_texte(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def _limites(registre) -> str:
    chemin = registre / "generated" / "reports" / "scan-limits.json"
    return json.dumps(C.lire_json(chemin), ensure_ascii=False) if chemin.exists() else ""


class _MondeGenere(unittest.TestCase):
    NOM = "jeu-g"
    LICENCE = True

    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        self.reg = self.world.registre
        L6._ajouter_jeu(self, self.NOM, _fichiers_jeu_g(self.LICENCE))
        chemin = self.reg / C.SOURCES
        doc = C.lire_json(chemin)
        entree = next(s for s in doc[C.CLE_SOURCES] if s.get("name") == self.NOM)
        entree["generatedResources"] = DECLARATION
        chemin.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.world.commiter_registre("Registre : ressources générées déclarées pour jeu-g")
        r = self.world.scan()
        self.assertEqual(r.code, C.OK, f"fixture : scan\n{r}")
        self.commit = self.world.commits[self.NOM]

    def fiche(self, chemin):
        return C.asset_par_chemin(self.reg, self.NOM, chemin)

    def exiger_genere(self, chemin, generateur, texte_generateur, commit=None):
        asset_id, a = self.fiche(chemin)
        provenance = a["provenance"]
        self.assertEqual(provenance.get("type"), "code-generated", f"{chemin} : provenance {provenance}")
        self.assertEqual(provenance.get("generator"),
                         {"path": generateur, "commit": commit or self.commit, "sha256": _sha_texte(texte_generateur)},
                         f"{chemin} : générateur, commit importé et SHA-256 du générateur : {provenance}")
        return asset_id, a

    def exiger_rien_attribue(self, chemin, motif):
        asset_id, a = self.fiche(chemin)
        self.assertEqual(a["license"], "unknown", f"{motif} : aucune licence attribuée à {chemin} : {a['license']}")
        self.assertNotEqual(a["provenance"].get("type"), "code-generated", f"{motif} : {a['provenance']}")
        return asset_id, a


class L9RessourcesGenereesParCode(_MondeGenere):
    """Contrat 1 (docstring du module) : ressource déclarée et prouvée par son générateur au commit importé."""

    def test_icones_provenance_generateur_et_commit(self):
        for chemin in ("public/icons/jeu-g-192.png", "public/icons/jeu-g-512.png"):
            self.exiger_genere(chemin, "scripts/make-icons.js", GENERATEUR_ICONES)

    def test_svg_genere(self):
        self.exiger_genere("public/art/glyphs.svg", "src/art.ts", GENERATEUR_ART)

    def test_licence_du_depot_avec_preuve(self):
        _, a = self.exiger_genere("public/icons/jeu-g-192.png", "scripts/make-icons.js", GENERATEUR_ICONES)
        self.assertEqual(a["license"], "MIT", f"licence du dépôt du jeu : {a['license']}")
        self.assertIn("LICENSE", json.dumps(a.get("licenseEvidence"), ensure_ascii=False),
                      f"la preuve de licence cite le fichier LICENSE du dépôt : {a.get('licenseEvidence')}")
        self.assertNotEqual(a.get("status"), "needs-review", "ressource prouvée : hors needs-review")

    def test_aucune_decoupe_ni_region(self):
        asset_id, a = self.exiger_genere("public/icons/jeu-g-512.png", "scripts/make-icons.js", GENERATEUR_ICONES)
        self.assertFalse(a.get("sourceSheetId"), f"aucune planche : {a.get('sourceSheetId')}")
        self.assertFalse(L6._regions(self, asset_id), "aucune région de planche ne cite une ressource générée")

    def test_livrable_en_public_et_catalogue_valide(self):
        asset_id, _ = self.exiger_genere("public/icons/jeu-g-192.png", "scripts/make-icons.js", GENERATEUR_ICONES)
        self.world.commiter_registre("Catalogue avec ressources générées")
        r = self.world.ctl(["validate", "--json"])
        self.assertEqual(r.code, C.OK, f"le schéma spécialisé est valide\n{r}")
        r = self.world.ctl(C.cmd_materialize(asset_id, self.world.racine / "sortie-l9" / "icone.png"))
        self.assertEqual(r.code, C.OK, f"licence du dépôt prouvée : livrable vers une cible publique\n{r}")

    def test_generateur_absent_rien_attribue_et_limite(self):
        self.exiger_rien_attribue("public/art/sans-generateur.png", "générateur absent au commit")
        self.assertIn("public/art/sans-generateur.png", _limites(self.reg), "limite nommée citant l'image")

    def test_generateur_qui_ne_mentionne_pas_rien_attribue_et_limite(self):
        self.exiger_rien_attribue("public/art/non-mentionne.png", "fragment déclaré absent du générateur")
        self.assertIn("public/art/non-mentionne.png", _limites(self.reg), "limite nommée citant l'image")

    def test_image_non_declaree_jamais_devinee(self):
        self.exiger_rien_attribue("public/art/orphelin.png", "image non déclarée")

    def test_nouvelle_version_quand_generateur_et_sortie_changent(self):
        id_avant, avant = self.exiger_genere("public/icons/jeu-g-192.png", "scripts/make-icons.js", GENERATEUR_ICONES)
        self.world.commiter_registre("Catalogue avant évolution du générateur")
        nouveau = GENERATEUR_ICONES.replace("// Icônes PWA", "// Icônes PWA, fond plus sombre")
        commit = M.ajouter_commit(self.world, self.NOM, {"scripts/make-icons.js": nouveau,
                                                         "public/icons/jeu-g-192.png": _image((120, 60, 10), 48)},
                                  (), "2026-03-06T10:00:00+00:00", "Icônes plus sombres")
        r = self.world.scan()
        self.assertEqual(r.code, C.OK, f"second scan\n{r}")
        id_apres, apres = self.exiger_genere("public/icons/jeu-g-192.png", "scripts/make-icons.js", nouveau, commit)
        self.assertEqual(id_apres, id_avant, "même asset")
        self.assertEqual(apres["version"], avant["version"] + 1, "nouvelle version du même asset")


class L9DepotSansLicenceDeterminable(_MondeGenere):
    """Contrat 1 : dépôt sans `LICENSE` ni `license` dans package.json : générateur prouvé mais aucune licence."""

    NOM = "jeu-g"
    LICENCE = False

    def test_aucune_licence_et_limite(self):
        asset_id, a = self.fiche("public/icons/jeu-g-192.png")
        self.assertEqual(a["license"], "unknown", f"aucune licence de dépôt déterminable : {a['license']}")
        self.assertIn("public/icons/jeu-g-192.png", _limites(self.reg), "limite nommée citant l'image")
        r = self.world.ctl(C.cmd_materialize(asset_id, self.world.racine / "sortie-l9" / "icone.png"))
        self.assertEqual(r.code, C.REFUS, f"licence inconnue : refus public (3)\n{r}")


class L9MagickVersionAuFormatReel(L7._Monde):
    """Contrat 2 (docstring du module) : `outils.magick` au format `N.N.N-N` déclare la version ; la majeure
    décide comme en L7. ROUGE sur 2ec8965 : la forme réelle est ignorée, Pillow mesure."""

    def setUp(self):
        super().setUp()
        self.version = L7._exiger_magick(self)
        planche = L7._planche_k()
        self.planche_png = M.png(planche)
        self.cadre = L7._normaliser_magick(self.world.racine, self.planche_png)
        self.rmse_pillow = L7._rmse_pillow(planche, self.cadre)
        self.assertGreater(self.rmse_pillow, L7.SEUIL, "fixture : Pillow doit dépasser le seuil")

    def _jeu(self, nom, outils):
        L7._ajouter_jeu(self, nom, L7._fichiers_jeu_k(nom, self.planche_png, self.cadre, outils))
        L7._scan(self)
        asset_id, _ = L7._sprite(self, "sprite-k")
        return L7._regions(self, asset_id)

    def test_niveau_de_correctif_comme_pestouille(self):
        declaree = ".".join(map(str, self.version)) + "-35"
        regions = self._jeu("jeu-k35", {"magick": declaree})
        mesures = L7._rmse_mesurees(regions)
        self.assertTrue(mesures and min(mesures) <= L7.SEUIL,
                        f"magick {declaree} (forme de pestouille) : RMSE ≤ {L7.SEUIL} attendue, Pillow donne "
                        f"{self.rmse_pillow:.4f} : {mesures}")
        self.assertTrue(any(isinstance(r.get("evidence"), dict) and r["evidence"].get("tool") == "magick"
                            for r in regions), f"l'evidence nomme magick : {regions}")

    def test_niveau_de_correctif_majeure_differente(self):
        declaree = f"{self.version[0] - 1}.9.0-1"
        regions = self._jeu("jeu-k61", {"magick": declaree})
        self.assertFalse(L7._rmse_mesurees(regions), f"magick {declaree} : majeure différente, aucune RMSE")


class L9TemoinSansDeclaration(unittest.TestCase):
    """Témoin (vert dès aujourd'hui) : la même fixture SANS `generatedResources` se scanne (0) et aucune image
    n'est devinée « générée » ; les icônes restent `unknown`."""

    def test_fixture_saine_et_rien_devine(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        self.reg = self.world.registre
        L6._ajouter_jeu(self, "jeu-g", _fichiers_jeu_g())
        r = self.world.scan()
        self.assertEqual(r.code, C.OK, f"fixture : scan sans déclaration\n{r}")
        for chemin in ("public/icons/jeu-g-192.png", "public/art/glyphs.svg", "public/art/orphelin.png"):
            _, a = C.asset_par_chemin(self.reg, "jeu-g", chemin)
            self.assertEqual(a["license"], "unknown", f"{chemin} : rien n'est deviné sans déclaration")
            self.assertNotEqual(a["provenance"].get("type"), "code-generated", f"{chemin} : {a['provenance']}")


if __name__ == "__main__":
    unittest.main()
