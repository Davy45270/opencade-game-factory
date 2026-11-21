"""Oracles du lot 2 REG-003 (HL-525) : écrits AVANT le code du lot, vus rouges sur la base (usine + lot 1).

Couvre : codes de retour de REG-003 § 6 (0, 2, 3, 4, 5) ; fiche complète (§ 2, § 4) ; approbation humaine (§ 2) ;
CLI § 6 (discover, search, impact, verify --project/--commit, compare, export, lock) ; rapport de migration (§ 5) ;
liens BB-001 par identifiant (§ 7) ; versions incompatibles (§ 4) ; tests d'acceptation T01, T03, T04, T06, T09, T11.
Contrat d'appel : tests/specs/_outil.py (USINE_RACINE temporaire, homelab-docs jetable, jamais le dépôt réel).
"""
from __future__ import annotations

import json
import pathlib
import unittest

from ._outil import SPEC_A, SPEC_A_V11, Docs, git, sha

REF = "HL-525 7-2955"
DRIVE_ID = "1UhUySPtM6ImF_bhm6ozlNnEuhHChd2Se"


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()

    def tearDown(self) -> None:
        self.d.nettoyer()

    def ok(self, *args: str):
        r = self.d.specctl(*args, "--json")
        self.assertEqual(r.rc, 0, r)
        return r.json

    def importer(self):
        return self.ok("import", "--from", str(self.d.docs))

    def fiche(self, spec: str = "SPEC-JEU-A") -> dict:
        return self.d.registre()[spec]

    def ecrire(self, spec: str, fiche: dict) -> None:
        (self.d.usine / "specs" / "registry" / f"{spec}.json").write_text(json.dumps(fiche, ensure_ascii=False))


# ------------------------------------------------------------------------------------------------- § 6 codes de retour
class CodesReg003(Base):
    def test_aide_donne_la_table_de_la_spec(self) -> None:
        r = self.d.specctl("--help")
        for ligne in ("2  Non-conformité", "3  Entrée invalide", "4  Source indisponible", "5  Conflit de versions"):
            self.assertIn(ligne, r.stdout)

    def test_non_conformite_rend_2(self) -> None:
        self.importer()
        self.assertEqual(self.d.specctl("resolve", "--project", "inconnu", "--json").rc, 2)

    def test_entree_invalide_rend_3(self) -> None:
        self.assertEqual(self.d.specctl("inventer").rc, 3)
        self.assertEqual(self.d.specctl("import", "--json").rc, 3)

    def test_source_indisponible_4_et_conflit_5(self) -> None:
        self.assertEqual(self.d.specctl("import", "--from", str(self.d.tmp / "absent"), "--json").rc, 4)
        self.d.archive("jeu-a", {"Jeu_A_v1.1.md.txt": SPEC_A_V11})
        self.d.commit("v1.1")
        self.importer()
        self.assertEqual(self.d.specctl("resolve", "--project", "jeu-a", "--json").rc, 5)


# ----------------------------------------------------------------------------------------------- § 2 et § 4 : la fiche
class FicheComplete(Base):
    def test_fiche_porte_titre_proprietaire_statuts_origine(self) -> None:
        self.importer()
        f = self.fiche()
        self.assertEqual(f["title"], "Jeu A")                                  # premier titre Markdown du document
        self.assertEqual(f["owner"], "david")
        self.assertEqual((f["lifecycle"], f["visibility"]), ("draft", "private"))
        self.assertEqual(f["canonical"]["editableIn"], "usine")              # une seule origine éditable
        self.assertEqual(f["canonical"]["path"], "specs/registry/SPEC-JEU-A.json")
        self.assertEqual(f["canonical"]["importedFrom"]["commitSha"], git(self.d.docs, "rev-parse", "HEAD"))
        self.assertEqual(f["importOrigins"]["authority"], "usine")           # Drive ne fait plus autorité

    def test_statuts_orthogonaux_deduits_des_exigences(self) -> None:
        self.importer()
        f = self.fiche()                                                      # E001 faite sans preuve, E002 à faire
        self.assertEqual((f["implementation"], f["evidence"]), ("partial", "missing"))
        self.assertEqual(self.fiche("SPEC-JEU-B")["implementation"], "not-started")

    def test_statut_deduit_falsifie_refuse(self) -> None:
        self.importer()
        f = self.fiche()
        f["implementation"] = "verified"
        self.ecrire("SPEC-JEU-A", f)
        self.assertEqual(self.d.specctl("validate", "--json").rc, 2)

    def test_identifiant_drive_releve_du_manifeste(self) -> None:
        m = self.d.docs / "specs" / "jeu-a-sources" / "empreintes-drive.sha256"
        m.write_text(f"# Spec : Drive {DRIVE_ID} (.md)\n" + m.read_text())
        self.d.commit("drive")
        self.importer()
        self.assertEqual(self.fiche()["importOrigins"]["drive"], [DRIVE_ID])
        r = self.ok("discover", "--source", "drive", "--listing", str(self._listing()))
        self.assertEqual({x["driveId"]: x["status"] for x in r["documents"]}, {DRIVE_ID: "known", "1" + "x" * 32: "new"})

    def _listing(self) -> pathlib.Path:
        p = self.d.tmp / "drive.json"
        p.write_text(json.dumps([{"id": DRIVE_ID, "name": "REG-003.md"}, {"id": "1" + "x" * 32, "name": "neuf.md"}]))
        return p


