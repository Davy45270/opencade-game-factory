"""L8 — Correctifs différés (HL-538).

Raccords : plafond relatif et plancher absolu. Arbitrage du coordinateur, HL-538, 19/11 : « (ii) retenue : plafond
à 75 % exclusif et plancher de 1 024 px hors raccord. C'est le plancher absolu qui porte la preuve, et les deux
découpes honnêtes de capsule restent vérifiables. » Raison : au-delà, la zone hors raccord ne suffit plus à prouver
la provenance. Distribution mesurée (capsule-panic main, 14 entrées à raccords dans `*.retouches.json`) : couverture
cumulée 0,146 à 0,398 pour 12 entrées, puis `cadre-statistiques-reussite` 0,530 et `barre-partie` 0,697 (vérifiée
à 0,0068 une fois les raccords rejoués) ; pixels hors raccord : minimum 3 605 (`barre-partie`), médiane 4 840 ; les
16 entrées sans raccord ont toutes au moins 1 911 px. Le plancher de 1 024 px (32 × 32) est 3,5 fois sous le
minimum réel. Contrat : une région n'est mesurée que si la couverture cumulée des cibles est < 75 % ET s'il reste au
moins 1 024 px hors raccord ; sinon, limite nommée dans `scan-limits` et aucune RMSE.

Constat remonté par les agents de Cozy et de Six (19/11) : `assetctl check-lock <chemin relatif>` résout le chemin
depuis le dossier du registre, pas depuis le répertoire courant de l'appelant (rc 4, « No such file »).

Contrat (coordinateur, HL-538, 19/11) : « les chemins relatifs se résolvent depuis le répertoire courant, avec un
test ». Boîte noire : `assetctl` lancé par sous-processus avec `cwd` = le dépôt du jeu. Fixtures synthétiques seulement.
"""

import subprocess
import sys
import unittest

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M

DEST = "public/assets/reutilise/fouet.png"


def _depuis(world, cwd, args):
    p = subprocess.run([sys.executable, str(world.registre / C.ASSETCTL), *args], cwd=cwd,
                       env=C.environnement(world.home), capture_output=True, text=True, timeout=C.DELAI)
    return C.Resultat(p.returncode, p.stdout, p.stderr, args)


class L8CheminsRelatifsDepuisLeRepertoireCourant(unittest.TestCase):
    """Contrat : un chemin relatif passé à la CLI (ici le lock de `check-lock`) se résout depuis le répertoire
    courant de l'appelant. Témoin : le même lock en chemin absolu rend 0."""

    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        r = self.world.scan()
        self.assertEqual(r.code, C.OK, f"fixture : scan\n{r}")
        self.world.commiter_registre("Catalogue importé")
        fouet = [i for i, a in C.assets(self.world.registre).items()
                 if any(l.get("repo") == "jeu-a" and l.get("path") == M.FOUET for l in a["files"]["locations"])]
        self.assertEqual(len(fouet), 1, fouet)
        self.jeu_b = self.world.depot("jeu-b")
        r = self.world.ctl(C.cmd_usage_add(fouet[0], "jeu-b", "Menu", "sprite", self.jeu_b, DEST, C.OPTION_CIBLE_PRIVEE))
        self.assertEqual(r.code, C.OK, f"fixture : usage add\n{r}")
        r = self.world.ctl(C.cmd_materialize(fouet[0], self.jeu_b / DEST, C.OPTION_CIBLE_PRIVEE))
        self.assertEqual(r.code, C.OK, f"fixture : materialize\n{r}")

    def test_temoin_chemin_absolu(self):
        r = _depuis(self.world, self.jeu_b, C.cmd_check_lock(self.jeu_b / C.LOCK_JEU))
        self.assertEqual(r.code, C.OK, f"témoin : chemin absolu\n{r}")

    def test_chemin_relatif_depuis_le_depot_du_jeu(self):
        r = _depuis(self.world, self.jeu_b, ["check-lock", C.LOCK_JEU, "--json"])
        self.assertEqual(r.code, C.OK, "un chemin relatif se résout depuis le répertoire courant de l'appelant, "
                                       f"pas depuis le registre\n{r}")


# ------------------------------------------------------------------------------------------------
# Raccords : plafond 75 % exclusif et plancher 1 024 px hors raccord
# ------------------------------------------------------------------------------------------------

