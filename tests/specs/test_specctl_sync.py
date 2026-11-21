"""Oracles des anomalies croisées du 21/11 (HL-525), écrits AVANT le code.

1. `specctl sync --from <homelab-docs> [--dry-run]` : le registre garde les énoncés qu'il a importés, mais l'état
   d'avancement (statut, preuve, critère d'acceptation) se ferme dans les matrices de homelab-docs. Mesure du 21/11 :
   SPEC-ASSET-REGISTRY à 0 preuve au registre pour 227 dans la matrice. sync recopie statut/preuve/critère quand
   l'énoncé est IDENTIQUE, ajoute les exigences nouvelles, garde celles qui ont disparu de la matrice (identifiant
   jamais recyclé) et signale sans l'appliquer une exigence dont l'énoncé a changé (décision requise).
2. `specctl inscrire-drive --drive <id> --name <nom> --project <projet>` : un document Drive que l'on n'a pas encore
   archivé est inscrit au registre « à importer » ; `discover --source drive` le classe `pending` et non plus `new`.
"""
from __future__ import annotations

import json
import unittest

from ._outil import Docs

DRIVE = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"


class BaseSync(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()
        self.assertEqual(self.d.specctl("import", "--from", str(self.d.docs), "--json").rc, 0)
        m = self.d.docs / "specs" / "jeu-a-conformite.json"
        mat = json.loads(m.read_text())
        mat["exigences"][1]["statut"] = "faite"                                 # E002 close dans la matrice
        mat["exigences"][1]["preuve"] = {"type": "test", "ref": "tests/x.py::test_fin"}
        mat["exigences"][0]["source"]["extrait"] = "Le joueur pose une tuile."  # inchangé
        mat["exigences"].append({"id": "E003", "source": mat["exigences"][0]["source"] | {"extrait": "Règles"},
                                 "statut": "a_faire"})
        m.write_text(json.dumps(mat, ensure_ascii=False))
        self.d.commit("matrice avancée")

    def tearDown(self) -> None:
        self.d.nettoyer()

    def exigences(self) -> dict:
        return {r["id"]: r for r in self.d.registre()["SPEC-JEU-A"]["requirements"]}


class Sync(BaseSync):

    def test_statut_et_preuve_recopies_si_enonce_identique(self) -> None:
        r = self.d.specctl("sync", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 0, r)
        e = self.exigences()["REQ-JEU-A-E002"]
        self.assertEqual(e["matrixStatus"], "faite")
        self.assertEqual(e["evidence"]["ref"], "tests/x.py::test_fin")
        self.assertEqual(self.d.registre()["SPEC-JEU-A"]["implementation"], "partial")   # E003 nouvelle, à faire

    def test_exigence_nouvelle_ajoutee_et_enregistree(self) -> None:
        self.d.specctl("sync", "--from", str(self.d.docs), "--json")
        self.assertIn("REQ-JEU-A-E003", self.exigences())
        ids = json.loads((self.d.usine / "specs" / "registry" / "ids.json").read_text())
        self.assertEqual(ids["REQ-JEU-A-E003"], "SPEC-JEU-A")
        self.assertEqual(self.d.specctl("validate", "--json").rc, 0)

    def test_enonce_change_signale_non_applique(self) -> None:
        m = self.d.docs / "specs" / "jeu-a-conformite.json"
        mat = json.loads(m.read_text())
        mat["exigences"][0]["source"]["extrait"] = "Le joueur pose DEUX tuiles."
        mat["exigences"][0]["statut"] = "ecartee"
        m.write_text(json.dumps(mat, ensure_ascii=False))
        self.d.commit("énoncé réécrit")
        r = self.d.specctl("sync", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual([c["id"] for c in r.json["statementChanged"]], ["REQ-JEU-A-E001"])
        e = self.exigences()["REQ-JEU-A-E001"]
        self.assertEqual((e["statement"], e["matrixStatus"]), ("Le joueur pose une tuile.", "faite"))

    def test_exigence_disparue_gardee_et_signalee(self) -> None:
        m = self.d.docs / "specs" / "jeu-a-conformite.json"
        mat = json.loads(m.read_text())
        mat["exigences"] = mat["exigences"][1:]
        m.write_text(json.dumps(mat, ensure_ascii=False))
        self.d.commit("E001 retirée de la matrice")
        r = self.d.specctl("sync", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.json["missingFromMatrix"], ["REQ-JEU-A-E001"])
        self.assertIn("REQ-JEU-A-E001", self.exigences())

    def test_dry_run_n_ecrit_rien_et_relance_idempotente(self) -> None:
        avant = self.d.empreinte_usine()
        r = self.d.specctl("sync", "--from", str(self.d.docs), "--dry-run", "--json")
        self.assertEqual((r.rc, r.json["updated"], r.json["added"]), (0, 1, 1), r)
        self.assertEqual(self.d.empreinte_usine(), avant)
        self.d.specctl("sync", "--from", str(self.d.docs), "--json")
        apres = self.d.empreinte_usine()
        r = self.d.specctl("sync", "--from", str(self.d.docs), "--json")
        self.assertEqual((r.json["updated"], r.json["added"]), (0, 0))
        self.assertEqual(self.d.empreinte_usine(), apres)

    def test_sync_journalise(self) -> None:
        self.d.specctl("sync", "--from", str(self.d.docs), "--json")
        lignes = (self.d.usine / "specs" / "registry" / "journal.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(lignes[-1])["command"], "sync")


class SyncSuitLesRenommages(BaseSync):
    """21/11 (HL-525 7-3200) : une matrice qui renomme ses lignes (E### → E-<table>-<élément>, `ancien_id`) ou décale
    ses identifiants ne fait pas « disparaître » des exigences : sync les retrouve par `ancien_id` à énoncé égal, puis
    par énoncé identique et unique ; l'avancement suit, l'identifiant du registre ne change pas."""

    def renommer(self, lignes) -> None:
        m = self.d.docs / "specs" / "jeu-a-conformite.json"
        mat = json.loads(m.read_text())
        mat["exigences"] = lignes(mat["exigences"])
        m.write_text(json.dumps(mat, ensure_ascii=False))
        self.d.commit("matrice renommée")

    def test_ancien_id_suivi_pas_de_disparition_ni_d_ajout(self) -> None:
        def f(ex):
            ex[1] = ex[1] | {"id": "E-p01-fin", "ancien_id": "E002"}
            return ex
        self.renommer(f)
        r = self.d.specctl("sync", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(r.json["missingFromMatrix"], [])
        self.assertEqual(r.json["renamed"], [{"id": "REQ-JEU-A-E002", "matrixId": "E-p01-fin", "by": "ancien_id"}])
        e = self.exigences()
        self.assertNotIn("REQ-JEU-A-E-P01-FIN", e)
        self.assertEqual((e["REQ-JEU-A-E002"]["matrixStatus"], e["REQ-JEU-A-E002"]["matrixId"]), ("faite", "E002"))

    def test_identifiant_decale_retrouve_par_enonce(self) -> None:
        def f(ex):
            ex[1] = ex[1] | {"id": "E009"}                                      # même énoncé, autre identifiant
            return ex
        self.renommer(f)
        r = self.d.specctl("sync", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.json["missingFromMatrix"], [])
        self.assertEqual(r.json["renamed"], [{"id": "REQ-JEU-A-E002", "matrixId": "E009", "by": "statement"}])
        self.assertEqual(self.exigences()["REQ-JEU-A-E002"]["matrixStatus"], "faite")

    def test_ancien_id_a_enonce_different_non_suivi(self) -> None:
        def f(ex):
            ex[1] = ex[1] | {"id": "E-p01-fin", "ancien_id": "E002"}
            ex[1]["source"] = ex[1]["source"] | {"extrait": "Autre chose."}
            return ex
        self.renommer(f)
        r = self.d.specctl("sync", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.json["missingFromMatrix"], ["REQ-JEU-A-E002"])
        self.assertEqual(r.json["renamed"], [])


class InscrireDrive(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()
        self.assertEqual(self.d.specctl("import", "--from", str(self.d.docs), "--json").rc, 0)
        self.listing = self.d.tmp / "drive.json"
        self.listing.write_text(json.dumps([{"id": DRIVE, "name": "Jeu_C_Specifications_v1.0.zip"}]))

    def tearDown(self) -> None:
        self.d.nettoyer()

    def statut(self) -> str:
        r = self.d.specctl("discover", "--source", "drive", "--listing", str(self.listing), "--json")
        return r.json["documents"][0]["status"]

    def test_document_inscrit_passe_de_new_a_pending(self) -> None:
        self.assertEqual(self.statut(), "new")
        r = self.d.specctl("inscrire-drive", "--drive", DRIVE, "--name", "Jeu_C_Specifications_v1.0.zip",
                           "--project", "jeu-c", "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(self.statut(), "pending")
        self.assertEqual(self.d.specctl("validate", "--json").rc, 0)

    def test_identifiant_invalide_refuse(self) -> None:
        r = self.d.specctl("inscrire-drive", "--drive", "pas un id", "--name", "x", "--project", "jeu-c", "--json")
        self.assertEqual(r.rc, 3, r)

    def test_inscription_idempotente(self) -> None:
        for _ in range(2):
            self.d.specctl("inscrire-drive", "--drive", DRIVE, "--name", "x.zip", "--project", "jeu-c", "--json")
        f = self.d.usine / "specs" / "registry" / "drive-a-importer.json"
        self.assertEqual(len(json.loads(f.read_text())), 1)


if __name__ == "__main__":
    unittest.main()
