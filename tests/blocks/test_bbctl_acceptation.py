"""Oracles d'acceptation du module blocks/ (BB-001 : BB-01, BB-05, BB-07 ; BB-T03, T04, T05, T12 ; import des décisions
de réutilisation de pestouille-rpg).

Écrits AVANT le code (Claude, oracle) : ils échouent tant que `bbctl` n'existe pas. L'implémentation (Codex) les fait
passer SANS les modifier. Hors de ce lot : BB-02/03 (graphify le fait), BB-06 (open source), BB-08 (gate CI, en dernier,
d'abord en avertissement — HL-525 7-2953 point 7). Contrat d'appel : tests/blocks/_outil.py.
"""
from __future__ import annotations

import json
import os
import re
import unittest

from ._outil import BBCTL, COMMIT_PESTOUILLE, DECISIONS, Usine, fiche, sha

TYPES = ["internal-package", "shared-library", "game-local-module", "external-library", "cli-tool", "service", "template",
         "algorithm", "test-harness", "workflow", "generator", "renderer-adapter"]
STATUTS = ["discovered", "candidate", "evaluated", "approved", "adopted", "deprecated", "rejected", "blocked"]


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()

    def tearDown(self) -> None:
        self.u.nettoyer()


# ---------------------------------------------------------------------------------------------------------------- BB-01
class BB01ContratEtSchemas(Base):
    def schema(self) -> dict:
        p = BBCTL.parent / "blocks" / "schemas" / "block.schema.json"
        self.assertTrue(p.is_file(), p)
        return json.loads(p.read_text())

    def test_schema_valide_et_conforme_au_contrat(self) -> None:
        import jsonschema
        s = self.schema()
        jsonschema.Draft202012Validator.check_schema(s)
        for cle in ("schemaVersion", "id", "name", "kind", "origin", "capabilities", "interfaces", "specIds", "usedBy",
                    "quality", "decision", "provenance"):
            self.assertIn(cle, s["required"], cle)
        self.assertEqual(sorted(s["properties"]["kind"]["enum"]), sorted(TYPES))
        jsonschema.Draft202012Validator(s).validate(fiche())          # l'exemple d'une brique interne est valide

    def test_catalogue_valide(self) -> None:
        r = self.u.bbctl("validate", "--all", "--json")
        self.assertEqual(r.rc, 0, r)

    def test_id_en_double_refuse(self) -> None:
        self.u.poser(fiche(), nom="BB-SIX-PATHFINDING-001-copie")
        r = self.u.bbctl("validate", "--all", "--json")
        self.assertEqual(r.rc, 1, r)
        self.assertIn("BB-SIX-PATHFINDING-001", r.stdout)

    def test_id_invalide_refuse(self) -> None:
        self.u.poser(fiche("bb-pathfinding"), nom="bb-pathfinding")
        self.assertEqual(self.u.bbctl("validate", "--all", "--json").rc, 1)

    def test_type_hors_enumeration_refuse(self) -> None:
        self.u.poser(fiche("BB-X-001", kind="framework"))
        self.assertEqual(self.u.bbctl("validate", "--all", "--json").rc, 1)

    def test_statut_hors_enumeration_refuse(self) -> None:
        self.u.poser(fiche("BB-X-001", quality={"status": "génial", "sbomRef": None, "securityReportRef": None}))
        self.assertEqual(self.u.bbctl("validate", "--all", "--json").rc, 1)

    def test_licence_inventee_refusee(self) -> None:
        # « Licence ImageMagick » n'est pas un identifiant SPDX : on écrit UNKNOWN, jamais une licence devinée.
        o = {**fiche()["origin"], "licenseSpdx": "Licence ImageMagick"}
        self.u.poser(fiche("BB-X-001", origin=o))
        self.assertEqual(self.u.bbctl("validate", "--all", "--json").rc, 1)
        o["licenseSpdx"] = "UNKNOWN"
        self.u.poser(fiche("BB-X-001", origin=o))
        self.assertEqual(self.u.bbctl("validate", "--all", "--json").rc, 0)