# -------------------------------------------------------------------------------------------- § 2 approbation humaine
class ApprobationHumaine(Base):
    def test_approuver_sans_reference_de_david_refuse(self) -> None:
        self.importer()
        r = self.d.specctl("statuer", "--spec", "SPEC-JEU-A", "--lifecycle", "approved", "--json")
        self.assertEqual(r.rc, 3, r)
        self.assertEqual(self.fiche()["lifecycle"], "draft")

    def test_approuver_avec_reference(self) -> None:
        self.importer()
        self.ok("statuer", "--spec", "SPEC-JEU-A", "--lifecycle", "approved", "--ref", REF)
        f = self.fiche()
        self.assertEqual((f["lifecycle"], f["lifecycleRef"]), ("approved", REF))

    def test_deprecier_ou_publier_exigent_la_reference(self) -> None:
        self.importer()
        for args in (("--lifecycle", "deprecated"), ("--lifecycle", "retired"), ("--visibility", "public")):
            self.assertEqual(self.d.specctl("statuer", "--spec", "SPEC-JEU-A", *args, "--json").rc, 3, args)

    def test_fiche_approuvee_sans_reference_refusee_a_la_lecture(self) -> None:
        self.importer()
        f = self.fiche()
        f["lifecycle"] = "approved"
        self.ecrire("SPEC-JEU-A", f)
        self.assertEqual(self.d.specctl("validate", "--json").rc, 2)


# ------------------------------------------------------------------------------------------------------------- § 6 CLI
class Recherche(Base):
    def test_search_trouve_l_exigence(self) -> None:
        self.importer()
        r = self.ok("search", "réserve vide")
        self.assertEqual(r["hits"][0]["id"], "REQ-JEU-A-E002")
        self.assertEqual(r, self.ok("search", "réserve vide"))                # déterministe

    def test_search_vide_entree_invalide(self) -> None:
        self.importer()
        self.assertEqual(self.d.specctl("search", "  ", "--json").rc, 3)


class Impact(Base):
    def test_T06_changement_partage_projets_consommateurs(self) -> None:
        self.d.archive("socle", {"Socle_v1.0.md.txt": "# Socle\n\nRègle commune.\n"})
        self.d.commit("socle")
        self.importer()
        self.ok("relier", "--spec", "SPEC-JEU-A", "--type", "consumes", "--target", "SPEC-SOCLE")
        self.ok("relier", "--spec", "SPEC-JEU-B", "--type", "requires", "--target", "SPEC-JEU-A")
        r = self.ok("impact", "--spec", "SPEC-SOCLE")
        self.assertEqual(r["projects"], ["jeu-a", "jeu-b"])                  # direct, puis transitif
        self.assertEqual([c["depth"] for c in r["consumers"]], [1, 2])
        self.assertEqual(self.ok("impact", "--spec", "SPEC-JEU-B")["projects"], [])

    def test_relier_vers_une_spec_absente_refuse(self) -> None:
        self.importer()
        self.assertEqual(self.d.specctl("relier", "--spec", "SPEC-JEU-A", "--type", "consumes", "--target",
                                        "SPEC-ABSENTE", "--json").rc, 2)

    def test_version_incompatible_detectee(self) -> None:
        self.importer()
        self.ok("relier", "--spec", "SPEC-JEU-B", "--type", "requires", "--target", "SPEC-JEU-A", "--range", "^2.0.0")
        r = self.d.specctl("verify", "--json")
        self.assertEqual(r.rc, 2, r)
        self.assertEqual([x["target"] for x in r.json["incompatibleVersions"]], ["SPEC-JEU-A"])
        self.ok("relier", "--spec", "SPEC-JEU-B", "--type", "requires", "--target", "SPEC-JEU-A", "--range", "^1.0.0")
        self.assertEqual(self.d.specctl("verify", "--json").rc, 0)


