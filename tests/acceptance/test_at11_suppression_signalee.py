"""AT-11 (matrice E121) : « la suppression d'un fichier source utilisé est signalée sans effacer l'historique des releases. »"""
from __future__ import annotations

import json
import subprocess

from . import _contrat as C
from ._base import MondeScanne
from ._monde import FOUET, SCENE, ajouter_commit

BRANCHE = "sync/oracle-at11"


class AT11SuppressionSignalee(MondeScanne):
    """AT-11 / E121 — « AT-11 : la suppression d'un fichier source utilisé est signalée sans effacer
    l'historique des releases. »

    Scénario : `fouet.png` est utilisé par la scène Cuisine au commit tagué `v1.0` ; le registre importe
    puis commite sur `main`. Au commit suivant, le jeu supprime `fouet.png`. `sync` (incrémental) :
      - commite sur une branche `sync/…`, jamais sur `main` ; aucun dépôt source n'est modifié ;
      - l'asset reste au catalogue avec le même ID et son emplacement ; l'usage passe `removed` avec
        `removedAtCommit` = le commit de suppression, et garde `releases: [v1.0]` ;
      - l'événement est signalé dans `generated/reports/removed-in-use.json`."""

    def _git_show(self, chemin: str) -> str | None:
        p = subprocess.run(["git", "-C", str(self.reg), "show", f"{BRANCHE}:{chemin}"],
                           capture_output=True, text=True, env=C.environnement(self.monde.home))
        return p.stdout if p.returncode == 0 else None

    def test_suppression_signalee_historique_conserve(self):
        self.exiger_scan_ok()
        asset_id, avant = self.asset("jeu-a", FOUET)
        self.assertTrue(any("v1.0" in (u.get("releases") or []) for u in self.usages(asset_id, avant)),
                        "avant suppression : l'usage doit porter la release v1.0")
        main_avant = self.monde.commiter_registre("Import de fixture")
        sources_avant = {n: C.empreinte_arbre(self.monde.depot(n)) for n in ("jeu-a", "jeu-b")}

        suppression = ajouter_commit(self.monde, "jeu-a", {}, (FOUET,), "2026-03-01T10:00:00+00:00",
                                     "Retire le fouet")
        sources_avant["jeu-a"] = C.empreinte_arbre(self.monde.depot("jeu-a"))
        r = self.ctl(C.cmd_sync(BRANCHE))
        self.exiger_code(r, C.OK)

        self.assertEqual(self.monde.git(self.reg, "rev-parse", "main"), main_avant, "sync ne touche pas main")
        self.assertEqual(sources_avant, {n: C.empreinte_arbre(self.monde.depot(n)) for n in ("jeu-a", "jeu-b")},
                         "sync ne modifie aucun dépôt source")
        brut = self._git_show(f"{C.DOSSIER_ASSETS}/{asset_id}.json")
        self.assertIsNotNone(brut, f"la branche {BRANCHE} doit exister et garder l'asset {asset_id}")
        apres = json.loads(brut)
        self.assertEqual(apres["id"], asset_id)
        self.assertTrue(any(e.get("path") == FOUET for e in C.emplacements(apres.get("files"))),
                        "l'emplacement ne disparaît jamais du catalogue")
        usages = [u for u in apres.get("usages") or [] if (u.get("codeRef") or {}).get("path") == SCENE]
        self.assertTrue(usages, "l'usage de la scène Cuisine doit rester au catalogue")
        for u in usages:
            self.assertEqual(u.get("status"), "removed", u)
            self.assertEqual(u.get("removedAtCommit"), suppression, u)
            self.assertIn("v1.0", u.get("releases") or [], "l'historique des releases est conservé")

        rapport = self._git_show(C.RAPPORT_SUPPRESSIONS)
        if rapport is None and (self.reg / C.RAPPORT_SUPPRESSIONS).is_file():
            rapport = (self.reg / C.RAPPORT_SUPPRESSIONS).read_text(encoding="utf-8")
        self.assertIsNotNone(rapport, "removed-in-use.json absent")
        self.assertIn(asset_id, rapport, "la suppression d'un fichier utilisé est signalée")



class AT11SyncSansChangement(MondeScanne):
    """AT-11 / E121 — témoin : sans nouveau commit, `sync` ne signale rien et ne change pas le catalogue."""

    def test_sync_sans_nouveau_commit_ne_change_rien(self):
        self.exiger_scan_ok()
        self.monde.commiter_registre("Import de fixture")
        catalogue = C.empreinte_arbre(self.reg / "catalog", avec_dates=False)
        main_avant = self.monde.git(self.reg, "rev-parse", "main")
        r = self.ctl(C.cmd_sync("sync/oracle-vide"))
        self.exiger_code(r, C.OK)
        self.assertEqual(catalogue, C.empreinte_arbre(self.reg / "catalog", avec_dates=False))
        self.assertEqual(main_avant, self.monde.git(self.reg, "rev-parse", "main"))
        rapport = self.reg / C.RAPPORT_SUPPRESSIONS
        if rapport.is_file():
            asset_id, _ = self.asset("jeu-a", FOUET)
            self.assertNotIn(asset_id, rapport.read_text(encoding="utf-8"), "rien n'a été supprimé")
