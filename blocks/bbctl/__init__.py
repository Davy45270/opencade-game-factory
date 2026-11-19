"""CLI du registre BB-001."""

import argparse
import os
import re
import sys
from pathlib import Path

from tools.core import journal
from tools.core.catalog import CatalogueScopeError, InvalidJSON, ROOT, json_text, write_json
from tools.core.exit_codes import ExitCode

from .decisions import VersionConflict, import_decisions
from .evaluation import evaluate, nonblank
from .registry import lock, read_catalogue
from .search import GraphUnavailable, search

CHOICES = ("reuse", "adapt", "wrap", "fork", "build", "defer")
CODE_HELP = """Codes de retour
  0 succès
  1 contrôle en échec
  2 usage
  3 refus de sécurité
  4 source indisponible
  5 conflit de versions"""


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def parser():
    cli = Parser(
        prog="bbctl", description="Catalogue de briques BB-001 et recherche interne via graphify.",
        epilog=CODE_HELP, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = cli.add_subparsers(dest="command", required=True)
    descriptions = {
        "validate": "Vérifier le catalogue.",
        "import-decisions": "Importer des décisions Markdown en conservant leur provenance.",
        "search": "Chercher dans le graphe graphify.",
        "evaluate": "Appliquer les gates et calculer la note pondérée.",
        "decide": "Enregistrer une décision motivée.",
    }
    sub = {}
    for name, description in descriptions.items():
        command = commands.add_parser(name, help=description)
        command.add_argument("--json", action="store_true", help="Afficher le résultat structuré.")
        sub[name] = command
    sub["validate"].add_argument("--all", action="store_true", required=True)
    importer = sub["import-decisions"]
    importer.add_argument("--from", dest="source", required=True, type=Path)
    importer.add_argument("--repo", required=True)
    importer.add_argument("--commit", required=True)
    importer.add_argument("--dry-run", action="store_true")
    searcher = sub["search"]
    searcher.add_argument("--query", required=True)
    searcher.add_argument("--scope", choices=("internal",), required=True)
    searcher.add_argument("--graph", type=Path, help="Défaut : BBCTL_GRAPH ou ~/graphify/public/graph.json.")
    searcher.add_argument("--repo")
    searcher.add_argument("--kind")
    searcher.add_argument("--receipt", type=Path)
    sub["evaluate"].add_argument("--candidate", required=True)
    sub["decide"].add_argument("--candidate", required=True)
    sub["decide"].add_argument("--choice", choices=CHOICES, required=True)
    sub["decide"].add_argument("--reason", required=True)
    return cli


def check_args(cli, args):
    if args.command == "decide" and not nonblank(args.reason):
        cli.error("--reason exige une justification.")
    if args.command == "search" and not nonblank(args.query):
        cli.error("--query exige un terme de recherche.")
    if args.command == "import-decisions":
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.repo):
            cli.error("--repo exige un nom de dépôt simple.")
        if not re.fullmatch(r"(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})", args.commit):
            cli.error("--commit exige l'empreinte Git complète.")


def run(args, root):
    command = args.command
    blocks = root / "blocks"
    write = command == "decide" or (command == "import-decisions" and not args.dry_run)
    with lock(root, write=write):
        if command == "import-decisions":
            return import_decisions(blocks, args.source, args.repo, args.commit, args.dry_run)
        if command == "search":
            graph_path = args.graph or Path(os.environ.get("BBCTL_GRAPH") or "~/graphify/public/graph.json")
            return search(blocks, args, graph_path.expanduser())

        records = read_catalogue(blocks / "catalog")
        if command == "validate":
            return {"count": len(records)}
        if args.candidate not in records:
            raise InvalidJSON(f"Candidat absent du catalogue : {args.candidate}.")
        path, block = records[args.candidate]
        result = evaluate(blocks / "evaluations", block)
        if command == "evaluate":
            return result
        if result["eliminated"] and args.choice in {"reuse", "adapt", "wrap", "fork"}:
            raise CatalogueScopeError("Impossible d'adopter un candidat éliminé.")
        decision = {**block["decision"], "status": "decided", "choice": args.choice, "rationale": args.reason}
        if block["decision"] != decision:
            block["decision"] = decision
            write_json(path, block)
        return {"candidate": block["id"], "decision": decision}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cli = parser()
    command = None
    try:
        args = cli.parse_args(argv)
        command = args.command
        check_args(cli, args)
        root = Path(os.environ.get("USINE_RACINE", ROOT)).resolve()
        payload = {"status": "ok", **run(args, root)}
        code = ExitCode.OK
    except UsageError as exc:
        code, payload = ExitCode.USAGE, {"status": "usage", "error": str(exc)}
    except (GraphUnavailable, OSError, ImportError) as exc:
        code, payload = ExitCode.IO, {"status": "source-unavailable", "error": str(exc)}
    except VersionConflict as exc:
        code, payload = ExitCode.VERSION_CONFLICT, {"status": "version-conflict", "error": str(exc)}
    except CatalogueScopeError as exc:
        code, payload = ExitCode.SAFETY, {"status": "safety-refusal", "error": str(exc)}
    except (InvalidJSON, UnicodeError) as exc:
        code, payload = ExitCode.CHECK_FAILED, {"status": "check-failed", "error": str(exc)}
    journal.event("command-finished", command=command, status=payload["status"], code=int(code))
    if "--json" in argv or code == ExitCode.OK:
        sys.stdout.write(json_text(payload))
    else:
        if code == ExitCode.USAGE:
            cli.print_usage(sys.stderr)
        print(payload["error"], file=sys.stderr)
    return code