import json as _json

import numpy as np

from tests.acceptance import test_l6_correctifs as L6

PLANCHER = 1024


def _jeu_raccord(boite, bande, cible):
    """Planche 512×512 ; découpe en bruit opaque, bande source à lignes constantes ; cadre = découpe raccordée."""
    w, h, x, y = boite
    decoupe = L6._bruit(h, w, 23)
    bw, bh, bx, by = L6._geo(bande)
    for i in range(bh):
        decoupe[by + i, bx:bx + bw] = (20 + 5 * i, 120, 220 - 4 * i, 255)
    cw, ch, cx, cy = L6._geo(cible)
    decoupe[cy:cy + ch, cx:cx + cw] = (250, 0, 250, 255)            # libellé peint
    cadre = decoupe.copy()
    cadre[cy:cy + ch, cx:cx + cw] = np.repeat(decoupe[by:by + bh, bx:bx + 1], cw, axis=1)
    planche = np.zeros((512, 512, 4), np.int32)
    planche[y:y + h, x:x + w] = decoupe
    planche_png = M.png(planche)
    atlas_png, atlas_json = L6._atlas({"sprite-r": cadre}, "r.png")
    entree = {"id": "sprite-r", "origine": "dérivé", "planche": "Planche_R.png", "planche_sha256": L6._sha(planche_png),
              "boite": boite, "source_retouche": "assets/source/r.retouches.json",
              "etapes": ["crop", "retouche raster ImageMagick", "resize", "atlas json-hash"]}
    retouches = [{"id": "r", "boite": f"{w}x{h}+{x}+{y}", "raccords": [[bande, cible]]}]
    return {
        "package.json": _json.dumps({"name": "jeu-r", "private": True}) + "\n",
        "assets/source/Planche_R.png": planche_png,
        "assets/source/r.retouches.json": _json.dumps(retouches, indent=2) + "\n",
        "assets/provenance.json": _json.dumps({"schemaVersion": 1, "outils": {"magick": "fixture"},
                                               "assets": [entree]}, ensure_ascii=False, indent=2) + "\n",
        "public/assets/atlas/r.png": atlas_png,
        "public/assets/atlas/r.json": _json.dumps(atlas_json, indent=2) + "\n",
    }


class L8RaccordsPlafondEtPlancher(L6._Monde):
    """Contrat : couverture cumulée < 75 % ET au moins 1 024 px hors raccord pour mesurer (voir docstring du module)."""

    def _mesures(self, boite, bande, cible):
        L6._ajouter_jeu(self, "jeu-r", _jeu_raccord(boite, bande, cible))
        L6._scan(self)
        asset_id, _ = L6._sprite(self, "sprite-r")
        return L6._rmse_mesurees(L6._regions(self, asset_id))

    def test_petite_region_sous_le_plancher_pas_de_mesure(self):
        # 40×20 = 800 px ; cible 19×20 (47,5 %) : 420 px hors raccord < 1 024.
        mesures = self._mesures([40, 20, 380, 40], "1x20+0+0", "19x20+1+0")
        self.assertFalse(mesures, "moins de 1 024 px hors raccord : la région ne se mesure pas, même sous le plafond "
                                  f"relatif : {mesures}")

    def test_cas_barre_partie_70_pourcent_mesure(self):
        # 120×40 = 4 800 px ; cible 84×40 (70 %) : 1 440 px hors raccord ≥ 1 024 — comme barre-partie (69,7 %).
        mesures = self._mesures([120, 40, 300, 300], "2x40+0+0", "84x40+2+0")
        self.assertTrue(mesures and min(mesures) <= L6.SEUIL,
                        f"couverture 70 % < 75 % et 1 440 px hors raccord : mesurée et vérifiée : {mesures}")

    def test_temoin_75_pourcent_refuse(self):
        # 120×40 ; cible 90×40 (75 %, plafond exclusif) : 1 200 px hors raccord, mais couverture ≥ 75 %.
        mesures = self._mesures([120, 40, 300, 300], "2x40+0+0", "90x40+2+0")
        self.assertFalse(mesures, f"couverture ≥ 75 % : pas de mesure : {mesures}")


# ------------------------------------------------------------------------------------------------
# M6 — `sync` lit un changement de `pathAliases` à refs sources constantes
# ------------------------------------------------------------------------------------------------

