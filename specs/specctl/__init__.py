"""CLI headless du registre de spécifications."""

import argparse
import copy
import os
import re
import sys
from datetime import datetime, timezone
from graphlib import CycleError, TopologicalSorter
from itertools import chain
from pathlib import Path

from tools.core import journal
from tools.core.catalog import CatalogueScopeError, InvalidJSON, ROOT, json_text
from tools.core.exit_codes import ExitCode

from .registry import BaseInconnue, RegistryStore, check_against_base, check_ids, check_record
from . import commandes, fiche, generes, tour
from .source import Source, VersionConflict, document_entries, set_documents, sha256

COMMENT = re.compile(r"HL-[0-9]+ 7-[0-9]+")


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def parser():
    cli = Parser(
        prog="specctl", allow_abbrev=False, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Codes de retour (REG-003 § 6)
  0  Succès
  2  Non-conformité : contrôle en échec, fiche ou projet introuvable, spec périmée
  3  Entrée invalide : usage, ou refus de sécurité (approbation de David absente)
  4  Source indisponible : doc, dépôt, Drive ou registre illisible (jamais une non-conformité)
  5  Conflit de versions : arbitrage de David requis""",
    )
    commands = cli.add_subparsers(dest="command", required=True)
    for name, description in {
        "discover": "inventorier en lecture seule les specs d’une source (docs, github, drive)",
        "import": "inventorier les archives de documentation",
        "validate": "valider les fiches et leurs identifiants",
        "search": "chercher une spec ou une exigence par mots",
        "resolve": "résoudre la version applicable d’un projet",
        "lock": "verrou du jeu de specs appliqué (SemVer, empreinte, horodatage)",
        "coverage": "calculer la couverture des exigences d’un projet",
        "verify": "contrôler relations, preuves, archives ; ou le verrou d’une PR (--project --commit)",
        "impact": "projets consommateurs d’une spec",
        "compare": "comparer deux états du registre (références git de l’usine)",
        "export": "exporter le registre (markdown, json ou html navigable ; --public : specs publiques seulement)",
        "blocks": "décisions BB-001 liées à une spec, par identifiant",
        "arbitrer": "consigner une version choisie par David",
        "statuer": "changer lifecycle ou visibilité (approbation de David pour approuver, déprécier, publier)",
        "relier": "ajouter une relation typée entre specs",
        "sync": "recopier statut, preuve et critère des matrices de homelab-docs (énoncés inchangés)",
        "inscrire-drive": "inscrire un document Drive « à importer » (pas encore archivé)",
        "index": "reconstruire les index générés (--check : comparer sans écrire)",
        "sbom": "SBOM CycloneDX de specctl, licences des dépendances contrôlées",
    }.items():
        command = commands.add_parser(name, help=description, allow_abbrev=False)
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        if name in {"import", "verify", "sync"}:
            command.add_argument("--from", dest="source", type=Path, required=name in {"import", "sync"},
                                 metavar="HOMELAB-DOCS")
        if name in {"import", "sync"}:
            command.add_argument("--dry-run", action="store_true")
        if name == "inscrire-drive":
            command.add_argument("--drive", required=True)
            command.add_argument("--name", required=True)
            command.add_argument("--project", required=True)
        if name == "import":
            command.add_argument("--report", action="store_true", help="rapport de migration (§ 5)")
        if name in {"resolve", "coverage", "lock"}:
            command.add_argument("--project", required=True)
        if name == "validate":
            command.add_argument("--base", metavar="REF", help="refuser une clé d'identifiant retirée ou réattribuée")
        if name == "verify":
            command.add_argument("--project")
            command.add_argument("--commit")
            command.add_argument("--repo", type=Path)
        if name in {"arbitrer", "statuer", "relier", "impact", "blocks"}:
            command.add_argument("--spec", required=True)
        if name == "arbitrer":
            command.add_argument("--version", required=True)
        if name in {"arbitrer", "statuer"}:
            command.add_argument("--ref", help="commentaire de David au format HL-n 7-n")
        if name == "statuer":
            command.add_argument("--lifecycle", choices=fiche.LIFECYCLES)
            command.add_argument("--visibility", choices=fiche.VISIBILITIES)
        if name == "relier":
            command.add_argument("--type", dest="kind", required=True, choices=sorted(commandes.RELATIONS))
            command.add_argument("--target", required=True)
            command.add_argument("--range", dest="rule")
        if name == "discover":
            command.add_argument("--source", dest="kind", required=True, choices=("docs", "github", "drive"))
            command.add_argument("--from", dest="source", type=Path, metavar="HOMELAB-DOCS")
            command.add_argument("--sources", type=Path, default=ROOT / "catalog" / "sources.json")
            command.add_argument("--clones", type=Path, default=Path.home() / "Projets" / "jeux")
            command.add_argument("--listing", type=Path, help="liste Drive exportée par le connecteur claude.ai")
        if name == "search":
            command.add_argument("query")
            command.add_argument("--project")
            command.add_argument("--limit", type=int, default=20)
        if name == "compare":
            command.add_argument("--from", dest="before", required=True)
            command.add_argument("--to", dest="after", required=True)
            command.add_argument("--spec")
        if name == "index":
            command.add_argument("--out", type=Path, default=None, help="défaut : generated/specs de l’usine")
            command.add_argument("--check", action="store_true")
        if name == "sbom":
            command.add_argument("--out", type=Path, required=True)
            command.add_argument("--allow", nargs="+", metavar="SPDX", help="politique de licences (défaut intégré)")
        if name == "export":
            command.add_argument("--format", dest="fmt", choices=("markdown", "json", "html"), default="json")
            command.add_argument("--public", action="store_true")
    cli.add_argument("--json", action="store_true", help="écrire le résultat en JSON sur stdout")
    return cli


def import_records(store, source, dry_run, report=False):
    incoming, warnings = source.inventory()
    for spec_id, record in incoming.items():
        for row in record["requirements"]:
            row.pop("_previousMatrixId", None)          # suivi des renommages : sync seulement, jamais écrit
        check_record(spec_id, record)

    with store.lock(write=not dry_run):
        records = store.read()
        changes = {}
        created = updated = 0
        for spec_id, record in incoming.items():
            previous = records.get(spec_id)
            if previous is None:
                created += 1
            else:
                # Les exigences, liens et arbitrages sont édités dans l’usine après le premier import.
                record = copy.deepcopy(previous)
                set_documents(record, chain(document_entries(previous), document_entries(incoming[spec_id])))
                fiche.adopt(record, incoming[spec_id])
                updated += record != previous
            if record != previous:
                changes[spec_id] = record
            records[spec_id] = record
        if not dry_run and changes:
            store.publish(changes, "import")
    payload = {"status": "ok", "specs": [records[key] for key in incoming],
               "created": created, "updated": updated, "warnings": warnings,
               "sourceCommit": source.head, "dryRun": dry_run}
    if report:
        payload["report"] = commandes.report(records, source, warnings, incoming)
    return ExitCode.OK, payload


def resolve(records, project):
    specs = []
    for record in records.values():
        if record["project"] != project:
            continue
        spec_id = record["id"]
        versions = record["versions"]
        arbitration = record.get("arbitration")
        if len(versions) > 1 and arbitration is None:
            return ExitCode.VERSION_CONFLICT, {"status": "arbitration-required", "specId": spec_id,
                                               "versions": [entry["version"] for entry in versions]}
        if not versions:
            return ExitCode.CHECK_FAILED, {"status": "version-missing", "specId": spec_id}
        version = (next(entry for entry in versions if entry["version"] == arbitration["version"])
                   if arbitration else versions[0])
        result = {"specId": spec_id, **version}
        if arbitration:
            result["arbitration"] = arbitration
        specs.append(result)
    if not specs:
        return ExitCode.CHECK_FAILED, {"status": "project-not-found", "project": project}
    return ExitCode.OK, {"status": "ok", "project": project, "specs": specs,
                         "registryDigest": sha256(json_text(records).encode("utf-8")),
                         "resolvedAt": datetime.now(timezone.utc).isoformat()}


def verify(records, source):
    nodes = set(records)
    nodes.update(row["id"] for record in records.values() for row in record["requirements"])
    broken, cycles, outdated, missing, declared, specs, incompatible = [], [], [], [], [], [], []
    graph = TopologicalSorter()
    for spec_id, record in records.items():
        archives = list(document_entries(record))
        frozen = bool(archives)
        for relation in record.get("relations", []):
            target = relation["target"]
            if target not in nodes:
                broken.append({"specId": spec_id, **relation})
            else:
                if relation["type"] in {"requires", "supersedes"}:
                    graph.add(spec_id, target)
                if "range" in relation and not commandes.satisfies(commandes.spec_version(target, records),
                                                                   relation["range"]):
                    incompatible.append({"specId": spec_id, **relation,
                                         "resolved": commandes.spec_version(target, records)})
        for row in record["requirements"]:
            if "evidence" not in row:
                # Une ligne « faite » déclare une couverture, sans en fournir de preuve vérifiable.
                (declared if row["matrixStatus"] == "faite" else missing).append(row["id"])
        if source is not None:
            for _, digest, provenance in archives:
                path = provenance["path"]
                if not source.frozen(path, digest, provenance["commitSha"]):
                    outdated.append({"specId": spec_id, "path": path})
                    frozen = False
        specs.append({"specId": spec_id, "editableOrigin": "usine",
                      "archive": {"repo": "homelab-docs", "frozen": frozen,
                                  "checked": source is not None}})
    try:
        graph.prepare()
    except CycleError as exc:
        cycles.append(exc.args[1])
    failed = bool(broken or cycles or outdated or incompatible)
    return (ExitCode.CHECK_FAILED if failed else ExitCode.OK), {
        "status": "non-compliant" if failed else "ok",
        "specs": specs, "brokenLinks": broken, "cycles": cycles, "outdated": outdated,
        "incompatibleVersions": incompatible,
        "requirementsWithoutEvidence": missing, "requirementsDeclaredWithoutProof": declared,
    }


def coverage(records, project):
    record = next((record for record in records.values() if record["project"] == project), None)
    if record is None:
        return ExitCode.CHECK_FAILED, {"status": "project-not-found", "project": project}

    requirements, uncovered, inconsistent = [], [], []
    covered = waived = 0
    for row in record["requirements"]:
        requirement_id = row["id"]
        status = row["matrixStatus"]
        evidence = row.get("evidence")
        if evidence is not None and all(evidence[key].strip() for key in ("type", "ref")):
            evidence = {key: evidence[key] for key in ("type", "ref")}
        else:
            evidence = None
        requirements.append({"id": requirement_id, "matrixId": row["matrixId"],
                             "status": status, "evidence": evidence})
        if status == "ecartee":
            waived += 1
        elif status == "faite" and evidence is not None:
            covered += 1
        else:
            uncovered.append(requirement_id)
            if status == "faite":
                inconsistent.append(requirement_id)

    total = len(requirements)
    applicable = total - waived
    # revue Codex 12 (19/11) : aucune exigence applicable (matrice absente à l'import, ou tout écarté) n'est jamais
    # « 100 % couvert » : rien n'est mesuré, le contrôle échoue et le ratio est nul (None)
    vide = applicable == 0
    return (ExitCode.CHECK_FAILED if inconsistent or vide else ExitCode.OK), {
        "status": "non-compliant" if inconsistent else ("no-applicable-requirements" if vide else "ok"),
        "project": project, "total": total, "covered": covered, "waived": waived,
        "uncovered": uncovered, "ratio": None if vide else round(covered / applicable, 4),
        "requirements": requirements, "inconsistent": inconsistent,
    }


def arbitrate(store, records, args):
    record = records.get(args.spec)
    if record is None or args.version not in {entry["version"] for entry in record["versions"]}:
        return ExitCode.CHECK_FAILED, {"status": "version-not-found", "specId": args.spec}
    arbitration = {"version": args.version, "ref": args.ref}
    if record.get("arbitration") != arbitration:
        record["arbitration"] = arbitration
        store.publish({args.spec: record}, "arbitrer")
    return ExitCode.OK, {"status": "ok", "specId": args.spec, "arbitration": arbitration}


def run(args, root):
    store = RegistryStore(root)
    command = args.command
    if command == "import":
        return import_records(store, Source(args.source), args.dry_run, args.report)
    if command == "arbitrer" and not COMMENT.fullmatch(args.ref or ""):
        return ExitCode.SAFETY, {"status": "refused", "message": "Référence attendue au format HL-n 7-n."}
    if command == "compare":
        return commandes.compare(root, args.before, args.after, args.spec)
    if command == "sbom":
        return generes.sbom(args.out, args.allow)
    if command == "verify" and (args.project or args.commit or args.repo):
        if not (args.project and args.commit and args.repo):
            return ExitCode.USAGE, {"status": "usage", "message": "--project, --commit et --repo vont ensemble."}
    source = Source(args.source) if command == "verify" and args.source is not None else None
    if command == "discover" and args.kind == "docs":
        if args.source is None:
            return ExitCode.USAGE, {"status": "usage", "message": "--from <homelab-docs> attendu."}
        source = args.source
    if command == "sync":
        incoming, _ = Source(args.source).inventory()
    with store.lock(write=command in {"arbitrer", "statuer", "relier", "inscrire-drive"}
                    or (command == "sync" and not args.dry_run)):
        records = store.read()
        if command == "validate":
            ids = store.ids()
            errors = check_ids(records, ids)
            if args.base is not None:
                try:
                    errors += check_against_base(root, args.base, ids)
                except BaseInconnue as exc:
                    return ExitCode.USAGE, {"status": "usage", "message": str(exc)}
            if errors:
                return ExitCode.CHECK_FAILED, {"status": "ids-invalid", "errors": errors}
            return ExitCode.OK, {"status": "ok", "count": len(records), "ids": len(ids)}
        if command == "resolve":
            code, payload = resolve(records, args.project)
            tour.emettre_resolution(args.project, code, payload)     # opt-in, n'échoue jamais
            return code, payload
        if command == "coverage":
            code, payload = coverage(records, args.project)
            tour.emettre_verifications(records, args.project, payload)   # opt-in, n'échoue jamais
            return code, payload
        if command == "verify" and args.project:
            code, payload = commandes.verify_project(records, args.project, args.commit, args.repo)
            tour.emettre_verrou(records, code, payload)               # opt-in, n'échoue jamais
            return code, payload
        if command == "verify":
            code, payload = verify(records, source)
            tour.emettre_peremptions(records, payload)              # opt-in, n'échoue jamais
            return code, payload
        if command == "discover":
            if args.kind == "docs":
                return commandes.discover_docs(records, source)
            if args.kind == "github":
                return commandes.discover_github(records, args.sources, args.clones)
            return commandes.discover_drive(records, args.listing, commandes.pending_drive(root))
        if command == "search":
            return commandes.search(records, args.query, args.project, args.limit)
        if command == "lock":
            return commandes.lock(records, args.project)
        if command == "impact":
            code, payload = commandes.impact(records, args.spec)
            tour.emettre_impact(records, code, payload)               # opt-in, n'échoue jamais
            return code, payload
        if command == "export":
            return commandes.export(records, args.fmt, args.public)
        if command == "sync":
            return commandes.sync(store, records, incoming, args.dry_run)
        if command == "inscrire-drive":
            return commandes.inscrire_drive(store, args.drive, args.name, args.project)
        if command == "index":
            return generes.index(records, args.out or root / "generated" / "specs", args.check)
        if command == "blocks":
            return commandes.blocks(records, root, args.spec)
        if command == "statuer":
            code, payload = commandes.statuer(store, records, args.spec, args.lifecycle, args.visibility, args.ref)
            if payload.get("lifecycle") == "approved" and payload.get("changed"):
                tour.emettre_approbation(records, code, {"status": "ok", "specId": args.spec,
                                                         "arbitration": None, "lifecycleRef": args.ref})
            return code, payload
        if command == "relier":
            return commandes.relier(store, records, args.spec, args.kind, args.target, args.rule)
        code, payload = arbitrate(store, records, args)
        tour.emettre_approbation(records, code, payload)            # opt-in, n'échoue jamais
        return code, payload


# REG-003 § 6 : 0 succès, 2 non-conformité, 3 entrée invalide, 4 source indisponible, 5 conflit de versions.
# Le cœur parle la table commune de l'usine (tools.core.exit_codes) ; la sortie de specctl est traduite ici, comme
# `assetctl level` le fait pour EXT-002 (docs/ARCHITECTURE.md § Codes de retour).
CODES_REG003 = {ExitCode.OK: 0, ExitCode.CHECK_FAILED: 2, ExitCode.USAGE: 3, ExitCode.SAFETY: 3, ExitCode.IO: 4,
                ExitCode.VERSION_CONFLICT: 5}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    command = None
    try:
        args = parser().parse_args(argv)
        command = args.command
        code, payload = run(args, Path(os.environ.get("USINE_RACINE", ROOT)).resolve())
    except UsageError as exc:
        code, payload = ExitCode.USAGE, {"status": "usage", "message": str(exc)}
    except CatalogueScopeError as exc:
        code, payload = ExitCode.SAFETY, {"status": "refused", "message": str(exc)}
    except ValueError as exc:
        if not isinstance(exc, (InvalidJSON, UnicodeError, VersionConflict)):
            code, payload = ExitCode.USAGE, {"status": "usage", "message": str(exc)}
        elif isinstance(exc, VersionConflict):
            code, payload = ExitCode.VERSION_CONFLICT, {"status": "version-conflict", "message": str(exc)}
        else:
            code, payload = ExitCode.CHECK_FAILED, {"status": "non-compliant", "message": str(exc)}
    except (InvalidJSON, UnicodeError) as exc:
        code, payload = ExitCode.CHECK_FAILED, {"status": "non-compliant", "message": str(exc)}
    except VersionConflict as exc:
        code, payload = ExitCode.VERSION_CONFLICT, {"status": "version-conflict", "message": str(exc)}
    except (OSError, ImportError) as exc:
        code, payload = ExitCode.IO, {"status": "source-unavailable", "message": str(exc)}
    code = CODES_REG003[ExitCode(int(code))]
    journal.event("command-finished", command=command, status=payload["status"], code=int(code))
    if "--json" in argv:
        print(json_text(payload), end="")
    elif "message" in payload:
        print(payload["message"], file=sys.stderr)
    else:
        print(json_text(payload), end="")
    return int(code)
