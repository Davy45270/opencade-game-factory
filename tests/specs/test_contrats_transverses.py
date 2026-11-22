"""Oracles ARCH-001 E017 (contrats transverses versionnés) et E054 (contrat de livraison), écrits AVANT le code.

`contracts/index.json` nomme les 12 contrats de la spec, mot pour mot. Chacun a une version, un schéma JSON
(draft 2020-12) et des exemples : chaque exemple de CHAQUE version publiée doit rester valide contre le schéma
courant (compatibilité ascendante), et chaque contre-exemple doit être refusé (le schéma n'accepte pas tout).
Les contrats qui existent déjà sont réutilisés : Specification (REG-003), Component (BB-001), Artifact
(fiche d'asset) et FactoryEvent (Control Tower, copie dont l'empreinte est vérifiée)."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

RACINE = pathlib.Path(__file__).resolve().parents[2]
INDEX = RACINE / "contracts" / "index.json"
DOUZE = ["Project", "Task", "AgentExecution", "WorkflowDefinition", "WorkflowRun", "Evidence", "Artifact",
         "Component", "Specification", "PolicyDecision", "Release", "FactoryEvent"]
EXECUTION = ["portfolioId", "projectId", "taskId", "runId", "traceId", "agentId", "specRefs", "buildingBlockRefs",
             "commitSha", "evidenceRefs", "workflowVersion"]
LIVRAISON = ["releaseId", "commitSha", "specVersions", "componentVersions", "assetLock", "levelLock", "sbomRef",
             "testEvidence", "policyDecisions", "deploymentRef"]
REUTILISES = {"Specification": "specs/schemas/specification.schema.json",
              "Component": "blocks/schemas/block.schema.json",
              "Artifact": "schemas/asset.schema.json"}


def lire(chemin) -> dict:
    return json.loads((RACINE / chemin).read_text(encoding="utf-8"))


def index() -> dict:
    return lire("contracts/index.json")


def registre() -> Registry:
    """Tous les schémas du dépôt, par leur $id : les $ref entre schémas se résolvent hors ligne."""
    r = Registry()
    for f in RACINE.glob("**/*.schema.json"):
        if any(p in f.parts for p in (".venv", "node_modules", ".git")):
            continue
        s = json.loads(f.read_text(encoding="utf-8"))
        if s.get("$id"):
            r = r.with_resource(s["$id"], Resource.from_contents(s))
    return r


def validateur(chemin) -> Draft202012Validator:
    return Draft202012Validator(lire(chemin), registry=registre())


class ContratsTransverses(unittest.TestCase):
    def test_les_douze_contrats_sont_nommes_mot_pour_mot(self):
        self.assertEqual(sorted(index()["contrats"]), sorted(DOUZE))

    def test_chaque_contrat_est_versionne(self):
        for nom, c in index()["contrats"].items():
            self.assertRegex(c.get("version", ""), r"^\d+\.\d+\.\d+$", nom)
            self.assertTrue(c.get("historique"), nom)
            self.assertEqual(c["historique"][-1]["version"], c["version"], nom)

    def test_les_contrats_existants_sont_reutilises_pas_recrees(self):
        cs = index()["contrats"]
        for nom, chemin in REUTILISES.items():
            self.assertEqual(cs[nom]["schema"], chemin, nom)

    def test_chaque_schema_est_valide_et_chaque_exemple_de_chaque_version_passe(self):
        for nom, c in index()["contrats"].items():
            Draft202012Validator.check_schema(lire(c["schema"]))
            v = validateur(c["schema"])
            exemples = [e for h in c["historique"] for e in h["exemples"]]
            self.assertTrue(exemples, nom)
            for e in exemples:
                erreurs = [x.message for x in v.iter_errors(lire(e))]
                self.assertEqual(erreurs, [], f"{nom} : {e}")

    def test_chaque_contre_exemple_est_refuse(self):
        for nom, c in index()["contrats"].items():
            self.assertTrue(c.get("contreExemples"), nom)
            v = validateur(c["schema"])
            for e in c["contreExemples"]:
                self.assertFalse(v.is_valid(lire(e)), f"{nom} accepte {e}")

    def test_factory_event_est_la_copie_exacte_du_contrat_de_la_tower(self):
        c = index()["contrats"]["FactoryEvent"]
        self.assertEqual(c["origine"]["depot"], "homelab-diag")
        self.assertRegex(c["origine"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(hashlib.sha256((RACINE / c["schema"]).read_bytes()).hexdigest(), c["origine"]["sha256"])

    def test_agent_execution_exige_les_onze_champs_d_execution(self):
        s = lire(index()["contrats"]["AgentExecution"]["schema"])
        self.assertEqual(sorted(set(EXECUTION) - set(s["required"])), [])

    def test_release_exige_les_dix_champs_de_livraison(self):
        s = lire(index()["contrats"]["Release"]["schema"])
        self.assertEqual(sorted(set(LIVRAISON) - set(s["required"])), [])

    def test_une_release_sans_un_champ_de_livraison_est_refusee(self):
        c = index()["contrats"]["Release"]
        v = validateur(c["schema"])
        ok = lire(c["historique"][-1]["exemples"][0])
        for champ in LIVRAISON:
            r = {k: x for k, x in ok.items() if k != champ}
            self.assertFalse(v.is_valid(r), champ)

    def test_les_identifiants_de_schema_portent_la_version_majeure(self):
        for nom, c in index()["contrats"].items():
            if nom in REUTILISES:
                continue
            majeure = c["version"].split(".")[0]
            self.assertTrue(re.search(rf"-v{majeure}(\.\d+)?(\.schema)?\.json$", lire(c["schema"]).get("$id", "")),
                            nom)


if __name__ == "__main__":
    unittest.main()
