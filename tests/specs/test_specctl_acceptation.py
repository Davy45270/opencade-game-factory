"""Oracles d'acceptation du module specs/ (REG-003 : REG-01 à REG-05, REG-T01/T02/T04/T05/T07/T08 ; ARCH-001 AT-11).

Écrits AVANT le code (Claude, oracle) : ils échouent tant que `specctl` n'existe pas. L'implémentation (Codex) les fait
passer SANS les modifier ; un oracle qu'elle juge faux se signale dans son rapport, il ne se réécrit pas.
Décisions de David appliquées : import initial depuis homelab-docs, puis l'usine fait foi (HL-525 7-2955) ; analyse des
écarts § 3 : la fiche RÉFÉRENCE l'archive par commit et empreinte, elle ne recopie pas le texte.
Contrat d'appel et codes de retour : tests/specs/_outil.py.
"""
from __future__ import annotations

import json
import re
import subprocess
import unittest

from ._outil import SPEC_A, SPEC_A_V11, SPECCTL, Docs, git, sha

ID_SPEC = re.compile(r"SPEC-[A-Z0-9]+(?:-[A-Z0-9]+)*")
ID_REQ = re.compile(r"REQ-[A-Z0-9]+(?:-[A-Z0-9]+)*-E\d{3,}")


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()

    def tearDown(self) -> None:
        self.d.nettoyer()

    def importer(self, *extra: str):
        r = self.d.specctl("import", "--from", str(self.d.docs), "--json", *extra)
        self.assertEqual(r.rc, 0, r)
        return r


# ---------------------------------------------------------------------------------------------------------------- REG-01
class REG01SchemasEtIds(Base):
    def test_schemas_json_valides(self) -> None:
        import jsonschema
        for nom in ("specification", "requirement"):
            p = SPECCTL.parent / "specs" / "schemas" / f"{nom}.schema.json"
            self.assertTrue(p.is_file(), p)
            jsonschema.Draft202012Validator.check_schema(json.loads(p.read_text()))

    def test_fiches_importees_valides_et_ids_stables(self) -> None:
        self.importer()
        reg = self.d.registre()
        self.assertEqual(sorted(reg), ["SPEC-JEU-A", "SPEC-JEU-B"])
        for nom, fiche in reg.items():
            self.assertEqual(fiche["id"], nom)
            self.assertRegex(fiche["id"], ID_SPEC)
        reqs = reg["SPEC-JEU-A"]["requirements"]
        self.assertEqual([r["matrixId"] for r in reqs], ["E001", "E002"])          # REQ-ID ↔ E nnn de la matrice
        for r in reqs:
            self.assertRegex(r["id"], ID_REQ)
        r = self.d.specctl("validate", "--json")
        self.assertEqual(r.rc, 0, r)

    def test_id_en_double_refuse(self) -> None:
        self.importer()
        reg = self.d.usine / "specs" / "registry"
        (reg / "SPEC-JEU-A-COPIE.json").write_text((reg / "SPEC-JEU-A.json").read_text())   # même `id` dans deux fiches
        r = self.d.specctl("validate", "--json")
        self.assertEqual(r.rc, 2, r)
        self.assertIn("SPEC-JEU-A", r.stdout)

    def test_id_invalide_refuse(self) -> None:
        self.importer()
        f = self.d.usine / "specs" / "registry" / "SPEC-JEU-B.json"
        v = json.loads(f.read_text()); v["id"] = "spec-jeu-b"
        f.write_text(json.dumps(v))
        self.assertEqual(self.d.specctl("validate", "--json").rc, 2)


