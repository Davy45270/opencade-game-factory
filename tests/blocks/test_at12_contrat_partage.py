"""ARCH-001 AT-12 : un changement de contrat partagé remonte les jeux impactés.

Deux contrats partagés, deux chemins :
- une brique consommée par plusieurs jeux (module local d'un monorepo, ou bibliothèque npm sous deux versions) :
  `bbctl impact <brique> --to-version V` liste les jeux qui ne sont pas déjà en V, et REMONTE l'impact à la Tour
  (OPS-001) par un événement `bb.impact-detected` qui porte la brique, la version visée et les jeux touchés ;
- une spec partagée (REG-003) : `specctl impact` liste les projets consommateurs, directs puis transitifs, et émet
  `spec.impact-detected` (oracles T06 et T12 de tests/specs/test_specctl_reg003.py, rejoués par specs.yml).
"""
from __future__ import annotations

import json
import os
import unittest

from .test_bbctl_discover import Base


class AT12ContratPartage(Base):
    def setUp(self) -> None:
        super().setUp()
        self.assertEqual(self.decouvrir().rc, 0)
        self.tour = self.u.tmp / "tour"
        self.tour.mkdir()
        os.environ.update(TOWER_DIR=str(self.tour), TOWER_TRACE_ID="arch001-at12")

    def tearDown(self) -> None:
        os.environ.pop("TOWER_DIR", None)
        os.environ.pop("TOWER_TRACE_ID", None)
        super().tearDown()

    def evenements(self) -> list[dict]:
        f = self.tour / "inbox.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.is_file() else []

    def test_module_partage_remonte_les_deux_jeux(self) -> None:
        combat = self.par_nom("combat")[0]
        r = self.u.bbctl("impact", combat["id"], "--to-version", "2.0.0", "--json")
        self.assertEqual(r.json["impacted"], ["mono/alpha", "mono/beta"])
        (e,) = self.evenements()
        self.assertEqual((e["eventType"], e["traceId"], e["buildingBlockRefs"]),
                         ("bb.impact-detected", "arch001-at12", [combat["id"]]))
        self.assertEqual((e["metadata"]["projects"], e["metadata"]["toVersion"]), (["mono/alpha", "mono/beta"], "2.0.0"))

    def test_bibliotheque_partagee_seuls_les_jeux_en_retard(self) -> None:
        phaser = sorted(self.par_nom("phaser"), key=lambda b: b["origin"]["version"])
        r = self.u.bbctl("impact", phaser[1]["id"], "--to-version", "3.90.0", "--json")
        self.assertEqual(r.json["impacted"], ["mono"])                        # jeu-b est déjà en 3.90.0
        self.assertEqual(self.evenements()[0]["metadata"]["projects"], ["mono"])

    def test_aucun_jeu_touche_est_dit_aussi(self) -> None:
        phaser = sorted(self.par_nom("phaser"), key=lambda b: b["origin"]["version"])
        self.u.bbctl("impact", phaser[1]["id"], "--to-version", "3.80.1", "--json")
        self.u.bbctl("impact", phaser[0]["id"], "--to-version", "3.80.1", "--json")
        projets = [e["metadata"]["projects"] for e in self.evenements()]
        self.assertIn(["jeu-b"], projets)
        self.assertTrue(all(e["status"] == "success" for e in self.evenements()))


if __name__ == "__main__":
    unittest.main()
