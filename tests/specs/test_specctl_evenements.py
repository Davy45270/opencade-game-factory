"""Oracles du maillon « spec » de la tranche verticale ARCH-12 : `specctl resolve` informe la Control Tower.

Mesure du 20/11 (journal de la Tower) : aucun événement `spec.*`. La tranche ne pouvait donc pas montrer QUELLE version
de spec a servi. Contrat fixé ici :
  - succès → un FactoryEvent v1.1 `spec.resolved` (status success), `specRefs` = `SPEC-X@version`,
    `metadata.registryDigest` = celui de la sortie JSON ;
  - arbitrage requis (rc 5) → `spec.conflict` (status blocked), les versions en conflit dans `metadata` ;
  - `traceId` = `TOWER_TRACE_ID` s'il est bien formé, sinon absent ;
  - émission OPT-IN : seulement si `TOWER_DIR` ou `TOWER_TRACE_ID` est posé, et seulement dans un dossier qui EXISTE
    déjà (rien n'est créé, rien en CI) ; `TOWER_DESACTIVE=1` coupe tout ;
  - l'émission ne change JAMAIS le code de sortie ni la sortie JSON, même quand elle échoue ;
  - le même fait rejoué donne le même eventId (déduplication côté Tower).
Écrits AVANT le code."""
from __future__ import annotations

import json
import pathlib
import re
import unittest

from ._outil import SPEC_A, SPEC_A_V11, Docs


