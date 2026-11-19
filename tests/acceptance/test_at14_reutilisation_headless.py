"""AT-14 (matrice E124) : « un agent peut importer et réutiliser un asset dans un autre jeu sans interface graphique. »"""
from __future__ import annotations

import json

from . import _contrat as C
from ._base import MondeScanne
from ._monde import FOUET

DESTINATION = "public/assets/reutilise/fouet.png"


class AT14ReutilisationHeadless(MondeScanne):
    """AT-14 / E124 — « AT-14 : un agent peut importer et réutiliser un asset dans un autre jeu sans
    interface graphique. »

    Scénario, uniquement des sous-processus sans affichage (DISPLAY retiré par `_contrat.environnement`) : le fouet est importé depuis
    jeu-a ; un agent le cherche (`search`), le déclare dans jeu-b (`usage add`, qui écrit
    `assets.lock.json`), le matérialise (`materialize`) : le fichier est là, son SHA-256 est celui du
    catalogue, et `check-lock` rend 0 — puis 1 si le lock est trafiqué. jeu-b est une cible privée
    (`--private-target`), le fouet étant de licence inconnue (la garde publique est l'objet d'AT-08)."""

    def test_search_usage_add_materialize_check_lock(self):
        self.exiger_scan_ok()
        asset_id, fouet = self.asset("jeu-a", FOUET)
        r = self.ctl(C.cmd_search("fouet"))
        self.exiger_code(r, C.OK)
        self.assertIn(asset_id, [x.get("id") for x in C.resultats_recherche(r.json)])

        jeu_b = self.monde.depot("jeu-b")
        r = self.ctl(C.cmd_usage_add(asset_id, "jeu-b", "Menu", "sprite", jeu_b, DESTINATION, C.OPTION_CIBLE_PRIVEE))
        self.exiger_code(r, C.OK)
        lock_chemin = jeu_b / C.LOCK_JEU
        self.assertTrue(lock_chemin.is_file(), f"{C.LOCK_JEU} absent de jeu-b")
        lock = C.lire_json(lock_chemin)
        self.assertEqual(lock.get("game"), "jeu-b")
        self.assertEqual(lock.get("registryCommit"), self.monde.git(self.reg, "rev-parse", "HEAD"))
        lignes = [x for x in lock.get("assets") or [] if x.get("assetId") == asset_id]
        self.assertEqual(len(lignes), 1, lock)
        ligne = lignes[0]
        self.assertEqual((ligne.get("sha256"), ligne.get("scene"), ligne.get("role"), ligne.get("path")),
                         (fouet["sha256"], "Menu", "sprite", DESTINATION))
        self.assertIn("assetVersion", ligne)

        r = self.ctl(C.cmd_materialize(asset_id, jeu_b / DESTINATION, C.OPTION_CIBLE_PRIVEE))
        self.exiger_code(r, C.OK)
        self.assertEqual(C.sha256_fichier(jeu_b / DESTINATION), fouet["sha256"])
        self.assertEqual(C.sha256_fichier(jeu_b / DESTINATION),
                         C.sha256_fichier(self.monde.depot("jeu-a") / FOUET))

        self.exiger_code(self.ctl(C.cmd_check_lock(lock_chemin)), C.OK)
        trafique = jeu_b / "assets.lock.trafique.json"
        faux = json.loads(json.dumps(lock))
        for x in faux["assets"]:
            if x.get("assetId") == asset_id:
                x["sha256"] = "0" * 64
        trafique.write_text(json.dumps(faux, indent=2), encoding="utf-8")
        self.exiger_code(self.ctl(C.cmd_check_lock(trafique)), C.ECHEC)

    def test_sans_cible_privee_l_export_interdit_est_refuse(self):
        """Garde E074 : sans `--private-target`, un asset à export public interdit n'est pas écrit."""
        self.exiger_scan_ok()
        asset_id, _ = self.asset("jeu-a", FOUET)
        dest = self.monde.depot("jeu-b") / "public/assets/refuse/fouet.png"
        r = self.ctl(C.cmd_materialize(asset_id, dest))
        self.exiger_code(r, C.REFUS)
        self.assertFalse(dest.exists())