class L8SyncPathAliasesARefsConstantes(unittest.TestCase):
    """Constat M6 (relecture n° 2) : « Si le catalogue commité ajoute ou modifie une table sans déplacement de
    branche ou de tag source, la référence comparée reste identique. `sync` peut retourner 0, `scannedCopies: 0`,
    avec la résolution et le rapport précédents. Un scan complet applique la table. »

    Contrat : la table `pathAliases` effective fait partie de l'état comparé par le scan incrémental. Ajouter ou
    retirer une table à commit source constant fait relire la copie (`scannedCopies` ≥ 1), et la branche de sync
    porte la résolution que donnerait un scan complet (région de `sprite-p1` mesurée sous le seuil)."""

    BRANCHE = "sync/l8-alias"

    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        self.reg = self.world.registre

    def _alias(self, valeur):
        chemin = self.reg / C.SOURCES
        doc = C.lire_json(chemin)
        entree = next(s for s in doc[C.CLE_SOURCES] if s.get("name") == "jeu-p")
        if valeur is None:
            entree.pop("pathAliases", None)
        else:
            entree["pathAliases"] = valeur
        chemin.write_text(_json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.world.commiter_registre("Registre : table pathAliases de jeu-p modifiée (refs sources constantes)")

    def _sync(self):
        r = self.world.ctl(C.cmd_sync(self.BRANCHE))
        self.assertEqual(r.code, C.OK, f"sync\n{r}")
        return _json.loads(r.stdout)

    def _mesures_sur_branche(self):
        def lire(dossier):
            noms = self.world.git(self.reg, "ls-tree", "--name-only", f"{self.BRANCHE}:{dossier}").split()
            return {n[:-5]: _json.loads(self.world.git(self.reg, "show", f"{self.BRANCHE}:{dossier}/{n}"))
                    for n in noms if n.endswith(".json")}
        ids = [i for i, a in lire(C.DOSSIER_ASSETS).items() if isinstance(a.get("family"), dict)
               and a["family"].get("sprite", {}).get("frameName") == "sprite-p1"]
        regions = [r for p in lire(C.DOSSIER_PLANCHES).values() for r in p.get("regions", [])
                   if r.get("assetId") in ids]
        return L6._rmse_mesurees(regions)

    def test_ajout_de_la_table_relu_par_sync(self):
        L6._ajouter_jeu(self, "jeu-p", L6._fichiers_jeu_p())
        r = self.world.scan()
        self.assertEqual(r.code, C.OK, f"fixture : scan sans table\n{r}")
        self.world.commiter_registre("Catalogue sans table")
        self._alias(L6.ALIAS)
        sortie = self._sync()
        self.assertGreaterEqual(sortie.get("scannedCopies", 0), 1,
                                f"table ajoutée à refs constantes : la copie doit être relue : {sortie}")
        mesures = self._mesures_sur_branche()
        self.assertTrue(mesures and min(mesures) <= L6.SEUIL,
                        f"la branche de sync porte la résolution par la table (comme un scan complet) : {mesures}")

    def test_retrait_de_la_table_relu_par_sync(self):
        L6._ajouter_jeu(self, "jeu-p", L6._fichiers_jeu_p(), alias=L6.ALIAS)
        r = self.world.scan()
        self.assertEqual(r.code, C.OK, f"fixture : scan avec table\n{r}")
        self.world.commiter_registre("Catalogue avec table")
        self._alias(None)
        sortie = self._sync()
        self.assertGreaterEqual(sortie.get("scannedCopies", 0), 1,
                                f"table retirée à refs constantes : la copie doit être relue : {sortie}")

    def test_temoin_refs_et_table_constantes_rien_a_relire(self):
        L6._ajouter_jeu(self, "jeu-p", L6._fichiers_jeu_p(), alias=L6.ALIAS)
        r = self.world.scan()
        self.assertEqual(r.code, C.OK, f"fixture : scan avec table\n{r}")
        self.world.commiter_registre("Catalogue avec table")
        self._sync()
        sortie = self._sync()
        self.assertEqual(sortie.get("scannedCopies"), 0, f"témoin : rien n'a changé, rien à relire : {sortie}")


if __name__ == "__main__":
    unittest.main()