class VerrouDePr(Base):
    """T03 : une PR fondée sur une spec périmée est bloquée (verrou `.woodpecker/usine/spec.json` du commit)."""

    def jeu(self, version: str) -> tuple[pathlib.Path, str]:
        depot = self.d.tmp / "jeu-a"
        if not depot.exists():
            depot.mkdir()
            git(depot, "init", "-q", "-b", "main")
        f = depot / ".woodpecker" / "usine" / "spec.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"project": "jeu-a", "specId": "SPEC-JEU-A", "version": version, "status": "ok"}))
        git(depot, "add", ".woodpecker")
        git(depot, "commit", "-q", "-m", version)
        return depot, git(depot, "rev-parse", "HEAD")

    def test_T03_pr_sur_spec_perimee_bloquee(self) -> None:
        self.importer()
        depot, a_jour = self.jeu("1.0.0")
        self.assertEqual(self.ok("verify", "--project", "jeu-a", "--commit", a_jour, "--repo", str(depot))["status"], "ok")
        self.d.archive("jeu-a", {"Jeu_A_v1.1.md.txt": SPEC_A_V11})
        self.d.commit("v1.1")
        self.importer()
        self.ok("arbitrer", "--spec", "SPEC-JEU-A", "--version", "1.1.0", "--ref", REF)
        r = self.d.specctl("verify", "--project", "jeu-a", "--commit", a_jour, "--repo", str(depot), "--json")
        self.assertEqual(r.rc, 2, r)
        self.assertEqual((r.json["status"], r.json["reasons"]), ("outdated", ["version"]))

    def test_commit_introuvable_source_indisponible(self) -> None:
        self.importer()
        depot, _ = self.jeu("1.0.0")
        r = self.d.specctl("verify", "--project", "jeu-a", "--commit", "0" * 40, "--repo", str(depot), "--json")
        self.assertEqual(r.rc, 4, r)

    def test_lock_semver_empreinte_horodatage(self) -> None:
        self.importer()
        r = self.ok("lock", "--project", "jeu-a")
        self.assertEqual([(s["specId"], s["version"]) for s in r["specs"]], [("SPEC-JEU-A", "1.0.0")])
        self.assertRegex(r["specs"][0]["specDigest"], "^[0-9a-f]{64}$")
        self.assertIn("resolvedAt", r)


class Comparaison(Base):
    def test_compare_deux_etats_du_registre(self) -> None:
        self.importer()
        git(self.d.usine, "init", "-q", "-b", "main")
        git(self.d.usine, "add", "specs")
        git(self.d.usine, "commit", "-q", "-m", "avant")
        self.ok("statuer", "--spec", "SPEC-JEU-A", "--lifecycle", "approved", "--ref", REF)
        git(self.d.usine, "add", "-u", "specs")
        git(self.d.usine, "commit", "-q", "-m", "après")
        r = self.ok("compare", "--from", "HEAD~1", "--to", "HEAD")
        self.assertEqual([(c["specId"], c["fieldsChanged"]) for c in r["changes"]],
                         [("SPEC-JEU-A", ["lifecycle", "lifecycleRef"])])

    def test_compare_hors_git_source_indisponible(self) -> None:
        self.importer()
        self.assertEqual(self.d.specctl("compare", "--from", "HEAD~1", "--to", "HEAD", "--json").rc, 4)


class Export(Base):
    def test_T09_spec_privee_jamais_dans_l_export_public(self) -> None:
        self.importer()
        self.ok("statuer", "--spec", "SPEC-JEU-B", "--visibility", "public", "--ref", REF)
        for fmt in ("json", "markdown"):
            r = self.d.specctl("export", "--format", fmt, "--public", "--json")
            self.assertEqual(r.rc, 0, r)
            self.assertNotIn("SPEC-JEU-A", r.stdout)
            self.assertNotIn("pose une tuile", r.stdout)                      # ni l'id, ni le texte d'une exigence privée
            self.assertNotIn("homelab-docs", r.stdout)                        # ni la provenance
            self.assertIn("SPEC-JEU-B", r.stdout)

    def test_export_complet_prive(self) -> None:
        self.importer()
        r = self.ok("export", "--format", "markdown")
        self.assertEqual(r["classification"], "private")
        self.assertIn("## SPEC-JEU-A — Jeu A", r["markdown"])


