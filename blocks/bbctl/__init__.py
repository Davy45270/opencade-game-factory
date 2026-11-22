"""CLI du registre BB-001."""

import argparse
import os
import re
import sys
from pathlib import Path

from tools.core import journal
from tools.core.catalog import CatalogueScopeError, InvalidJSON, ROOT, json_text, read_json, write_json
from tools.core.exit_codes import ExitCode

from .decisions import VersionConflict, import_decisions
from .discover import discover, impact, inspect, usages
from .opensource import search_opensource
from . import evenements
from .adoption import Conflict, adopt, gate, write_block
from .liens import link_specs
from .duplicates import duplicates
from .evaluation import evaluate, nonblank
from .registry import lock, read_catalogue
from .search import GraphUnavailable, read_graph, search
from . import index as generes, recu
from .sbom import sbom as sbom_catalogue

CHOICES = ("reuse", "adapt", "wrap", "fork", "build", "defer")


class Unknown(GraphUnavailable):
    """ARCH-001 AT-02 : l'existant n'a pas pu être lu ; il est inconnu, pas absent."""


def graph_path_of(args):
    return Path(args.graph or os.environ.get("BBCTL_GRAPH") or "~/graphify/public/graph.json").expanduser()
CODE_HELP = """Codes de retour
  0 succès
  1 contrôle en échec
  2 usage
  3 refus de sécurité
  4 source indisponible
  5 conflit de versions"""


class UsageError(ValueError):
    pass


class Uncovered(Exception):
    """gate : briques nouvelles sans décision ni dérogation (code 1, résultat complet en JSON)."""

    def __init__(self, result):
        super().__init__("Brique nouvelle sans recherche documentée : " + ", ".join(result["uncovered"]))
        self.result = result


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
        "adopt": "Adopter une brique décidée : SBOM, verrou de version, PR, tests, usedBy.",
        "gate": "Contrôle « reuse before build » entre deux commits d'un dépôt de jeu.",
        "link-specs": "Relier chaque brique aux spécifications REG-003 de ses projets consommateurs.",
        "sbom": "SBOM CycloneDX des briques (versions, licences, dépendances des dépôts consommateurs).",
        "index": "Générer l'index SQLite FTS5 et le graphe de dépendances depuis le catalogue (--check : comparer).",
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
    searcher.add_argument("--scope", choices=("internal", "opensource", "catalog"), required=True)
    searcher.add_argument("--index", type=Path, help="catalog : dossier écrit par bbctl index --out.")
    searcher.add_argument("--project", help="internal avec --receipt : étape 1, specctl resolve du projet.")
    searcher.add_argument("--ecosystem", choices=("npm",), default="npm", help="opensource : registre interrogé.")
    searcher.add_argument("--size", type=int, default=10, help="opensource : nombre de candidats.")
    searcher.add_argument("--record", action="store_true", help="opensource : inscrire les candidats au catalogue.")
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
    adopter = sub["adopt"]
    adopter.add_argument("--candidate", required=True)
    adopter.add_argument("--used-by", required=True)
    adopter.add_argument("--version", required=True)
    adopter.add_argument("--pr", required=True)
    adopter.add_argument("--tests", required=True)
    adopter.add_argument("--sbom")
    for name in ("adopt", "decide"):
        sub[name].add_argument("--expect", metavar="SHA256", help="Empreinte de la fiche lue : refus si elle a changé.")
    sub["link-specs"].add_argument("--dry-run", action="store_true")
    sub["index"].add_argument("--out", type=Path, required=True)
    sub["sbom"].add_argument("--out", type=Path, required=True)
    sub["index"].add_argument("--check", action="store_true")
    for name in ("evaluate", "decide"):
        sub[name].add_argument("--receipt", type=Path, help="Reçu commun reuse before build : l'étape y est ajoutée.")
    gater = sub["gate"]
    gater.add_argument("--repo", type=Path, required=True)
    gater.add_argument("--base", required=True)
    gater.add_argument("--head", default="HEAD")
    gater.add_argument("--name", help="Nom du dépôt (défaut : nom du dossier).")
    sub["evaluate"].add_argument("--candidate", required=True)
    sub["decide"].add_argument("--candidate", required=True)
    sub["decide"].add_argument("--choice", choices=CHOICES, required=True)
    sub["decide"].add_argument("--reason", required=True)
    sub["decide"].add_argument("--graph", type=Path, help="build seulement : graphe graphify consulté (défaut : BBCTL_GRAPH "
                               "ou ~/graphify/public/graph.json) ; illisible = existant inconnu, build refusé (AT-02).")
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
    write = (command in {"decide", "adopt", "gate"} or (command == "link-specs" and not args.dry_run) or (command in {"import-decisions", "discover"} and not args.dry_run)
             or (command == "search" and args.scope == "opensource" and args.record))
    with lock(root, write=write):
        if command == "import-decisions":
            return import_decisions(blocks, args.source, args.repo, args.commit, args.dry_run)
        if command == "search" and args.scope == "catalog":
            if args.index is None:
                raise UsageError("--scope catalog exige --index.")
            return generes.chercher(args.index, args.query, args.size)
        if command == "search" and args.scope == "opensource":
            return search_opensource(blocks, args.query, args.ecosystem, args.size, args.record)
        if command == "search":
            graph_path = args.graph or Path(os.environ.get("BBCTL_GRAPH") or "~/graphify/public/graph.json")
            result = search(blocks, args, graph_path.expanduser())
            # ARCH-001 § 10 étape 2 : la recherche est un maillon observable de la tranche (opt-in, n'échoue jamais).
            evenements.emettre("bb.searched", "success", args.repo or "inconnu",
                               sorted({x["block"] for x in result["results"] if x["block"]}),
                               {"query": args.query, "scope": "internal", "results": len(result["results"])},
                               args.query + (args.repo or ""))
            return result

        if command == "discover":
            return discover(blocks, args.sources or root / "catalog" / "sources.json", args.clones, args.dry_run)

        records = read_catalogue(blocks / "catalog")
        if command == "index":
            return generes.index(records, args.out, args.check)
        if command == "sbom":
            return sbom_catalogue(records, args.out)
        if command == "inspect":
            return {**inspect(records, args.block), "status": generes.statuts(records[args.block][1])}
        if command == "usages":
            return usages(records, args.block)
        if command == "impact":
            result = impact(records, args.block, args.to_version)
            # ARCH-001 AT-12 : l'impact d'un changement de contrat partagé remonte à la Tour (opt-in, n'échoue jamais).
            block = records[args.block][1]
            evenements.emettre("bb.impact-detected", "success", projet_de(block), [args.block],
                               {"toVersion": args.to_version, "projects": result["impacted"]},
                               args.to_version + ",".join(result["impacted"]), specs=block.get("specIds") or ())
            return result
        if command == "adopt":
            return adopt(blocks, records, args)
        if command == "link-specs":
            return link_specs(blocks, records, args.dry_run)
        if command == "gate":
            try:
                result = gate(blocks, records, args.repo, args.base, args.head, args.name)
            except ValueError as exc:
                raise UsageError(str(exc)) from exc
            if result["uncovered"]:
                raise Uncovered(result)
            return result
        if command == "validate":
            # E183 : `adopted` = approuvée ET consommée ; sans consommateur, les deux axes sont confondus.
            orphelines = generes.incoherences(records)
            if orphelines:
                raise InvalidJSON("Brique adoptée sans consommateur (usedBy vide) : " + ", ".join(orphelines))
            return {"count": len(records), "specLinks": check_spec_links(root, records)}
        if args.candidate not in records:
            raise InvalidJSON(f"Candidat absent du catalogue : {args.candidate}.")
        path, block = records[args.candidate]
        result = evaluate(blocks / "evaluations", block)
        if command == "evaluate":
            if args.receipt:
                recu.ajouter(args.receipt, blocks, [{"step": "bbctl evaluate", "candidate": block["id"],
                                                     "eliminated": result["eliminated"], "score": result["score"]}])
            return result
        if result["eliminated"] and args.choice in {"reuse", "adapt", "wrap", "fork"}:
            raise CatalogueScopeError("Impossible d'adopter un candidat éliminé.")
        # BB-001 T07 : une décision argumentée porte la note pondérée qui l'a fondée (None si le candidat est éliminé).
        decision = {**block["decision"], "status": "decided", "choice": args.choice, "rationale": args.reason,
                    "score": result["score"]}
        decision.pop("searchGraphSha256", None)
        if args.choice == "build":
            # AT-02 : construire = remplacer ce qui existe peut-être. Sans recherche interne lisible, l'existant est
            # INCONNU (jamais « absent ») : la décision est bloquée, rien n'est écrit.
            try:
                _, digest = read_graph(graph_path_of(args))
            except GraphUnavailable as exc:
                raise Unknown(f"Existant inconnu, décision build bloquée : {exc}") from exc
            decision["searchGraphSha256"] = digest
        changed = False
        if block["decision"] != decision or args.expect is not None:
            block["decision"] = decision
            changed = write_block(blocks, path, block, "decide", args.expect)
        if changed:
            evenements.emettre("bb.decided", "success", projet_de(block), [block["id"]],
                               {"choice": args.choice, "score": result["score"]}, args.choice + args.reason,
                               specs=block.get("specIds") or ())
        if args.receipt:
            recu.ajouter(args.receipt, blocks, [{"step": "bbctl decide", "candidate": block["id"], "choice": args.choice,
                                                 "rationale": args.reason, "score": result["score"]}])
        return {"candidate": block["id"], "decision": decision, "changed": changed}


