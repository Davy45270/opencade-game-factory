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
from .discover import discover, impact, inspect, usages
from .duplicates import duplicates
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
        "duplicates": "Signaler les doublons entre dépôts.",
        "evaluate": "Appliquer les gates et calculer la note pondérée.",
        "decide": "Enregistrer une décision motivée.",
        "discover": "Découvrir les briques des dépôts autorisés (lecture seule des dépôts).",
        "inspect": "Afficher une fiche.",
        "usages": "Dépôts et jeux qui utilisent une brique.",
        "impact": "Projets touchés par un changement de version.",
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
    detector = sub["duplicates"]
    detector.add_argument("--graph", type=Path, required=True)
    detector.add_argument("--root", action="append", default=[], metavar="DÉPÔT=CHEMIN")
    detector.add_argument("--min-similarity", type=float, default=0.85)
    finder = sub["discover"]
    finder.add_argument("--repos", choices=("authorized",), required=True)
    finder.add_argument("--sources", type=Path, help="Défaut : catalog/sources.json de l'usine.")
    finder.add_argument("--clones", type=Path, default=Path("~/Projets/jeux"))
    finder.add_argument("--dry-run", action="store_true")
    for name in ("inspect", "usages", "impact"):
        sub[name].add_argument("block")
    sub["impact"].add_argument("--to-version", required=True)
    sub["evaluate"].add_argument("--candidate", required=True)
    sub["decide"].add_argument("--candidate", required=True)
    sub["decide"].add_argument("--choice", choices=CHOICES, required=True)
    sub["decide"].add_argument("--reason", required=True)
    return cli


def check_args(cli, args):
    if args.command == "duplicates":
        if not 0 <= args.min_similarity <= 1:
            cli.error("--min-similarity doit être compris entre 0 et 1.")
        roots = {}
        for value in args.root:
            repo, _, path = value.partition("=")
            if not repo or not path or repo in roots:
                cli.error("--root exige DÉPÔT=CHEMIN, une fois par dépôt.")
            roots[repo] = Path(path).expanduser()
        args.roots = roots
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
    if command == "duplicates":
        return duplicates(args.graph.expanduser(), args.roots, args.min_similarity)
    blocks = root / "blocks"
    write = command == "decide" or (command in {"import-decisions", "discover"} and not args.dry_run)
    with lock(root, write=write):
        if command == "import-decisions":
            return import_decisions(blocks, args.source, args.repo, args.commit, args.dry_run)
        if command == "search":
            graph_path = args.graph or Path(os.environ.get("BBCTL_GRAPH") or "~/graphify/public/graph.json")
            return search(blocks, args, graph_path.expanduser())

        if command == "discover":
            return discover(blocks, args.sources or root / "catalog" / "sources.json", args.clones, args.dry_run)

        records = read_catalogue(blocks / "catalog")
        if command == "inspect":
            return inspect(records, args.block)
        if command == "usages":
            return usages(records, args.block)
        if command == "impact":
            return impact(records, args.block, args.to_version)
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