class Decouverte(Base):
    def test_discover_docs_lecture_seule(self) -> None:
        avant = self.d.empreinte_docs()
        r = self.ok("discover", "--source", "docs", "--from", str(self.d.docs))
        self.assertEqual({x["status"] for x in r["documents"]}, {"new"})
        self.importer()
        r = self.ok("discover", "--source", "docs", "--from", str(self.d.docs))
        connus = {x["path"]: x["knownAs"] for x in r["documents"] if x["status"] == "known"}
        self.assertEqual(connus["specs/jeu-a-sources/Jeu_A_v1.0.md.txt"], "SPEC-JEU-A")
        self.assertEqual(self.d.empreinte_docs(), avant)

    def test_discover_github_copies_locales(self) -> None:
        clones = self.d.tmp / "clones"
        depot = clones / "jeu-x"
        depot.mkdir(parents=True)
        git(depot, "init", "-q", "-b", "main")
        (depot / "docs").mkdir()
        (depot / "docs" / "specification.md").write_text(SPEC_A)
        (depot / "src.ts").write_text("export {}\n")
        git(depot, "add", ".")
        git(depot, "commit", "-q", "-m", "x")
        sources = self.d.tmp / "sources.json"
        sources.write_text(json.dumps({"sources": [{"name": "jeu-x"}, {"name": "absent"}]}))
        r = self.ok("discover", "--source", "github", "--sources", str(sources), "--clones", str(clones))
        self.assertEqual([(x["repo"], x["path"]) for x in r["documents"]], [("jeu-x", "docs/specification.md")])
        self.assertEqual(r["documents"][0]["sha256"], sha(SPEC_A.encode()))
        self.assertEqual((r["status"], [u["repo"] for u in r["unavailable"]]), ("partial", ["absent"]))

    def test_T04_drive_indisponible_n_est_pas_une_non_conformite(self) -> None:
        r = self.d.specctl("discover", "--source", "drive", "--json")
        self.assertEqual((r.rc, r.json["status"]), (4, "source-unavailable"))


class RapportDeMigration(Base):
    def test_rapport_correspondance_doublons_conflits_inconnus(self) -> None:
        self.d.archive("jeu-a", {"zip-extrait/Jeu_A_v1.0.md.txt": SPEC_A, "Jeu_A_v1.1.md.txt": SPEC_A_V11})
        m = self.d.docs / "specs" / "jeu-a-sources" / "empreintes-drive.sha256"
        m.write_text(m.read_text() + f"{'0' * 64}  absent.md.txt\n")
        self.d.commit("doublon, nouvelle version, fichier manquant")
        avant = self.d.empreinte_usine()
        r = self.ok("import", "--from", str(self.d.docs), "--dry-run", "--report")
        self.assertEqual(self.d.empreinte_usine(), avant)                     # dry-run : rien d'écrit
        rap = r["report"]
        chemins = {m["path"]: m["specId"] for m in rap["mapping"]}
        self.assertEqual(chemins["specs/jeu-a-sources/zip-extrait/Jeu_A_v1.0.md.txt"], "SPEC-JEU-A")
        self.assertEqual(len(rap["duplicates"]), 1)                           # T01 : une identité, deux provenances
        self.assertEqual(rap["decisionsRequired"], ["SPEC-JEU-A"])            # 1.0.0 et 1.1.0 : jamais « le plus récent »
        self.assertIn({"path": "specs/jeu-a-sources/absent.md.txt", "issue": "archive-not-in-commit"}, rap["unknown"])
        self.assertEqual({c["specId"]: c["applicable"] for c in rap["coverage"]}["SPEC-JEU-A"], 2)


