"""L6 — Correctifs de l'inventaire réel du 19/11 (HL-538) : planches de David mesurées mais non prouvées.

Constats (inventaire figé, registre 34a1455, jeux-assets 788c83f) :

1. capsule-panic : 61 régions ont une RMSE > 0,02. Toutes sont des entrées `origine: "dérivé"` de
   `packages/assets/provenance.json` qui déclarent une retouche (`source_retouche` →
   `*.retouches.json`, `raccords: [[bande source, zone cible]]` : un libellé peint effacé en étirant une
   bande voisine). Rejeu à la main sur 5 cas (Claude, 19/11) : RMSE brute 0,080–0,216 ; après rejeu des
   raccords déclarés 0,007–0,020 pour 4 cas sur 5 ; le 5e déclare aussi un masque de silhouette.
   L'hypothèse « le resize n'est pas rejoué » est FAUSSE (le registre fait déjà crop, trim, resize,
   extent) : c'est la retouche déclarée qui n'est pas rejouée.
2. pestouille-rpg : 0 région liée, 19 limites `atlas-image-unresolved`. Le JSON d'atlas
   `public/assets/e03-interface.json` cite `meta.image: "e03-interface.png"`, alors que le dépôt livre
   `public/assets/e03-interface.webp`, encodé depuis `assets/export/e03-interface.png`.

Contrats (décisions du coordinateur, HL-538, 19/11) :

- `L6RaccordsDeclares` : le registre REJOUE la retouche déclarée (les pixels de la bande source, étirés sur la
  zone cible) sur la découpe AVANT de comparer. Il ne masque pas la zone et ne relève pas le seuil (0,02).
  Une zone cible qui ne contient pas la bande étirée reste au-dessus du seuil, tout comme des pixels étrangers
  hors des raccords. L'entrée reste `derived` : sa licence est une décision de David, pas de ce lot.
- `L6CorrespondanceDeChemins` : une table de correspondance DÉCLARÉE dans `catalog/sources.json`, au niveau
  de la source, `pathAliases: [{"from": "public/assets/*.png", "to": "assets/export/*.png"}]` (un seul `*`,
  dans le nom de fichier). Sans déclaration : pas de devinette, la limite `atlas-image-unresolved` reste. Avec
  déclaration : l'atlas se résout, la région est liée et mesurée, et chaque application de la table est tracée
  dans un rapport de `generated/reports/` (chemin cité et chemin résolu).

Boîte noire : CLI `assetctl … --json`, `catalog/assets/*.json`, `catalog/sheets/*.json`,
`generated/reports/*.json`. Fixtures synthétiques seulement : aucun dépôt réel, aucun réseau.
"""

import hashlib
import json
import unittest

import numpy as np
from PIL import Image

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M

SEUIL = 0.02  # spec : seuil de vérification des découpes ; ce lot ne le relève pas


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bruit(h: int, w: int, graine: int) -> np.ndarray:
    rng = np.random.default_rng(graine)
    a = rng.integers(40, 216, size=(h, w, 4), dtype=np.int32)
    a[..., 3] = 255
    return a


def _geo(s: str) -> tuple[int, int, int, int]:
    w, rest = s.split("x")
    h, x, y = (int(v) for v in rest.split("+"))
    return int(w), h, x, y


def _atlas(cadres: dict[str, np.ndarray], image: str) -> tuple[bytes, dict]:
    """Atlas JSON-hash horizontal, sans rognage ni rotation."""
    hauteur = max(c.shape[0] for c in cadres.values()) + 4
    largeur = sum(c.shape[1] + 2 for c in cadres.values()) + 2
    img = np.zeros((hauteur, largeur, 4), np.int32)
    frames, x = {}, 2
    for nom, px in cadres.items():
        h, w = px.shape[:2]
        img[2:2 + h, x:x + w] = px
        frames[nom] = {"frame": {"x": x, "y": 2, "w": w, "h": h}, "rotated": False, "trimmed": False,
                       "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h}, "sourceSize": {"w": w, "h": h},
                       "duration": 100}
        x += w + 2
    return M.png(img), {"frames": frames, "meta": {"app": "fixture", "image": image, "format": "RGBA8888",
                                                   "size": {"w": largeur, "h": hauteur}, "scale": "1"}}


