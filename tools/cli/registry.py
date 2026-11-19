"""Arguments et distribution des commandes de recherche et de livraison."""

import argparse
from pathlib import Path

from tools.cli import caller_path


def configure(command, parser):
    if command == "search":
        parser.add_argument("query", nargs="?", default="")
        for field in ("tag", "universe", "orientation", "state", "license", "used-by", "category", "family"):
            parser.add_argument(f"--{field}")
        parser.add_argument("--similar-to")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--receipt", type=caller_path)
    elif command == "usage":
        parser.add_argument("subject", help="identifiant ou add")
        parser.add_argument("id", nargs="?")
        for field in ("game", "scene", "role"):
            parser.add_argument(f"--{field}")
        parser.add_argument("--repo-dir", type=caller_path)
        parser.add_argument("--path", type=Path)
        parser.add_argument("--dry-run", action="store_true")
    elif command in {"publish", "export-atlas"}:
        parser.add_argument("ids", nargs="+")
        if command == "publish":
            parser.add_argument("--target", choices=("public", "private"), required=True)
            parser.add_argument("--dest", type=caller_path, required=True)
        else:
            parser.add_argument("--out", type=caller_path, required=True)
            parser.add_argument("--padding", type=int, default=2)
    elif command == "materialize":
        parser.add_argument("id")
        parser.add_argument("--version", type=int)
        parser.add_argument("--to", type=caller_path, required=True)
    elif command in {"check-lock", "validate-atlas"}:
        parser.add_argument("file", type=caller_path)
        if command == "check-lock":
            parser.add_argument("--public", action="store_true")
    elif command == "register":
        parser.add_argument("file", type=caller_path)
        parser.add_argument("--name", required=True)
        parser.add_argument("--category", required=True)
        parser.add_argument("--receipt", type=caller_path)
        parser.add_argument("--reject", action="append", default=[])
    elif command == "derive":
        parser.add_argument("id")
        parser.add_argument("--recipe", type=caller_path, required=True)
    elif command == "sync":
        parser.add_argument("--only", nargs="+", action="extend")
        parser.add_argument("--branch")
        parser.add_argument("--fetch", action=argparse.BooleanOptionalAction, default=True)
    elif command == "sbom":
        parser.add_argument("--out", type=caller_path, required=True)

    if command in {"materialize", "usage"}:
        parser.add_argument("--private-target", action="store_true")
    if command in {"materialize", "usage", "publish", "derive", "export-atlas", "sync"}:
        parser.add_argument("--cache", type=caller_path)


def run(root, args):
    command = args.command
    if command in {"index", "search", "duplicates"}:
        from tools.index import search as operations
    elif command in {"publish", "materialize", "usage", "check-lock"}:
        from tools.publish import delivery as operations
    elif command in {"register", "derive"}:
        from tools import creation as operations
    elif command == "sync":
        from tools.discovery import sync as operations
    elif command == "sbom":
        from tools.publish import sbom as operations
    else:
        from tools.extract import atlas as operations

    return getattr(operations, command.replace("-", "_"))(root, args)
