"""Interface headless du registre."""

import argparse
import os
import sqlite3
import sys
from contextlib import ExitStack
from pathlib import Path

from tools.core import journal
from tools.core.catalog import ROOT, Catalogue, CatalogueScopeError, InvalidJSON, json_text
from tools.core.exit_codes import ExitCode
from tools.core.git_base import InvalidRef
from tools.core.ids import parse_id

COMMANDS = {
    "search": True, "inspect": False, "import-sheet": True, "extract": True,
    "register": True, "derive": True, "validate": False, "usage": False,
    "publish": True, "duplicates": True, "scan-repos": True, "sync": True,
    "index": True, "materialize": True, "check-lock": False, "export-atlas": True,
    "validate-atlas": False, "sbom": True, "external": False,
}


class UsageError(ValueError):
    pass


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def caller_path(value):
    # Keep symlinks visible to the directory and file guards.
    return Path(os.path.abspath(value))


def _options(parser):
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="écrire le résultat en JSON sur stdout")
    parser.add_argument("--log", type=caller_path, default=argparse.SUPPRESS,
                        help="ajouter le journal JSON Lines à ce fichier")


def _parser():
    parser = ArgumentParser(prog="assetctl", allow_abbrev=False)
    _options(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    from tools.cli.registry import configure

    for command, mutates in COMMANDS.items():
        sub = subparsers.add_parser(command, allow_abbrev=False)
        _options(sub)
        if mutates:
            sub.add_argument("--dry-run", action="store_true", help="simuler sans mutation")
        if command == "validate":
            sub.add_argument("--base", metavar="REF", help="comparer le catalogue à une révision Git")
        elif command == "inspect":
            sub.add_argument("id")
        elif command == "scan-repos":
            sub.add_argument("--sources", type=caller_path, help="sélection issue de catalog/sources.json")
            sub.add_argument("--cache", type=caller_path)
            sub.add_argument("--only", nargs="+")
            sub.add_argument("--provider", choices=("github", "forgejo", "local"))
            sub.add_argument("--fetch", action=argparse.BooleanOptionalAction, default=True)
            sub.add_argument("--job", type=caller_path)
            sub.add_argument("--verify", action="store_true")
        elif command == "import-sheet":
            sub.add_argument("file", type=caller_path)
            sub.add_argument("--decoupe", type=caller_path)
        elif command == "extract":
            sub.add_argument("sheet_id")
            mode = sub.add_mutually_exclusive_group()
            mode.add_argument("--regions", type=caller_path)
            mode.add_argument("--candidates", action="store_true")
            sub.add_argument("--out", type=caller_path)
            sub.add_argument("--cache", type=caller_path)
        elif command == "external":
            from tools.external.commands import configure as external

            external(sub, caller_path)
        elif command == "index":
            sub.add_argument("operation", choices=["rebuild"], nargs="?", default="rebuild")
        else:
            configure(command, sub)
    return parser


def _inspect(root, record_id):
    if not parse_id(record_id):
        raise UsageError(f"Identifiant invalide : {record_id}")
    catalogue = Catalogue(root)
    is_sheet = record_id.startswith("sheet-")
    kind = "sheet" if is_sheet else "asset"
    collection = "sheets" if is_sheet else "assets"
    files = {file.stem: file for file in catalogue.documents(collection)}
    if record_id not in files:
        return ExitCode.CHECK_FAILED, {"ok": False, "error": "not-found", "id": record_id}

    def read_record(path, schema):
        from tools.core.schemas import schemas

        value = catalogue.read(path)
        error = next(schemas().validator(schema).iter_errors(value), None)
        if error is not None or value["id"] != path.stem:
            raise InvalidJSON(f"Fiche {path.name} invalide : {error.message if error else 'identifiant incohérent'}")
        return value

    record = read_record(files[record_id], kind)
    if is_sheet:
        usages = [
            {"assetId": asset["id"], **usage}
            for path in catalogue.documents("assets")
            if (asset := read_record(path, "asset"))["sourceSheetId"] == record_id
            or any(frame["atlasSheetId"] == record_id for frame in asset["files"].get("atlasFrames", ()))
            for usage in asset["usages"]
        ]
    else:
        from tools.asset_versions import initialize

        initialize(record)
        usages = record["usages"]
    return ExitCode.OK, {"ok": True, kind: record, "usages": usages}


def _run(args, root, selected=None):
    if args.command == "scan-repos":
        from tools.discovery.scan import run

        return run(root, args, selected)
    if args.command == "validate":
        from tools.validate import validate

        issues = validate(root, args.base)
        return (ExitCode.CHECK_FAILED if issues else ExitCode.OK), {"ok": not issues, "issues": issues}
    if args.command == "inspect":
        return _inspect(root, args.id)
    if args.command in {"import-sheet", "extract"}:
        from tools.extract.commands import run

        return run(root, args)
    if args.command == "external":
        from tools.external.commands import run

        return run(root, args)
    from tools.cli.registry import run

    return run(root, args)


def _output(payload, *, as_json):
    if as_json or "error" in payload or "usages" in payload or "issues" not in payload:
        print(json_text(payload), end="")
    elif payload["ok"]:
        print("Catalogue valide.")
    else:
        for issue in payload["issues"]:
            print(f"{issue['path']} [{issue['code']}] {issue['message']}")


def main(argv=None, *, root=ROOT):
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = _parser().parse_args(argv)
        if getattr(args, "format", None) == "json":
            args.json = True
    except UsageError as exc:
        result = {"ok": False, "error": "usage", "message": str(exc)}
        journal.event("usage-error", message=str(exc), code=int(ExitCode.USAGE))
        if "--json" in argv:
            _output(result, as_json=True)
        return int(ExitCode.USAGE)

    with ExitStack() as stack:
        stream = None
        try:
            selected = None
            if args.command == "scan-repos":
                from tools.discovery.scan import preflight

                selected = preflight(Path(root), args)
            if args.command in {"import-sheet", "extract"}:
                from tools.extract.commands import preflight

                preflight(Path(root), args)
            log_path = None
            if getattr(args, "log", None) is not None and not getattr(args, "dry_run", False):
                from tools.publish.delivery import scoped_path, worktree

                log_path = scoped_path(args.log)
                registry = Path(root).resolve()
                checkout = worktree(log_path)
                if (any(log_path.is_relative_to(registry / directory) for directory in ("catalog", "published"))
                        or ".git" in log_path.parts
                        or checkout is not None and checkout != worktree(registry)):
                    raise CatalogueScopeError("Le journal doit être extérieur au catalogue et aux jeux.")
                if not log_path.parent.is_dir() or (log_path.exists() and not log_path.is_file()):
                    raise OSError("Destination du journal indisponible.")
                if log_path.exists() and log_path.stat().st_nlink > 1:
                    raise CatalogueScopeError("Lien dur interdit pour le journal.")
            code, payload = _run(args, Path(root), selected)
            if log_path is not None and code != ExitCode.SAFETY:
                def open_log(path, flags):
                    descriptor = os.open(path, flags | os.O_NOFOLLOW, 0o600)
                    if os.fstat(descriptor).st_nlink > 1:
                        os.close(descriptor)
                        raise CatalogueScopeError("Lien dur interdit pour le journal.")
                    return descriptor

                stream = stack.enter_context(open(log_path, "a", encoding="utf-8", newline="\n",
                                                  opener=open_log))
        except (UsageError, InvalidRef) as exc:
            code, payload = ExitCode.USAGE, {"ok": False, "error": "usage", "message": str(exc)}
        except CatalogueScopeError as exc:
            code, payload = ExitCode.SAFETY, {"ok": False, "error": "safety", "message": str(exc)}
        except InvalidJSON as exc:
            code, payload = ExitCode.CHECK_FAILED, {"ok": False, "error": "invalid-json", "message": str(exc)}
        except (OSError, ImportError, sqlite3.Error) as exc:
            code, payload = ExitCode.IO, {"ok": False, "error": "io", "message": str(exc)}

        try:
            journal.event("command-finished", stream=stream, command=args.command,
                          ok=payload["ok"], code=int(code))
        except OSError as exc:
            code, payload = ExitCode.IO, {"ok": False, "error": "io", "message": str(exc)}
            journal.event("log-error", command=args.command, code=int(code))
        _output(payload, as_json=getattr(args, "json", False))
        return int(code)