def _ajouter_jeu(test, nom: str, fichiers: dict, alias: list | None = None):
    """Ajoute un dépôt de jeu au monde et à la liste d'autorisation (avec `pathAliases` si donné)."""
    world = test.world
    world.commits[nom] = M._depot(world, nom, fichiers, "2026-02-04T10:00:00+00:00")
    chemin = world.registre / C.SOURCES
    doc = C.lire_json(chemin)
    entree = C.source_locale(nom, world.depot(nom))
    if alias is not None:
        entree["pathAliases"] = alias
    doc[C.CLE_SOURCES].append(entree)
    chemin.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    world.commiter_registre(f"Registre de fixture : source {nom}")


def _scan(test):
    r = test.world.scan()
    test.assertEqual(r.code, C.OK, f"fixture : scan-repos en échec\n{r}")
    return r


def _sprite(test, cadre: str) -> tuple[str, dict]:
    trouves = [(i, a) for i, a in C.assets(test.reg).items()
               if isinstance(a.get("family"), dict) and a["family"].get("sprite", {}).get("frameName") == cadre]
    test.assertEqual(len(trouves), 1, f"un sprite {cadre} attendu : {[i for i, _ in trouves]}")
    return trouves[0]


def _regions(test, asset_id: str) -> list[dict]:
    return [r for p in C.planches(test.reg).values() for r in p.get("regions", []) if r.get("assetId") == asset_id]


def _rmse_mesurees(regions: list[dict]) -> list[float]:
    return [r["evidence"]["value"] for r in regions
            if isinstance(r.get("evidence"), dict) and r["evidence"].get("method") == "rmse"]


class _Monde(unittest.TestCase):
    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        self.reg = self.world.registre


# ------------------------------------------------------------------------------------------------
# 1. Raccords déclarés (capsule-panic) : rejouer la retouche avant de comparer
# ------------------------------------------------------------------------------------------------

BOITE_R = [48, 24, 380, 40]            # w, h, x, y sur la planche 512×512
BANDE = "4x10+2+5"                     # bande source, coordonnées DANS la découpe
CIBLE = "30x10+8+5"                    # zone cible (libellé peint), coordonnées dans la découpe


def _planche_r() -> tuple[np.ndarray, np.ndarray]:
    """Planche 512×512 ; la découpe est un bruit opaque dont la bande source a des lignes de couleur
    constante (l'étirement horizontal ne dépend donc pas du filtre de rééchantillonnage) et dont la zone
    cible porte un « libellé peint » magenta."""
    w, h, x, y = BOITE_R
    decoupe = _bruit(h, w, 7)
    bw, bh, bx, by = _geo(BANDE)
    for i in range(bh):
        decoupe[by + i, bx:bx + bw] = (30 + 15 * i, 90, 200 - 10 * i, 255)
    cw, ch, cx, cy = _geo(CIBLE)
    decoupe[cy:cy + ch, cx:cx + cw] = (250, 0, 250, 255)
    a = np.zeros((512, 512, 4), np.int32)
    a[y:y + h, x:x + w] = decoupe
    return a, decoupe


def _raccorder(decoupe: np.ndarray) -> np.ndarray:
    bw, bh, bx, by = _geo(BANDE)
    cw, ch, cx, cy = _geo(CIBLE)
    sortie = decoupe.copy()
    ligne = decoupe[by:by + bh, bx:bx + 1]                     # lignes constantes : colonne représentative
    sortie[cy:cy + ch, cx:cx + cw] = np.repeat(ligne, cw, axis=1)
    return sortie