# ------------------------------------------------------------------------------------- import des décisions (pestouille)
class ImportDecisions(Base):
    def importer(self, *extra: str):
        return self.u.bbctl("import-decisions", "--from", str(DECISIONS), "--repo", "pestouille-rpg",
                            "--commit", COMMIT_PESTOUILLE, "--json", *extra)

    def decisions(self) -> dict[str, dict]:
        d = self.u.usine / "blocks" / "decisions" / "pestouille-rpg"
        return {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))} if d.is_dir() else {}

    def test_les_16_fiches_de_decision_importees_l_inventaire_ecarte(self) -> None:
        avant = self.u.empreinte(DECISIONS)
        r = self.importer()
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(len(self.decisions()), 16)
        self.assertEqual([i["path"] for i in r.json["ignored"]], ["inventaire.md"])   # index des fiches, pas une décision
        self.assertEqual(self.u.empreinte(DECISIONS), avant)                           # lecture seule

    def test_provenance_par_commit_et_empreinte(self) -> None:
        self.importer()
        d = self.decisions()["atlas-des-planches"]
        brut = (DECISIONS / "atlas-des-planches.md").read_bytes()
        self.assertEqual(d["source"], {"repo": "pestouille-rpg", "path": "docs/reuse-decisions/atlas-des-planches.md",
                                       "commitSha": COMMIT_PESTOUILLE, "sha256": sha(brut)})
        self.assertRegex(d["id"], r"^DEC-PESTOUILLE-RPG-[A-Z0-9-]+$")

    def test_candidats_lus_par_en_tete_sans_licence_inventee(self) -> None:
        self.importer()
        atlas = self.decisions()["atlas-des-planches"]["candidates"]
        self.assertEqual(len(atlas), 11)   # la fiche figée compte 11 lignes de candidats (12 à 22)
        phaser = atlas[0]
        self.assertEqual((phaser["candidate"], phaser["licenseRaw"], phaser["licenseSpdx"]),
                         ("Phaser, chargeur JSON hash", "MIT", "MIT"))
        magick = next(c for c in atlas if c["candidate"] == "ImageMagick")
        self.assertEqual((magick["licenseRaw"], magick["licenseSpdx"]), ("Licence ImageMagick", "UNKNOWN"))
        navigateur = next(c for c in atlas if c["candidate"] == "localStorage natif")
        self.assertEqual(navigateur["licenseSpdx"], "UNKNOWN")
        # Les colonnes varient d'une fiche à l'autre (Choix, Décision, Constat ; Version présente ou non).
        combat = self.decisions()["combat-versionne"]["candidates"]
        self.assertTrue(combat and all("version" in c and c["verdict"] for c in combat), combat)

    def test_T03_import_relance_aucune_duplication(self) -> None:
        self.importer()
        d = self.u.usine / "blocks" / "decisions"
        avant = self.u.empreinte(d)
        r = self.importer()
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(self.u.empreinte(d), avant)

    def test_dry_run_n_ecrit_rien(self) -> None:
        r = self.importer("--dry-run")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(len(r.json["decisions"]), 16)
        self.assertEqual(self.decisions(), {})