class EvenementsSpec(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()
        r = self.d.specctl("import", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 0, r)
        self.tour = self.d.tmp / "tour"
        self.tour.mkdir()

    def tearDown(self) -> None:
        self.d.nettoyer()

    def evenements(self, tour: pathlib.Path | None = None) -> list[dict]:
        f = (tour or self.tour) / "inbox.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.is_file() else []

    def resoudre(self, **env: str):
        return self.d.specctl("resolve", "--project", "jeu-a", "--json", env_tour=env)

    def test_resolution_emet_spec_resolved_avec_trace_et_specrefs(self) -> None:
        r = self.resoudre(TOWER_DIR=str(self.tour), TOWER_TRACE_ID="six-T1")
        self.assertEqual(r.rc, 0, r)
        evs = self.evenements()
        self.assertEqual(len(evs), 1, evs)
        e = evs[0]
        self.assertEqual((e["eventType"], e["status"], e["projectId"], e["traceId"]),
                         ("spec.resolved", "success", "jeu-a", "six-T1"))
        self.assertEqual(e["specRefs"], ["SPEC-JEU-A@1.0.0"])
        self.assertEqual(e["metadata"]["registryDigest"], r.json["registryDigest"])
        self.assertEqual(e["schemaVersion"], 1.1)
        for k in ("eventId", "occurredAt", "source", "portfolioId", "workflowId", "workflowVersion", "runId",
                  "evidence", "metadata"):
            self.assertIn(k, e)
        self.assertRegex(e["eventId"], r"^[A-Za-z0-9._:/@+-]{8,256}$")
        self.assertRegex(e["occurredAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")

    def test_meme_fait_rejoue_meme_event_id(self) -> None:
        self.resoudre(TOWER_DIR=str(self.tour), TOWER_TRACE_ID="six-T1")
        self.resoudre(TOWER_DIR=str(self.tour), TOWER_TRACE_ID="six-T1")
        ids = [e["eventId"] for e in self.evenements()]
        self.assertEqual(len(ids), 2)
        self.assertEqual(ids[0], ids[1])

    def test_conflit_emet_spec_conflict_bloque(self) -> None:
        self.d.archive("jeu-a", {"Jeu_A_v1.1.md.txt": SPEC_A_V11})
        self.d.commit("v1.1 déposée")
        self.assertEqual(self.d.specctl("import", "--from", str(self.d.docs), "--json").rc, 0)
        r = self.resoudre(TOWER_DIR=str(self.tour))
        self.assertEqual(r.rc, 5, r)
        (e,) = self.evenements()
        self.assertEqual((e["eventType"], e["status"]), ("spec.conflict", "blocked"))
        self.assertEqual(sorted(e["metadata"]["versions"]), ["1.0.0", "1.1.0"])
        self.assertNotIn("traceId", e)

    def test_sans_variable_tour_rien_n_est_emis(self) -> None:
        r = self.resoudre()
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(self.evenements(), [])

    def test_dossier_absent_jamais_cree_et_sortie_inchangee(self) -> None:
        absent = self.d.tmp / "pas-de-tour"
        r = self.resoudre(TOWER_DIR=str(absent), TOWER_TRACE_ID="six-T1")
        t = self.resoudre()
        self.assertEqual((r.rc, t.rc), (0, 0), (r, t))
        self.assertFalse(absent.exists())
        a, b = r.json, t.json
        a.pop("resolvedAt"); b.pop("resolvedAt")
        self.assertEqual(a, b)                                    # l'émission ne touche jamais la sortie

    def test_desactive_et_trace_mal_formee(self) -> None:
        self.resoudre(TOWER_DIR=str(self.tour), TOWER_DESACTIVE="1")
        self.assertEqual(self.evenements(), [])
        self.resoudre(TOWER_DIR=str(self.tour), TOWER_TRACE_ID="a b;rm")
        (e,) = self.evenements()
        self.assertNotIn("traceId", e)

    def test_emission_en_echec_ne_change_pas_le_code(self) -> None:
        bloque = self.tour / "inbox.jsonl"
        bloque.mkdir()                                            # la boîte d'arrivée n'est pas un fichier
        r = self.resoudre(TOWER_DIR=str(self.tour))
        self.assertEqual(r.rc, 0, r)
        self.assertTrue(r.json["specs"])

    def test_arbitrage_emet_spec_approved(self) -> None:
        self.d.archive("jeu-a", {"Jeu_A_v1.1.md.txt": SPEC_A_V11})
        self.d.commit("v1.1 déposée")
        self.assertEqual(self.d.specctl("import", "--from", str(self.d.docs), "--json").rc, 0)
        env = {"TOWER_DIR": str(self.tour), "TOWER_TRACE_ID": "six-T2"}
        refus = self.d.specctl("arbitrer", "--spec", "SPEC-JEU-A", "--version", "1.1.0", "--ref", "par l'agent",
                               "--json", env_tour=env)
        self.assertEqual(refus.rc, 3, refus)
        self.assertEqual(self.evenements(), [])                   # un refus n'est pas une approbation
        r = self.d.specctl("arbitrer", "--spec", "SPEC-JEU-A", "--version", "1.1.0", "--ref", "HL-0 7-0",
                           "--json", env_tour=env)
        self.assertEqual(r.rc, 0, r)
        (e,) = self.evenements()
        self.assertEqual((e["eventType"], e["status"], e["projectId"], e["traceId"]),
                         ("spec.approved", "success", "jeu-a", "six-T2"))
        self.assertEqual(e["specRefs"], ["SPEC-JEU-A@1.1.0"])
        self.assertEqual(e["metadata"]["ref"], "HL-0 7-0")

    def test_archive_modifiee_emet_spec_outdated(self) -> None:
        r = self.d.specctl("verify", "--from", str(self.d.docs), "--json", env_tour={"TOWER_DIR": str(self.tour)})
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(self.evenements(), [])                   # archive intacte : rien à signaler
        (self.d.docs / "specs/jeu-a-sources/Jeu_A_v1.0.md.txt").write_text(SPEC_A + "édition sauvage\n")
        self.d.commit("archive éditée")
        r = self.d.specctl("verify", "--from", str(self.d.docs), "--json", env_tour={"TOWER_DIR": str(self.tour)})
        self.assertEqual(r.rc, 2, r)
        (e,) = self.evenements()
        self.assertEqual((e["eventType"], e["status"], e["projectId"]), ("spec.outdated", "failure", "jeu-a"))
        self.assertEqual(e["specRefs"], ["SPEC-JEU-A"])
        self.assertEqual(e["metadata"]["paths"], ["specs/jeu-a-sources/Jeu_A_v1.0.md.txt"])

    def test_aucun_chemin_de_machine_dans_le_module(self) -> None:
        src = pathlib.Path(__file__).resolve().parents[2] / "specs" / "specctl"
        for p in src.glob("*.py"):
            self.assertIsNone(re.search(r"/home/|\bHL-\d+|zalman|tank01", p.read_text(), re.I), p)


if __name__ == "__main__":
    unittest.main()
