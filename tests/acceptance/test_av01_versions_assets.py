"""AV-01 — Versions d'un asset : un contenu modifié est une NOUVELLE VERSION du même asset.

Source : spec v1.0 § 5 « Relations : `source-sheet -> source-region -> asset -> variant -> version ->
game/scene` » (matrice E036) et docs/AGENTS.md 5 « Ne jamais écraser un asset publié ; versionner les
variantes et dérivations » (E130). Arbitrage du coordinateur, HL-538, 19/11 : c'est le modèle du
cœur, Codex l'implémente (lot L4). Oracle écrit AVANT le code par Claude ; il échoue sur 7901d3c.

Contrat (lu dans le catalogue, `catalog/assets/*.json`) :
- l'`id` d'un asset est stable d'une version à l'autre ;
- `version` (entier ≥ 1) = version courante ; `sha256` = empreinte de la version courante ;
- `versions` : liste croissante de `{version, sha256, previousVersion, nextVersion}` —
  `previousVersion` vaut null pour la 1, `nextVersion` vaut null pour la dernière : l'historique se
  lit dans les deux sens ; aucune version n'est effacée ;
- même source + même chemin logique (ou même `assetId` déclaré dans l'`assets.lock.json` du jeu)
  + nouveau sha256 ⇒ nouvelle version du même asset, jamais un nouvel asset ;
- même contenu sous un nouveau chemin (renommage) ⇒ même asset, même version, emplacement mis à jour ;
- deux sources différentes ne fusionnent jamais leurs versions ;
- un second scan sans nouveau commit ne crée aucune version.
"""

import hashlib
import json
import unittest

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M

NOUVEAU = M.png(M.uni(16, 16, (56, 189, 248, 255)))  # le « cyan #38BDF8 » de Capsule
RENOMME = "public/assets/fouet-cuisine.png"
DECLARE = "public/assets/fouet-v2.png"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _actifs(asset: dict) -> set[tuple[str, str]]:
    return {(loc.get("repo"), loc.get("path")) for loc in C.emplacements(asset.get("files"))
            if loc.get("status", "active") != "removed" and not loc.get("releaseOnly")}


class AV01VersionsAssets(unittest.TestCase):
    def setUp(self):
        # Un monde neuf par test : chaque scénario part de la version 1.
        self.monde = M.creer_monde()
        self.addCleanup(self.monde.nettoyer)
        self.reg = self.monde.registre
        premier = self.monde.scan()
        self.assertEqual(premier.code, C.OK, str(premier))
        self.id, self.v1 = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        self.total = len(C.assets(self.reg))

    def _rescanner(self):
        result = self.monde.scan()
        self.assertEqual(result.code, C.OK, str(result))
        return C.assets(self.reg)

    def test_contenu_modifie_nouvelle_version_du_meme_asset(self):
        M.ajouter_commit(self.monde, "jeu-a", {M.FOUET: NOUVEAU}, (), "2026-03-05T10:00:00+00:00",
                         "Recoloration du fouet")
        assets = self._rescanner()
        identifiant, asset = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        self.assertEqual(identifiant, self.id, "un contenu modifié doit garder l'ID de l'asset")
        self.assertEqual(len(assets), self.total, "aucun nouvel asset pour une nouvelle version")
        self.assertEqual(asset.get("version"), 2)
        self.assertEqual(asset["sha256"], _sha(NOUVEAU))
        versions = asset.get("versions")
        self.assertIsInstance(versions, list, "champ `versions` absent")
        self.assertEqual([v["version"] for v in versions], [1, 2])
        self.assertEqual([v["sha256"] for v in versions], [self.v1["sha256"], _sha(NOUVEAU)])
        self.assertIsNone(versions[0]["previousVersion"])
        self.assertEqual(versions[0]["nextVersion"], 2, "historique illisible vers l'avant")
        self.assertEqual(versions[1]["previousVersion"], 1, "historique illisible vers l'arrière")
        self.assertIsNone(versions[1]["nextVersion"])
        orphelins = [i for i, a in assets.items() if a["sha256"] == self.v1["sha256"]]
        self.assertEqual(orphelins, [], "l'ancien contenu ne doit pas devenir un asset séparé")

    def test_rescan_sans_commit_ne_cree_aucune_version(self):
        M.ajouter_commit(self.monde, "jeu-a", {M.FOUET: NOUVEAU}, (), "2026-03-05T10:00:00+00:00",
                         "Recoloration du fouet")
        self._rescanner()
        avant = C.assets(self.reg)[self.id]
        apres = self._rescanner()[self.id]
        self.assertEqual(apres.get("version"), 2)
        self.assertEqual((apres.get("version"), apres.get("versions")), (avant.get("version"), avant.get("versions")))

    def test_renommage_contenu_identique_meme_asset_emplacement_mis_a_jour(self):
        brut = (self.monde.depot("jeu-a") / M.FOUET).read_bytes()
        M.ajouter_commit(self.monde, "jeu-a", {RENOMME: brut}, (M.FOUET,), "2026-03-05T10:00:00+00:00",
                         "Renommage du fouet")
        assets = self._rescanner()
        identifiant, asset = C.asset_par_chemin(self.reg, "jeu-a", RENOMME)
        self.assertEqual(identifiant, self.id)
        self.assertEqual(len(assets), self.total)
        self.assertEqual(asset["sha256"], self.v1["sha256"])
        self.assertEqual(asset.get("version"), 1, "un renommage n'est pas une nouvelle version")
        self.assertEqual(len(asset.get("versions") or []), 1)
        self.assertIn(("jeu-a", RENOMME), _actifs(asset))
        self.assertNotIn(("jeu-a", M.FOUET), _actifs(asset), "l'ancien chemin ne doit plus être actif")

    def test_id_declare_par_le_lock_nouvelle_version_malgre_le_changement_de_chemin(self):
        lock = {"schemaVersion": "1.0", "game": "jeu-a", "registryCommit": "0" * 40,
                "assets": [{"assetId": self.id, "assetVersion": "2", "sha256": _sha(NOUVEAU),
                            "scene": "Cuisine", "role": "sprite", "path": DECLARE}]}
        M.ajouter_commit(self.monde, "jeu-a", {DECLARE: NOUVEAU, "assets.lock.json": json.dumps(lock)},
                         (M.FOUET,), "2026-03-05T10:00:00+00:00", "Nouveau fouet déclaré par le lock")
        assets = self._rescanner()
        identifiant, asset = C.asset_par_chemin(self.reg, "jeu-a", DECLARE)
        self.assertEqual(identifiant, self.id, "l'assetId déclaré par le jeu doit être suivi")
        self.assertEqual(len(assets), self.total)
        self.assertEqual((asset.get("version"), asset["sha256"]), (2, _sha(NOUVEAU)))
        self.assertEqual([v["sha256"] for v in asset["versions"]], [self.v1["sha256"], _sha(NOUVEAU)])

    def test_deux_sources_ne_fusionnent_jamais_leurs_versions(self):
        M.ajouter_commit(self.monde, "jeu-b", {M.FOUET: NOUVEAU}, (), "2026-03-05T10:00:00+00:00",
                         "Même chemin dans une autre source")
        assets = self._rescanner()
        self.assertEqual(assets[self.id]["sha256"], self.v1["sha256"])
        self.assertEqual(assets[self.id].get("version"), 1)
        autre, _ = C.asset_par_chemin(self.reg, "jeu-b", M.FOUET)
        self.assertNotEqual(autre, self.id)