# ---------------------------------------------------------------------------------------------------------------- BB-05
class BB05RechercheInterne(Base):
    def chercher(self, *extra: str):
        return self.u.bbctl("search", "--query", "path", "--scope", "internal", "--graph", str(self.u.graphe), "--json", *extra)

    def test_recherche_dans_graphify_tous_jeux_confondus(self) -> None:
        r = self.chercher()
        self.assertEqual(r.rc, 0, r)
        noeuds = {x["graphNode"] for x in r.json["results"]}
        self.assertEqual(noeuds, {"six-de-chaque::packages_engine_src_pathfinding_findpath",
                                  "capsule-panic::src_game_grid_path_gridpath"})
        x = next(x for x in r.json["results"] if x["repo"] == "six-de-chaque")
        self.assertEqual((x["sourceFile"], x["location"]), ("packages/engine/src/pathfinding.ts", "L12"))

    def test_resultat_joint_a_la_fiche_de_brique(self) -> None:
        r = self.chercher()
        par_depot = {x["repo"]: x for x in r.json["results"]}
        self.assertEqual(par_depot["six-de-chaque"]["block"], "BB-SIX-PATHFINDING-001")
        self.assertIsNone(par_depot["capsule-panic"]["block"])          # trouvé par graphify, sans fiche : proposé

    def test_filtres(self) -> None:
        r = self.chercher("--repo", "capsule-panic")
        self.assertEqual([x["repo"] for x in r.json["results"]], ["capsule-panic"])
        r = self.chercher("--kind", "game-local-module")
        self.assertEqual([x["block"] for x in r.json["results"]], ["BB-SIX-PATHFINDING-001"])

    def test_recu_de_recherche_tracable(self) -> None:
        recu = self.u.tmp / "recu.json"
        r = self.chercher("--receipt", str(recu))
        self.assertEqual(r.rc, 0, r)
        v = json.loads(recu.read_text())
        self.assertEqual((v["query"], v["scope"]), ("path", "internal"))
        self.assertEqual(v["graphSha256"], sha(self.u.graphe.read_bytes()))
        self.assertEqual(sorted(v["results"]), sorted(x["graphNode"] for x in r.json["results"]))
        self.assertRegex(v["at"], r"^\d{4}-\d{2}-\d{2}T")

    def test_T12_graphe_indisponible_erreur_explicite_aucun_resultat_invente(self) -> None:
        r = self.u.bbctl("search", "--query", "path", "--scope", "internal", "--graph", str(self.u.tmp / "absent.json"), "--json")
        self.assertEqual(r.rc, 4, r)
        self.assertEqual(r.json["status"], "source-unavailable")
        self.assertNotIn("results", r.json)

    def test_reference_externe_sans_fichier_ignoree_pas_tout_le_graphe(self) -> None:
        # Graphe réel du 22/11 : 519 nœuds sur 57 732 sont des références externes (imports : `FastMCP`, `Any`) sans
        # source_file, parfois sans repo. Ils ne sont pas des briques candidates ; un seul d'entre eux rendait tout le
        # graphe « indisponible » (étape 2 de la tranche ARCH-12 bloquée).
        g = json.loads(self.u.graphe.read_text())
        g["nodes"] += [{"id": "homelab-diag::fastmcp", "label": "FastMCP", "repo": "homelab-diag", "source_file": ""},
                       {"id": "anypath", "label": "path", "source_file": ""}]
        self.u.graphe.write_text(json.dumps(g))
        r = self.chercher()
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(len(r.json["results"]), 2)
        self.assertEqual(r.json["externalReferencesSkipped"], 2)

    def test_recherche_tracee_dans_la_tour(self) -> None:
        # Étape 2 d'ARCH-001 § 10 : la recherche de briques est un maillon observable de la tranche (traceId).
        tour = self.u.tmp / "tour"
        tour.mkdir()
        try:
            os.environ.update(TOWER_DIR=str(tour), TOWER_TRACE_ID="arch12-essai")
            self.chercher("--repo", "six-de-chaque")
        finally:
            os.environ.pop("TOWER_DIR", None), os.environ.pop("TOWER_TRACE_ID", None)
        (e,) = [json.loads(l) for l in (tour / "inbox.jsonl").read_text().splitlines()]
        self.assertEqual((e["eventType"], e["projectId"], e["traceId"]), ("bb.searched", "six-de-chaque", "arch12-essai"))
        self.assertEqual((e["metadata"]["results"], e["metadata"]["scope"]), (1, "internal"))

    def test_noeud_sans_identifiant_reste_mal_forme(self) -> None:
        g = json.loads(self.u.graphe.read_text())
        g["nodes"].append({"label": "path", "repo": "six-de-chaque", "source_file": "a.ts"})
        self.u.graphe.write_text(json.dumps(g))
        r = self.chercher()
        self.assertEqual((r.rc, r.json["status"]), (4, "source-unavailable"))

    def test_aucun_resultat_est_un_succes_vide(self) -> None:
        r = self.u.bbctl("search", "--query", "zzz-introuvable", "--scope", "internal", "--graph", str(self.u.graphe), "--json")
        self.assertEqual((r.rc, r.json["results"]), (0, []))


# ---------------------------------------------------------------------------------------------------------------- BB-07
SCORES = {"adequation": 4, "integration": 3, "maintenance": 5, "licence": 5, "securite": 4, "cout": 2}


def evaluation(**change) -> dict:
    e = {"candidate": "BB-SIX-PATHFINDING-001", "date": "2026-11-19",
         "gates": {"security": {"critical": 0, "accepted": False}, "provenance": "known", "technical": "ok"},
         "scores": {k: {"score": v, "preuve": f"mesure {k}"} for k, v in SCORES.items()}}
    e.update(change)
    return e