def _fichiers_jeu_r() -> dict:
    planche, decoupe = _planche_r()
    planche_png = M.png(planche)
    retouchee = _raccorder(decoupe)
    cw, ch, cx, cy = _geo(CIBLE)
    faux = decoupe.copy()
    faux[cy:cy + ch, cx:cx + cw] = (20, 200, 20, 255)          # la zone cible n'est PAS la bande étirée
    etranger = retouchee.copy()
    etranger[14:24, 40:48] = (255, 255, 0, 255)                # pixels étrangers HORS des raccords
    atlas_png, atlas_json = _atlas({"sprite-raccord-ok": retouchee, "sprite-raccord-faux": faux,
                                    "sprite-hors-raccord": etranger}, "r.png")
    w, h, x, y = BOITE_R
    entree = {"origine": "dérivé", "planche": "Planche_R.png", "planche_sha256": _sha(planche_png),
              "boite": BOITE_R, "transformation": "découpe + nettoyage raster",
              "source_retouche": "assets/source/r.retouches.json",
              "transformations": [f"retouche libellé peint effacé : bande {BANDE} étirée sur {CIBLE}"],
              "etapes": ["crop", "retouche raster ImageMagick", "resize", "atlas json-hash"]}
    provenance = {"schemaVersion": 1, "outils": {"magick": "fixture"},
                  "assets": [dict(entree, id=f"sprite-{n}") for n in ("raccord-ok", "raccord-faux", "hors-raccord")]}
    retouches = [{"id": n, "boite": f"{w}x{h}+{x}+{y}", "raccords": [[BANDE, CIBLE]],
                  "transformation": "découpe + nettoyage raster"}
                 for n in ("raccord-ok", "raccord-faux", "hors-raccord")]
    return {
        "package.json": json.dumps({"name": "jeu-r", "private": True}) + "\n",
        "assets/source/Planche_R.png": planche_png,
        "assets/source/r.retouches.json": json.dumps(retouches, ensure_ascii=False, indent=2) + "\n",
        "assets/provenance.json": json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        "public/assets/atlas/r.png": atlas_png,
        "public/assets/atlas/r.json": json.dumps(atlas_json, indent=2) + "\n",
    }


class L6RaccordsDeclares(_Monde):
    """Contrat : la retouche déclarée (`source_retouche`, `raccords`) est rejouée sur la découpe avant la
    comparaison ; seuil inchangé ; ni masque ni seuil relevé ; l'entrée reste `derived`."""

    def setUp(self):
        super().setUp()
        _ajouter_jeu(self, "jeu-r", _fichiers_jeu_r())
        _scan(self)

    def test_raccord_rejoue_mesure_sous_le_seuil(self):
        asset_id, fiche = _sprite(self, "sprite-raccord-ok")
        mesures = _rmse_mesurees(_regions(self, asset_id))
        self.assertTrue(mesures, f"une région mesurée (RMSE) attendue pour {asset_id} : {_regions(self, asset_id)}")
        self.assertLessEqual(min(mesures), SEUIL, "la découpe retouchée selon le raccord déclaré doit se "
                                                  f"vérifier sous {SEUIL} une fois le raccord rejoué : {mesures}")
        self.assertEqual(fiche["provenance"].get("type"), "derived",
                         "une découpe retouchée reste `derived` : sa licence est une décision de David")

    def test_zone_cible_qui_n_est_pas_la_bande_reste_au_dessus(self):
        asset_id, _ = _sprite(self, "sprite-raccord-faux")
        mesures = _rmse_mesurees(_regions(self, asset_id))
        self.assertFalse([m for m in mesures if m <= SEUIL],
                         "rejouer, ce n'est pas masquer : une zone cible qui ne porte pas la bande étirée "
                         f"ne se vérifie pas : {mesures}")

    def test_pixels_etrangers_hors_raccord_restent_au_dessus(self):
        asset_id, _ = _sprite(self, "sprite-hors-raccord")
        mesures = _rmse_mesurees(_regions(self, asset_id))
        self.assertFalse([m for m in mesures if m <= SEUIL],
                         f"des pixels étrangers hors des raccords ne se vérifient pas : {mesures}")


# ------------------------------------------------------------------------------------------------
# 2. Correspondance de chemins déclarée (pestouille-rpg)
# ------------------------------------------------------------------------------------------------