def projet_de(block):
    """projectId d'un événement de brique : le dépôt d'origine, sinon le premier consommateur sans son sous-chemin
    (« six-de-chaque/apps/web » → « six-de-chaque ») — un seul projet par trace (towerctl trace)."""
    repo = (block.get("origin") or {}).get("repo")
    return repo or ((block.get("usedBy") or ["inconnu"])[0]).split("/")[0]


def check_spec_links(root, records):
    """ARCH-001 E055 : chaque specIds résout vers une fiche du registre des specs ; registre absent = dit, pas refusé."""
    registry = root / "specs" / "registry"
    if not registry.is_dir():
        return "registre-absent"
    known = set()
    for path in registry.glob("SPEC-*.json"):
        record = read_json(path)
        if isinstance(record, dict) and isinstance(record.get("id"), str):
            known.add(record["id"])
    broken = sorted(f"{block_id} -> {spec}" for block_id, (_, block) in records.items()
                    for spec in block.get("specIds") or () if spec not in known)
    if broken:
        raise InvalidJSON("Lien de spec non résolu : " + ", ".join(broken))
    return "verifies"


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
    except Unknown as exc:
        code, payload = ExitCode.IO, {"status": "unknown", "error": str(exc)}
    except (GraphUnavailable, OSError, ImportError) as exc:
        code, payload = ExitCode.IO, {"status": "source-unavailable", "error": str(exc)}
    except Uncovered as exc:
        code, payload = ExitCode.CHECK_FAILED, {"status": "check-failed", "error": str(exc), **exc.result}
    except Conflict as exc:
        code, payload = ExitCode.VERSION_CONFLICT, {"status": "conflict", "error": str(exc)}
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