# ---------------------------------------------------------------------------------------------------------------- REG-02
class REG02Import(Base):
    def test_import_reference_par_commit_et_empreinte_sans_recopier_le_texte(self) -> None:
        self.importer()
        tete = git(self.d.docs, "rev-parse", "HEAD")
        fiche = self.d.registre()["SPEC-JEU-A"]
        docs = [doc for v in fiche["versions"] for doc in v["documents"]]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["sha256"], sha(SPEC_A.encode()))
        prov = docs[0]["provenances"]
        self.assertEqual(prov, [{"repo": "homelab-docs", "path": "specs/jeu-a-sources/Jeu_A_v1.0.md.txt", "commitSha": tete}])
        brut = json.dumps(fiche, ensure_ascii=False)
        self.assertNotIn(SPEC_A, brut)                                   # pas de duplication éditable du texte
        self.assertNotIn("## Règles", brut)
        self.assertFalse({"content", "text", "body"} & set(fiche), "la fiche ne porte pas le texte de la spec")

    def test_version_semver_lue_au_nom(self) -> None:
        self.importer()
        self.assertEqual([v["version"] for v in self.d.registre()["SPEC-JEU-A"]["versions"]], ["1.0.0"])

    def test_import_lecture_seule(self) -> None:
        avant = self.d.empreinte_docs()
        self.importer()
        self.assertEqual(self.d.empreinte_docs(), avant)
        self.assertEqual(git(self.d.docs, "status", "--porcelain"), "")

    def test_dry_run_n_ecrit_rien(self) -> None:
        avant = self.d.empreinte_usine()
        r = self.d.specctl("import", "--from", str(self.d.docs), "--dry-run", "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(sorted(s["id"] for s in r.json["specs"]), ["SPEC-JEU-A", "SPEC-JEU-B"])
        self.assertEqual(self.d.empreinte_usine(), avant)

    def test_T01_meme_spec_dans_deux_archives_une_identite_deux_provenances(self) -> None:
        self.d.archive("jeu-a", {"zip-extrait/Jeu_A_v1.0.md.txt": SPEC_A})
        self.d.commit("même spec dans un zip extrait")
        self.importer()
        fiche = self.d.registre()["SPEC-JEU-A"]
        docs = [doc for v in fiche["versions"] for doc in v["documents"]]
        self.assertEqual(len(docs), 1)
        self.assertEqual(sorted(p["path"] for p in docs[0]["provenances"]),
                         ["specs/jeu-a-sources/Jeu_A_v1.0.md.txt", "specs/jeu-a-sources/zip-extrait/Jeu_A_v1.0.md.txt"])

    def test_T08_relance_zero_doublon_octets_identiques(self) -> None:
        self.importer()
        avant = self.d.empreinte_usine()
        r = self.importer()
        self.assertEqual(self.d.empreinte_usine(), avant)               # idempotent : pas d'horodatage volatil dans les fiches
        self.assertEqual(r.json.get("created", 0), 0)

    def test_T04_source_indisponible_n_est_pas_une_non_conformite(self) -> None:
        r = self.d.specctl("import", "--from", str(self.d.tmp / "absent"), "--json")
        self.assertEqual(r.rc, 4, r)
        self.assertEqual(r.json["status"], "source-unavailable")
        self.assertEqual(self.d.registre(), {})

    def test_T07_deux_imports_simultanes_resultat_coherent(self) -> None:
        import os
        env = {**os.environ, "USINE_RACINE": str(self.d.usine)}
        ps = [subprocess.Popen([str(SPECCTL), "import", "--from", str(self.d.docs), "--json"], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        rcs = [p.wait(timeout=120) for p in ps]
        self.assertTrue(all(rc in (0, 5) for rc in rcs), rcs)            # 5 = conflit signalé, jamais d'écrasement muet
        self.assertIn(0, rcs)
        self.assertEqual(sorted(self.d.registre()), ["SPEC-JEU-A", "SPEC-JEU-B"])
        self.assertEqual(self.d.specctl("validate", "--json").rc, 0)


# ---------------------------------------------------------------------------------------------------------------- REG-03
class REG03Resolution(Base):
    def test_resolution_deterministe(self) -> None:
        self.importer()
        r1 = self.d.specctl("resolve", "--project", "jeu-a", "--json")
        r2 = self.d.specctl("resolve", "--project", "jeu-a", "--json")
        self.assertEqual((r1.rc, r2.rc), (0, 0), (r1, r2))
        a, b = r1.json, r2.json
        a.pop("resolvedAt", None); b.pop("resolvedAt", None)
        self.assertEqual(a, b)
        self.assertEqual([(s["specId"], s["version"]) for s in a["specs"]], [("SPEC-JEU-A", "1.0.0")])
        self.assertRegex(a["registryDigest"], r"^[0-9a-f]{64}$")       # le résultat dit CONTRE QUEL état du registre

    def test_T02_version_ambigue_arbitrage_requis(self) -> None:
        self.d.archive("jeu-a", {"Jeu_A_v1.1.md.txt": SPEC_A_V11})
        self.d.commit("v1.1 déposée")
        self.importer()
        r = self.d.specctl("resolve", "--project", "jeu-a", "--json")
        self.assertEqual(r.rc, 5, r)                                     # jamais « la plus récente l'emporte » en silence
        self.assertEqual(r.json["status"], "arbitration-required")

    def test_arbitrage_exige_le_commentaire_de_david(self) -> None:
        self.d.archive("jeu-a", {"Jeu_A_v1.1.md.txt": SPEC_A_V11})
        self.d.commit("v1.1 déposée")
        self.importer()
        sans = self.d.specctl("arbitrer", "--spec", "SPEC-JEU-A", "--version", "1.1.0", "--ref", "décidé par l'agent", "--json")
        self.assertEqual(sans.rc, 3, sans)                               # un agent n'approuve pas lui-même
        avec = self.d.specctl("arbitrer", "--spec", "SPEC-JEU-A", "--version", "1.1.0", "--ref", "HL-0 7-0", "--json")
        self.assertEqual(avec.rc, 0, avec)
        r = self.d.specctl("resolve", "--project", "jeu-a", "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(r.json["specs"][0]["version"], "1.1.0")
        self.assertEqual(r.json["specs"][0]["arbitration"]["ref"], "HL-0 7-0")

    def test_projet_inconnu(self) -> None:
        self.importer()
        r = self.d.specctl("resolve", "--project", "inexistant", "--json")
        self.assertEqual(r.rc, 2, r)


# ---------------------------------------------------------------------------------------------------------------- REG-04
class REG04Graphe(Base):
    def relation(self, de: str, vers: str, type_: str = "requires") -> None:
        f = self.d.usine / "specs" / "registry" / f"{de}.json"
        v = json.loads(f.read_text())
        v.setdefault("relations", []).append({"type": type_, "target": vers})
        f.write_text(json.dumps(v, ensure_ascii=False, indent=1))

    def test_lien_casse_detecte(self) -> None:
        self.importer()
        self.relation("SPEC-JEU-A", "SPEC-ABSENTE")
        r = self.d.specctl("verify", "--json")
        self.assertEqual(r.rc, 2, r)
        self.assertIn("SPEC-ABSENTE", json.dumps(r.json["brokenLinks"]))

    def test_cycle_detecte(self) -> None:
        self.importer()
        self.relation("SPEC-JEU-A", "SPEC-JEU-B")
        self.relation("SPEC-JEU-B", "SPEC-JEU-A")
        r = self.d.specctl("verify", "--json")
        self.assertEqual(r.rc, 2, r)
        self.assertTrue(r.json["cycles"])

    def test_relation_non_typee_refusee(self) -> None:
        self.importer()
        self.relation("SPEC-JEU-A", "SPEC-JEU-B", "ressemble-a")
        self.assertEqual(self.d.specctl("validate", "--json").rc, 2)

    def test_relation_typee_valide(self) -> None:
        self.importer()
        self.relation("SPEC-JEU-A", "SPEC-JEU-B", "reuses")
        self.assertEqual(self.d.specctl("verify", "--json").rc, 0)

    def test_T05_exigence_sans_preuve_ecart_explicite(self) -> None:
        self.importer()
        r = self.d.specctl("verify", "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertIn("REQ-JEU-A-E002", json.dumps(r.json["requirementsWithoutEvidence"]))
        self.assertNotIn("REQ-JEU-A-E001", json.dumps(r.json["requirementsWithoutEvidence"]))


# ---------------------------------------------------------------------------------------------------------------- AT-11
class AT11UneSeuleSourceEditable(Base):
    def test_une_seule_origine_editable_par_spec(self) -> None:
        self.importer()
        r = self.d.specctl("verify", "--json")
        self.assertEqual(r.rc, 0, r)
        for s in r.json["specs"]:
            self.assertEqual(s["editableOrigin"], "usine", s)
            self.assertTrue(s["archive"]["frozen"], s)
            self.assertEqual(s["archive"]["repo"], "homelab-docs")

    def test_copie_editable_du_texte_dans_l_usine_refusee(self) -> None:
        self.importer()
        f = self.d.usine / "specs" / "registry" / "SPEC-JEU-A.json"
        v = json.loads(f.read_text()); v["content"] = SPEC_A
        f.write_text(json.dumps(v, ensure_ascii=False))
        r = self.d.specctl("verify", "--json")
        self.assertEqual(r.rc, 2, r)

    def test_archive_modifiee_apres_import_spec_perimee(self) -> None:
        self.importer()
        (self.d.docs / "specs/jeu-a-sources/Jeu_A_v1.0.md.txt").write_text(SPEC_A + "édition sauvage\n")
        self.d.commit("archive éditée (ce que la garde de pre-commit refuse)")
        r = self.d.specctl("verify", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 2, r)
        self.assertIn("SPEC-JEU-A", json.dumps(r.json["outdated"]))

    def test_verify_source_indisponible(self) -> None:
        self.importer()
        r = self.d.specctl("verify", "--from", str(self.d.tmp / "absent"), "--json")
        self.assertEqual(r.rc, 4, r)


# ---------------------------------------------------------------------------------------------------------------- REG-05
class REG05Cli(Base):
    def test_aide_documente_les_codes(self) -> None:
        r = self.d.specctl("--help")
        self.assertEqual(r.rc, 0, r)
        for code in ("0", "2", "3", "4", "5"):
            self.assertRegex(r.stdout, rf"(?m)^\s*{code}\b", f"code {code} non documenté")
        for cmd in ("import", "resolve", "verify", "validate", "arbitrer"):
            self.assertIn(cmd, r.stdout)

    def test_usage(self) -> None:
        self.assertEqual(self.d.specctl("inventer").rc, 3)
        self.assertEqual(self.d.specctl("import", "--json").rc, 3)          # --from obligatoire

    def test_toutes_les_commandes_rendent_du_json(self) -> None:
        self.importer()
        for args in (("validate",), ("resolve", "--project", "jeu-a"), ("verify",),
                     ("import", "--from", str(self.d.docs), "--dry-run")):
            r = self.d.specctl(*args, "--json")
            self.assertIsInstance(r.json, dict, args)


if __name__ == "__main__":
    unittest.main()