BOITE_P = [40, 30, 120, 300]
ALIAS = [{"from": "public/assets/*.png", "to": "assets/export/*.png"}]


def _fichiers_jeu_p() -> dict:
    w, h, x, y = BOITE_P
    cadre = _bruit(h, w, 11)
    planche = np.zeros((512, 512, 4), np.int32)
    planche[y:y + h, x:x + w] = cadre
    planche_png = M.png(planche)
    atlas_png, atlas_json = _atlas({"sprite-p1": cadre}, "p.png")   # meta.image cite le PNG
    webp = io_webp(atlas_png)
    provenance = {"schemaVersion": 1, "outils": {"magick": "fixture"},
                  "livraison": {"atlas": "public/assets/<table>.webp, encodé depuis assets/export/<table>.png"},
                  "assets": [{"id": "sprite-p1", "origine": "planche", "planche": "Planche_P.png",
                              "planche_sha256": _sha(planche_png), "boite": BOITE_P, "marge": 0, "ancre": "centre",
                              "transformations": ["crop", "atlas json-hash"], "atlas": "public/assets/p.png",
                              "licence": "CC-BY-4.0"}]}
    return {
        "package.json": json.dumps({"name": "jeu-p", "private": True}) + "\n",
        "assets/source/Planche_P.png": planche_png,
        "assets/export/p.png": atlas_png,                         # référence sans perte (hors build)
        "public/assets/p.webp": webp,                             # livré
        "public/assets/p.json": json.dumps(atlas_json, indent=2) + "\n",
        "assets/provenance.json": json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
    }


def io_webp(png_bytes: bytes) -> bytes:
    import io
    with Image.open(io.BytesIO(png_bytes)) as im:
        b = io.BytesIO()
        im.convert("RGBA").save(b, "WEBP", lossless=True)
        return b.getvalue()


def _textes_rapports(registre) -> str:
    d = registre / "generated" / "reports"
    return "\n".join(f.read_text(encoding="utf-8") for f in sorted(d.glob("*.json"))) if d.is_dir() else ""


class L6CorrespondanceDeChemins(_Monde):
    """Contrat : `pathAliases` déclaré par source dans `catalog/sources.json` ; sans déclaration, aucune
    devinette ; avec, l'atlas se résout, la région est liée et mesurée, et l'application est tracée."""

    def test_sans_table_declaree_pas_de_devinette(self):
        _ajouter_jeu(self, "jeu-p", _fichiers_jeu_p())
        _scan(self)
        limites = C.lire_json(self.reg / "generated" / "reports" / "scan-limits.json")
        texte = json.dumps(limites, ensure_ascii=False)
        self.assertIn("atlas-image-unresolved", texte)
        self.assertIn("public/assets/p.json", texte)
        asset_id, _ = _sprite(self, "sprite-p1") if any(
            isinstance(a.get("family"), dict) and a["family"].get("sprite", {}).get("frameName") == "sprite-p1"
            for a in C.assets(self.reg).values()) else (None, None)
        if asset_id:
            self.assertFalse(_rmse_mesurees(_regions(self, asset_id)), "sans table déclarée, aucune mesure")

    def test_table_declaree_resout_lie_et_trace(self):
        _ajouter_jeu(self, "jeu-p", _fichiers_jeu_p(), alias=ALIAS)
        _scan(self)
        asset_id, fiche = _sprite(self, "sprite-p1")
        mesures = _rmse_mesurees(_regions(self, asset_id))
        self.assertTrue(mesures and min(mesures) <= SEUIL,
                        f"atlas résolu par la table déclarée : région liée et mesurée sous {SEUIL} : {mesures}")
        self.assertTrue(fiche.get("sourceSheetId"), "le sprite est rattaché à sa planche")
        limites = json.dumps(C.lire_json(self.reg / "generated" / "reports" / "scan-limits.json"))
        self.assertFalse("atlas-image-unresolved" in limites and "public/assets/p.json" in limites,
                         "l'atlas de jeu-p ne doit plus être signalé non résolu")
        rapports = _textes_rapports(self.reg)
        self.assertTrue("public/assets/p.png" in rapports and "assets/export/p.png" in rapports,
                        "chaque application de la table est tracée dans un rapport (chemin cité → résolu)")

    def test_validate_accepte_la_table(self):
        _ajouter_jeu(self, "jeu-p", _fichiers_jeu_p(), alias=ALIAS)
        _scan(self)
        r = self.world.ctl(["validate", "--json"])
        self.assertEqual(r.code, C.OK, f"`pathAliases` fait partie du schéma des sources\n{r}")


