"""Interface headless du registre."""

import argparse
import os
import sys
from contextlib import ExitStack
from pathlib import Path

from tools.core import journal
from tools.core.catalog import ROOT, Catalogue, CatalogueScopeError, InvalidJSON, json_text
from tools.core.exit_codes import ExitCode
from tools.core.git_base import InvalidRef
from tools.core.ids import parse_id

# Les commandes de découverte et découpe précèdent la recherche et la publication.
COMMANDS = {
    "search": ("L3", False),
    "inspect": (None, False),
    "import-sheet": (None, True),
    "extract": (None, True),
    "register": ("L3", True),
    "derive": ("L3", True),
    "validate": (None, False),
    "usage": ("L3", False),
    "publish": ("L3", True),
    "duplicates": ("L2", False),
    "scan-repos": (None, True),
    "sync": ("L3", True),
    "index": (None, True),
}


class UsageError(ValueError):
    pass


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def _options(parser):
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="écrire le résultat en JSON sur stdout")
    parser.add_argument("--log", type=Path, default=argparse.SUPPRESS,
                        help="ajouter le journal JSON Lines à ce fichier")


def _parser():
    parser = ArgumentParser(prog="assetctl", allow_abbrev=False)
    _options(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, (lot, mutates) in COMMANDS.items():
        description = f"prévu dans le lot {lot}" if lot else "consulter le catalogue"
        sub = subparsers.add_parser(command, help=description, allow_abbrev=False)
        _options(sub)
        if mutates:
            sub.add_argument("--dry-run", action="store_true", help="simuler sans mutation")
        if command == "validate":
            sub.add_argument("--base", metavar="REF", help="comparer le catalogue à une révision Git")
        elif command == "inspect":
            sub.add_argument("id")
        elif command == "scan-repos":
            sub.add_argument("--sources", type=Path, help="sélection issue de catalog/sources.json")
            sub.add_argument("--cache", type=Path)
            sub.add_argument("--only", nargs="+")
            sub.add_argument("--provider", choices=("github", "forgejo", "local"))
            sub.add_argument("--fetch", action=argparse.BooleanOptionalAction, default=True)
            sub.add_argument("--job", type=Path)
            sub.add_argument("--verify", action="store_true")
        elif command == "import-sheet":
            sub.add_argument("file", type=Path)
            sub.add_argument("--decoupe", type=Path)
        elif command == "extract":
            sub.add_argument("sheet_id")
            mode = sub.add_mutually_exclusive_group()
            mode.add_argument("--regions", type=Path)
            mode.add_argument("--candidates", action="store_true")
            sub.add_argument("--out", type=Path)
            sub.add_argument("--cache", type=Path)
        elif command == "index":
            sub.add_argument("operation", choices=["rebuild"], nargs="?", default="rebuild")
        elif lot:
            sub.add_argument("arguments", nargs="*", help=argparse.SUPPRESS)
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
    if args.command == "index":
        from tools.discovery.importer import read_assets
        from tools.discovery.references import emit as emit_usages
        from tools.discovery.scan import directory_lock
        from tools.publish.licenses import emit as emit_licenses

        with directory_lock(root / "catalog"):
            assets = read_assets(root)
            catalogue = Catalogue(root)
            sheets = [catalogue.read(path) for path in catalogue.documents("sheets")]
            if not args.dry_run:
                for folder in ("generated", "generated/reports"):
                    Catalogue._regular_path(root / folder)
                emit_usages(root, assets.values())
                emit_licenses(root, assets.values(), sheets)
        return ExitCode.OK, {"ok": True, "assets": len(assets), "sheets": len(sheets)}
    return ExitCode.USAGE, {"ok": False, "error": "not-implemented", "lot": COMMANDS[args.command][0]}


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
            if getattr(args, "log", None) is not None:
                log_path = args.log.resolve()
                catalogue_path = (Path(root) / "catalog").resolve()
                if log_path.is_relative_to(catalogue_path):
                    raise CatalogueScopeError("Le journal doit être extérieur au catalogue.")
                if args.command in {"scan-repos", "import-sheet", "extract"}:
                    def open_log(path, flags):
                        descriptor = os.open(path, flags | os.O_NOFOLLOW, 0o600)
                        if os.fstat(descriptor).st_nlink > 1:
                            os.close(descriptor)
                            raise CatalogueScopeError("Lien dur interdit pour le journal du scan.")
                        return descriptor

                    stream = stack.enter_context(open(log_path, "a", encoding="utf-8", newline="\n",
                                                      opener=open_log))
                else:
                    stream = stack.enter_context(log_path.open("a", encoding="utf-8", newline="\n"))
            code, payload = _run(args, Path(root), selected)
        except (UsageError, InvalidRef) as exc:
            code, payload = ExitCode.USAGE, {"ok": False, "error": "usage", "message": str(exc)}
        except CatalogueScopeError as exc:
            code, payload = ExitCode.SAFETY, {"ok": False, "error": "safety", "message": str(exc)}
        except InvalidJSON as exc:
            code, payload = ExitCode.CHECK_FAILED, {"ok": False, "error": "invalid-json", "message": str(exc)}
        except (OSError, ImportError) as exc:
            code, payload = ExitCode.IO, {"ok": False, "error": "io", "message": str(exc)}

        try:
            journal.event("command-finished", stream=stream, command=args.command,
                          ok=payload["ok"], code=int(code))
        except OSError as exc:
            code, payload = ExitCode.IO, {"ok": False, "error": "io", "message": str(exc)}
            journal.event("log-error", command=args.command, code=int(code))
        _output(payload, as_json=getattr(args, "json", False))
        return int(code)