class BB07MatriceDeDecision(Base):
    def poser_eval(self, e: dict) -> None:
        d = self.u.usine / "blocks" / "evaluations"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{e['candidate']}.json").write_text(json.dumps(e, ensure_ascii=False))

    def evaluer(self, cand: str = "BB-SIX-PATHFINDING-001"):
        return self.u.bbctl("evaluate", "--candidate", cand, "--json")

    def test_score_pondere(self) -> None:
        # 25 % adéquation, 20 % intégration, 15 % maintenance, 15 % licence, 15 % sécurité, 10 % coût complet
        self.poser_eval(evaluation())
        r = self.evaluer()
        self.assertEqual(r.rc, 0, r)
        self.assertEqual((r.json["eliminated"], r.json["score"]), (False, 3.9))

    def test_T04_licence_inconnue_eliminee_avant_le_score(self) -> None:
        o = {**fiche()["origin"], "licenseSpdx": "UNKNOWN"}
        self.u.poser(fiche(origin=o))
        self.poser_eval(evaluation())
        r = self.evaluer()
        self.assertEqual(r.rc, 0, r)
        self.assertTrue(r.json["eliminated"])
        self.assertIsNone(r.json["score"])
        self.assertIn("license", json.dumps(r.json["gates"]))

    def test_T05_vulnerabilite_critique_non_acceptee_eliminee(self) -> None:
        self.poser_eval(evaluation(gates={"security": {"critical": 1, "accepted": False}, "provenance": "known", "technical": "ok"}))
        r = self.evaluer()
        self.assertTrue(r.json["eliminated"])
        self.assertIsNone(r.json["score"])

    def test_provenance_inconnue_eliminee(self) -> None:
        self.poser_eval(evaluation(gates={"security": {"critical": 0, "accepted": False}, "provenance": "unknown", "technical": "ok"}))
        self.assertTrue(self.evaluer().json["eliminated"])

    def test_score_sans_preuve_refuse(self) -> None:
        e = evaluation()
        e["scores"]["cout"] = {"score": 2}
        self.poser_eval(e)
        self.assertEqual(self.evaluer().rc, 1)

    def test_score_hors_echelle_refuse(self) -> None:
        e = evaluation()
        e["scores"]["adequation"]["score"] = 7
        self.poser_eval(e)
        self.assertEqual(self.evaluer().rc, 1)

    def test_evaluation_absente(self) -> None:
        self.assertEqual(self.evaluer().rc, 1)

    def test_decision_justifiee(self) -> None:
        self.poser_eval(evaluation())
        r = self.u.bbctl("decide", "--candidate", "BB-SIX-PATHFINDING-001", "--choice", "reuse",
                         "--reason", "déjà pur et testé ; même grille", "--json")
        self.assertEqual(r.rc, 0, r)
        f = json.loads((self.u.usine / "blocks/catalog/BB-SIX-PATHFINDING-001.json").read_text())
        self.assertEqual((f["decision"]["choice"], f["decision"]["rationale"]), ("reuse", "déjà pur et testé ; même grille"))

    def test_decision_sans_justification_ou_choix_inconnu(self) -> None:
        self.poser_eval(evaluation())
        self.assertEqual(self.u.bbctl("decide", "--candidate", "BB-SIX-PATHFINDING-001", "--choice", "reuse",
                                      "--reason", " ", "--json").rc, 2)
        self.assertEqual(self.u.bbctl("decide", "--candidate", "BB-SIX-PATHFINDING-001", "--choice", "copier",
                                      "--reason", "x", "--json").rc, 2)

    def test_reutiliser_un_candidat_elimine_refuse(self) -> None:
        self.poser_eval(evaluation(gates={"security": {"critical": 2, "accepted": False}, "provenance": "known", "technical": "ok"}))
        r = self.u.bbctl("decide", "--candidate", "BB-SIX-PATHFINDING-001", "--choice", "reuse", "--reason", "pressé", "--json")
        self.assertEqual(r.rc, 3, r)


class CliCommune(Base):
    def test_aide_et_codes(self) -> None:
        r = self.u.bbctl("--help")
        self.assertEqual(r.rc, 0, r)
        for code in "012345":
            self.assertRegex(r.stdout, rf"(?m)^\s*{code}\b")
        for cmd in ("validate", "search", "evaluate", "decide", "import-decisions"):
            self.assertIn(cmd, r.stdout)
        self.assertEqual(self.u.bbctl("inventer").rc, 2)
        self.assertTrue(re.search(r"graphify", r.stdout, re.I), "l'aide dit que la recherche interne passe par graphify")


if __name__ == "__main__":
    unittest.main()