# ------------------------------------------------------------------------------------------------
# 3. `usage add` sur un catalogue non commité (mode de panne mis au jour par AT-14 sous L5)
# ------------------------------------------------------------------------------------------------

DEST_U = "public/assets/reutilise/fouet.png"


class L6UsageAddCatalogueNonCommite(_Monde):
    """Arbitrage du coordinateur, HL-538, 19/11 : « AT-14 : ACCEPTÉ. Le scénario commite le catalogue après le
    scan, comme dans un vrai usage. […] ajoute un cas d'oracle où `usage add` s'exécute sur un catalogue qui
    n'est pas commité, ou dont le HEAD ne contient pas l'asset. Il doit être REFUSÉ (rc 3, avec un message qui
    dit « commite le catalogue »), au lieu d'écrire un registryCommit faux. »

    Contrat : `usage add` refuse (code 3), n'écrit aucun lock, et son message contient « commite le catalogue »,
    quand le catalogue a des changements non commités ou quand HEAD ne contient pas le couple
    assetId/assetVersion demandé. Témoin : catalogue commité → code 0, `registryCommit` = HEAD."""

    def _usage_add(self, asset_id):
        jeu_b = self.world.depot("jeu-b")
        r = self.world.ctl(C.cmd_usage_add(asset_id, "jeu-b", "Menu", "sprite", jeu_b, DEST_U, C.OPTION_CIBLE_PRIVEE))
        return r, jeu_b / C.LOCK_JEU

    def _refus(self, r, lock):
        self.assertEqual(r.code, C.REFUS, f"usage add sur un catalogue non commité : refus (3) attendu\n{r}")
        self.assertIn("commite le catalogue", (r.stdout + r.stderr).casefold(),
                      f"le refus dit quoi faire : « commite le catalogue »\n{r}")
        self.assertFalse(lock.exists(), "un refus n'écrit aucun lock (pas de registryCommit faux)")

    def test_catalogue_non_commite_refuse(self):
        _scan(self)                                   # catalogue importé, PAS commité
        asset_id, _ = _un(self, "jeu-a", M.FOUET)
        self._refus(*self._usage_add(asset_id))

    def test_head_sans_l_asset_refuse(self):
        _scan(self)
        self.world.commiter_registre("Catalogue importé")
        M.ajouter_commit(self.world, "jeu-a", {"public/assets/neuf.png": M.png(M.uni(10, 10, (5, 99, 7, 255)))},
                         (), "2026-03-06T10:00:00+00:00", "Nouvel asset")
        _scan(self)                                   # le nouvel asset n'est que dans l'arbre de travail
        asset_id, _ = _un(self, "jeu-a", "public/assets/neuf.png")
        self._refus(*self._usage_add(asset_id))

    def test_temoin_catalogue_commite_accepte(self):
        _scan(self)
        head = self.world.commiter_registre("Catalogue importé")
        asset_id, _ = _un(self, "jeu-a", M.FOUET)
        r, lock = self._usage_add(asset_id)
        self.assertEqual(r.code, C.OK, f"témoin : catalogue commité, usage add accepté\n{r}")
        self.assertEqual(C.lire_json(lock).get("registryCommit"), head)


def _un(test, depot, chemin):
    trouves = [(i, a) for i, a in C.assets(test.reg).items()
               if any(l.get("repo") == depot and l.get("path") == chemin for l in a["files"]["locations"])]
    test.assertEqual(len(trouves), 1, f"un asset attendu à {depot}:{chemin} : {[i for i, _ in trouves]}")
    return trouves[0]


if __name__ == "__main__":
    unittest.main()
