"""AT-10 (matrice E120) : « une création sans recherche préalable échoue au contrôle de PR. »"""
from __future__ import annotations

import hashlib
import io
import json
import re

import numpy as np
from PIL import Image

from . import _contrat as C
from ._base import MondeScanne


def _png(couleur) -> bytes:
    a = np.zeros((20, 20, 4), np.uint8)
    a[3:17, 3:17] = couleur
    b = io.BytesIO()
    Image.fromarray(a, "RGBA").save(b, "PNG")
    return b.getvalue()


class AT10RechercheAvantCreation(MondeScanne):
    """AT-10 / E120 — « AT-10 : une création sans recherche préalable échoue au contrôle de PR. »

    Intention, en deux barrières :
      1. `register` sans reçu de recherche → code 3, rien d'écrit ; avec un reçu dont un candidat n'est
         pas rejeté avec une raison → code 3 ; avec reçu et rejets motivés → 0, l'asset porte
         `creation.searchReceipt` et `rejectedCandidates` ;
      2. le contrôle de PR `validate --base <ref>` rend 0 pour cet asset, et 1 pour un asset nouveau
         ajouté à la main sans `creation.searchReceipt` (en le disant)."""

    def test_register_et_controle_de_pr(self):
        self.exiger_scan_ok()
        base = self.monde.commiter_registre("Import de fixture")
        self.exiger_code(self.ctl(C.cmd_validate("--base", base)), C.OK)
        neuf = self.monde.racine / "neuf.png"
        neuf.write_bytes(_png((250, 120, 0, 255)))

        # 1a. sans reçu : refus, rien d'écrit
        avant = C.empreinte_arbre(self.reg, exclure=(".git", "build"))
        self.exiger_code(self.ctl(C.cmd_register(neuf, "Fouet neuf", "kitchen")), C.REFUS)
        self.assertEqual(avant, C.empreinte_arbre(self.reg, exclure=(".git", "build")), "refus : rien d'écrit")

        # 1b. reçu dont les candidats ne sont pas rejetés : refus
        recu = self.monde.racine / "recu.json"
        r = self.ctl(C.cmd_search("fouet", "--receipt", str(recu)))
        self.exiger_code(r, C.OK)
        self.assertTrue(recu.is_file(), "search --receipt doit écrire le reçu")
        candidats = [x["id"] for x in C.resultats_recherche(r.json)]
        self.assertTrue(candidats, "la recherche « fouet » doit trouver le fouet importé")
        self.exiger_code(self.ctl(C.cmd_register(neuf, "Fouet neuf", "kitchen", "--receipt", str(recu))), C.REFUS)

        # 1c. reçu et rejets motivés : accepté
        rejets = [a for c in candidats for a in ("--reject", f"{c}:couleur et orientation incompatibles")]
        r = self.ctl(C.cmd_register(neuf, "Fouet neuf", "kitchen", "--receipt", str(recu), *rejets))
        self.exiger_code(r, C.OK)
        nouveaux = {i: a for i, a in C.assets(self.reg).items() if (a.get("creation") or {}).get("searchReceipt")}
        self.assertEqual(len(nouveaux), 1, "l'asset créé porte creation.searchReceipt")
        nouvel_id, nouvel = next(iter(nouveaux.items()))
        rejetes = nouvel["creation"].get("rejectedCandidates")
        for c in candidats:
            self.assertTrue(C.contient_texte(rejetes, c), f"rejet motivé de {c} non conservé : {rejetes}")
        self.assertTrue(C.contient_texte(rejetes, "incompatibles"), "la raison du rejet est conservée")

        # 2a. contrôle de PR : la création avec reçu passe
        self.monde.commiter_registre("Création avec reçu")
        self.exiger_code(self.ctl(C.cmd_validate("--base", base)), C.OK)

        # 2b. un asset nouveau ajouté à la main sans reçu : le contrôle de PR échoue et le dit
        faux = json.loads(json.dumps(nouvel))
        del faux["creation"]["searchReceipt"]
        faux["creation"].pop("rejectedCandidates", None)
        faux_id = re.sub(r"-\d{4}$", "-9001", nouvel_id)
        faux["id"] = faux_id
        image = _png((0, 90, 250, 255))
        faux["sha256"] = hashlib.sha256(image).hexdigest()
        chemin_reg = (faux.get("files") or {}).get("registry")
        if chemin_reg:
            cible = self.reg / chemin_reg
            cible = cible.with_name(cible.stem + "-main" + cible.suffix)
            cible.write_bytes(image)
            faux["files"]["registry"] = cible.relative_to(self.reg).as_posix()
        (self.reg / C.DOSSIER_ASSETS / f"{faux_id}.json").write_text(
            json.dumps(faux, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        ids = C.lire_json(self.reg / C.FICHIER_IDS)
        ids[f"file:sha256:{faux['sha256']}"] = faux_id
        (self.reg / C.FICHIER_IDS).write_text(json.dumps(ids, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.monde.commiter_registre("Création sans recherche")
        r = self.ctl(C.cmd_validate("--base", base))
        self.exiger_code(r, C.ECHEC)
        self.assertRegex((r.stdout + r.stderr).lower(), r"searchreceipt|receipt|reçu",
                         "l'échec doit nommer le reçu de recherche manquant")
        self.assertIn(faux_id, r.stdout + r.stderr, "l'échec doit nommer l'asset fautif")
