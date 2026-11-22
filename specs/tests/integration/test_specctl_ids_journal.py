"""Oracles du lot 4 REG-003 (HL-525), écrits AVANT le code : identifiants jamais recyclés (§ 2, registre d'IDs en
ajout seul, même mécanisme que catalog/ids.json d'assetctl) et écritures journalisées (§ 6, § 9 journal d'audit).

- `specs/registry/ids.json` : {identifiant: SPEC propriétaire}, tenu par chaque écriture du registre ;
  `specctl validate` refuse un identifiant de fiche absent du registre d'IDs ; `validate --base <ref>` refuse une clé
  retirée ou réattribuée par rapport à la base (contrôle de PR).
- `specs/registry/journal.jsonl` : une ligne par écriture QUI CHANGE une fiche (commande, spec, empreintes avant et
  après) ; une écriture sans effet n'ajoute rien (T08 inchangé).
"""
from __future__ import annotations

import json
import unittest

from specs.tools.specctl.fiche import refresh

from .._outil import Docs, git

REF = "HL-525 7-2955"


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()
        r = self.d.specctl("import", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 0, r)
        self.reg = self.d.usine / "specs" / "registry"

    def tearDown(self) -> None:
        self.d.nettoyer()

    def ids(self) -> dict:
        return json.loads((self.reg / "ids.json").read_text())

    def journal(self) -> list[dict]:
        f = self.reg / "journal.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.is_file() else []


class IdentifiantsJamaisRecycles(Base):
    def test_import_enregistre_les_identifiants(self) -> None:
        ids = self.ids()
        self.assertEqual(ids["SPEC-JEU-A"], "SPEC-JEU-A")
        self.assertEqual((ids["REQ-JEU-A-E001"], ids["REQ-JEU-A-E002"]), ("SPEC-JEU-A", "SPEC-JEU-A"))

    def test_identifiant_absent_du_registre_d_ids_refuse(self) -> None:
        ids = self.ids()
        del ids["REQ-JEU-A-E002"]
        (self.reg / "ids.json").write_text(json.dumps(ids))
        self.assertEqual(self.d.specctl("validate", "--json").rc, 2)

    def base(self) -> None:
        git(self.d.usine, "init", "-q", "-b", "main")
        git(self.d.usine, "add", "specs")
        git(self.d.usine, "commit", "-q", "-m", "base")

    def test_cle_retiree_par_rapport_a_la_base_refusee(self) -> None:
        self.base()
        self.assertEqual(self.d.specctl("validate", "--base", "HEAD", "--json").rc, 0)
        fiche = json.loads((self.reg / "games" / "SPEC-JEU-A.json").read_text())
        fiche["requirements"] = fiche["requirements"][:1]                      # exigence retirée de la fiche : permis
        refresh(fiche)                                                          # statuts déduits recalculés
        (self.reg / "games" / "SPEC-JEU-A.json").write_text(json.dumps(fiche))
        ids = self.ids()
        del ids["REQ-JEU-A-E002"]                                               # mais son identifiant ne disparaît pas
        (self.reg / "ids.json").write_text(json.dumps(ids))
        r = self.d.specctl("validate", "--base", "HEAD", "--json")
        self.assertEqual(r.rc, 2, r)
        self.assertIn("REQ-JEU-A-E002", r.stdout)

    def test_cle_reattribuee_refusee(self) -> None:
        self.base()
        ids = self.ids()
        ids["REQ-JEU-A-E002"] = "SPEC-JEU-B"
        (self.reg / "ids.json").write_text(json.dumps(ids))
        self.assertEqual(self.d.specctl("validate", "--base", "HEAD", "--json").rc, 2)

    def test_base_inconnue_entree_invalide(self) -> None:
        self.base()
        self.assertEqual(self.d.specctl("validate", "--base", "inexistante", "--json").rc, 3)


class EcrituresJournalisees(Base):
    def test_import_initial_journalise(self) -> None:
        lignes = self.journal()
        self.assertEqual(sorted(l["specId"] for l in lignes), ["SPEC-JEU-A", "SPEC-JEU-B"])
        self.assertEqual({l["command"] for l in lignes}, {"import"})
        self.assertTrue(all(l["sha256Before"] is None and len(l["sha256After"]) == 64 for l in lignes))

    def test_ecriture_qui_change_journalisee_une_fois(self) -> None:
        n = len(self.journal())
        for _ in range(2):
            r = self.d.specctl("statuer", "--spec", "SPEC-JEU-A", "--lifecycle", "approved", "--ref", REF, "--json")
            self.assertEqual(r.rc, 0, r)
        lignes = self.journal()[n:]
        self.assertEqual([(l["command"], l["specId"]) for l in lignes], [("statuer", "SPEC-JEU-A")])
        self.assertNotEqual(lignes[0]["sha256Before"], lignes[0]["sha256After"])

    def test_dry_run_et_lecture_ne_journalisent_rien(self) -> None:
        avant = (self.reg / "journal.jsonl").read_bytes()
        self.d.specctl("import", "--from", str(self.d.docs), "--dry-run", "--json")
        self.d.specctl("resolve", "--project", "jeu-a", "--json")
        self.d.specctl("import", "--from", str(self.d.docs), "--json")         # relance sans changement
        self.assertEqual((self.reg / "journal.jsonl").read_bytes(), avant)


if __name__ == "__main__":
    unittest.main()