class LiensBB001(Base):
    def brique(self, ident: str, licence: str, decidee: bool) -> None:
        d = self.d.usine / "blocks" / "catalog"
        d.mkdir(parents=True, exist_ok=True)
        decision = {"status": "decided", "choice": "reuse", "rationale": "mesuré"} if decidee else \
            {"status": "pending", "rationale": None}
        (d / f"{ident}.json").write_text(json.dumps({
            "schemaVersion": "1.0", "id": ident, "name": ident, "kind": "external-library",
            "origin": {"repositoryUrl": "https://example.org/x", "licenseSpdx": licence, "commitSha": "a" * 40},
            "capabilities": ["x"], "interfaces": [{"language": "ts", "runtime": "browser"}], "specIds": ["SPEC-JEU-A"],
            "usedBy": [], "quality": {"status": "adopted", "sbomRef": None, "securityReportRef": None},
            "decision": decision, "provenance": {}}))

    def test_T11_decision_et_licence_tracables(self) -> None:
        self.importer()
        self.brique("BB-RNG-001", "MIT", True)
        r = self.ok("blocks", "--spec", "SPEC-JEU-A")
        self.assertEqual([(x["blockId"], x["choice"], x["licenseSpdx"]) for x in r["decisions"]],
                         [("BB-RNG-001", "reuse", "MIT")])
        self.assertNotIn("capabilities", json.dumps(r))                       # lien par ID, catalogue jamais recopié

    def test_licence_inconnue_ou_decision_absente_non_conforme(self) -> None:
        self.importer()
        self.brique("BB-RNG-001", "UNKNOWN", True)
        self.brique("BB-UI-001", "MIT", False)
        r = self.d.specctl("blocks", "--spec", "SPEC-JEU-A", "--json")
        self.assertEqual(r.rc, 2, r)
        self.assertEqual(r.json["untraceable"], ["BB-RNG-001", "BB-UI-001"])


# ------------------------------------------------------------------------------------------------ § 8 OPS-001 (T12)
CHAMPS_FACTORY_EVENT = {"agentId", "buildingBlockRefs", "commitSha", "eventId", "eventType", "evidence", "executionId",
                        "metadata", "occurredAt", "parentExecutionId", "portfolioId", "projectId", "pullRequestId",
                        "receivedAt", "runId", "schemaVersion", "source", "specRefs", "status", "taskId", "traceId",
                        "workflowId", "workflowVersion"}


class EvenementsOps001(Base):
    def setUp(self) -> None:
        super().setUp()
        self.tour = self.d.tmp / "tour"
        self.tour.mkdir()
        self.env = {"TOWER_DIR": str(self.tour), "TOWER_TRACE_ID": "reg003-T12"}

    def evenements(self) -> list[dict]:
        f = self.tour / "inbox.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.is_file() else []

    def test_T12_six_types_correles_par_trace(self) -> None:
        m = self.d.docs / "specs" / "jeu-a-conformite.json"
        mat = json.loads(m.read_text())
        mat["exigences"][0]["preuve"] = {"type": "test", "ref": "tests/x.py::test_a"}
        m.write_text(json.dumps(mat, ensure_ascii=False))
        self.d.archive("socle", {"Socle_v1.0.md.txt": "# Socle\n"})
        self.d.commit("preuve et socle")
        self.importer()
        self.ok("relier", "--spec", "SPEC-JEU-A", "--type", "consumes", "--target", "SPEC-SOCLE")
        run = lambda *a: self.d.specctl(*a, "--json", env_tour=self.env)
        run("resolve", "--project", "jeu-a")
        run("arbitrer", "--spec", "SPEC-JEU-A", "--version", "1.0.0", "--ref", REF)
        run("coverage", "--project", "jeu-a")
        run("impact", "--spec", "SPEC-SOCLE")
        evs = self.evenements()
        types = sorted({e["eventType"] for e in evs})
        self.assertEqual(types, ["requirement.verified", "spec.approved", "spec.impact-detected", "spec.resolved"])
        for e in evs:
            self.assertLessEqual(set(e), CHAMPS_FACTORY_EVENT, e)           # rien hors du schéma FactoryEvent v1.1
            self.assertEqual((e["traceId"], e["portfolioId"], e["agentId"]), ("reg003-T12", "homelab", "specctl"))
            self.assertTrue(e.get("specRefs"), e)                             # specId@specVersion
        verif = [e for e in evs if e["eventType"] == "requirement.verified"]
        self.assertEqual([e["metadata"]["requirementId"] for e in verif], ["REQ-JEU-A-E001"])
        self.assertEqual(verif[0]["evidence"], [{"type": "test", "uri": "tests/x.py::test_a"}])
        impact = next(e for e in evs if e["eventType"] == "spec.impact-detected")
        self.assertEqual(impact["metadata"]["projects"], ["jeu-a"])
        self.assertNotIn("@", json.dumps([e["metadata"] for e in evs]).replace("SPEC-", ""))  # aucune adresse


if __name__ == "__main__":
    unittest.main()
