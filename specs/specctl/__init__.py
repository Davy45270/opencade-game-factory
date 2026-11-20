"""CLI headless du registre de spécifications."""

import argparse
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

from .registry import RegistryStore, check_record
from . import tour
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
        epilog="""Codes de retour
  0  Succès
  1  Contrôle en échec ou fiche introuvable
  2  Usage invalide
  3  Refus de sécurité
  4  Source indisponible
  5  Conflit de versions""",
    )
    commands = cli.add_subparsers(dest="command", required=True)
    for name, description in {
        "import": "inventorier les archives de documentation",
        "validate": "valider les fiches et leurs identifiants",
        "resolve": "résoudre la version applicable d’un projet",
        "coverage": "calculer la couverture des exigences d’un projet",
        "verify": "contrôler les relations, les preuves et les archives",
        "arbitrer": "consigner une version choisie par David",
    }.items():
        command = commands.add_parser(name, help=description, allow_abbrev=False)
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        if name in {"import", "verify"}:
            command.add_argument("--from", dest="source", type=Path, required=name == "import",
                                 metavar="HOMELAB-DOCS")
        if name == "import":
            command.add_argument("--dry-run", action="store_true")
        if name in {"resolve", "coverage"}:
            command.add_argument("--project", required=True)
        if name == "arbitrer":
            command.add_argument("--spec", required=True)
            command.add_argument("--version", required=True)
            command.add_argument("--ref", help="commentaire de David au format HL-n 7-n")
    cli.add_argument("--json", action="store_true", help="écrire le résultat en JSON sur stdout")
    return cli


def import_records(store, source, dry_run):
    incoming, warnings = source.inventory()
    for spec_id, record in incoming.items():
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
                record = previous.copy()
                set_documents(record, chain(document_entries(previous), document_entries(incoming[spec_id])))
                updated += record != previous
            if record != previous:
                changes[spec_id] = record
            records[spec_id] = record
        if not dry_run and changes:
            store.publish(changes)
    return ExitCode.OK, {"status": "ok", "specs": [records[key] for key in incoming],
                         "created": created, "updated": updated, "warnings": warnings,
                         "sourceCommit": source.head, "dryRun": dry_run}


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
    broken, cycles, outdated, missing, declared, specs = [], [], [], [], [], []
    graph = TopologicalSorter()
    for spec_id, record in records.items():
        archives = list(document_entries(record))
        frozen = bool(archives)
        for relation in record.get("relations", []):
            target = relation["target"]
            if target not in nodes:
                broken.append({"specId": spec_id, **relation})
            elif relation["type"] in {"requires", "supersedes"}:
                graph.add(spec_id, target)
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
    failed = bool(broken or cycles or outdated)
    return (ExitCode.CHECK_FAILED if failed else ExitCode.OK), {
        "status": "non-compliant" if failed else "ok",
        "specs": specs, "brokenLinks": broken, "cycles": cycles, "outdated": outdated,
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
        store.publish({args.spec: record})
    return ExitCode.OK, {"status": "ok", "specId": args.spec, "arbitration": arbitration}


def run(args, root):
    store = RegistryStore(root)
    command = args.command
    if command == "import":
        return import_records(store, Source(args.source), args.dry_run)
    if command == "arbitrer" and not COMMENT.fullmatch(args.ref or ""):
        return ExitCode.SAFETY, {"status": "refused", "message": "Référence attendue au format HL-n 7-n."}
    source = Source(args.source) if command == "verify" and args.source is not None else None
    with store.lock(write=command == "arbitrer"):
        records = store.read()
        if command == "validate":
            return ExitCode.OK, {"status": "ok", "count": len(records)}
        if command == "resolve":
            code, payload = resolve(records, args.project)
            tour.emettre_resolution(args.project, code, payload)     # opt-in, n'échoue jamais
            return code, payload
        if command == "coverage":
            return coverage(records, args.project)
        if command == "verify":
            return verify(records, source)
        return arbitrate(store, records, args)


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
    except (InvalidJSON, UnicodeError) as exc:
        code, payload = ExitCode.CHECK_FAILED, {"status": "non-compliant", "message": str(exc)}
    except VersionConflict as exc:
        code, payload = ExitCode.VERSION_CONFLICT, {"status": "version-conflict", "message": str(exc)}
    except (OSError, ImportError) as exc:
        code, payload = ExitCode.IO, {"status": "source-unavailable", "message": str(exc)}
    journal.event("command-finished", command=command, status=payload["status"], code=int(code))
    if "--json" in argv:
        print(json_text(payload), end="")
    elif "message" in payload:
        print(payload["message"], file=sys.stderr)
    else:
        print(json_text(payload), end="")
    return int(code)
