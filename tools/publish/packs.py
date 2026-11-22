"""`assetctl pack build|export` — REG-09 (packs d'assets versionnés et export contrôlé) et EXT-13 (crédits).

- build : fige une liste {id, version, sha256, licence} sous `catalog/packs/<nom>/<version>.json`. Une version de pack
  est immuable : la reconstruire à l'identique rend `unchanged`, avec un autre contenu `version-immutable` (code 5).
- export : rejoue la publication (tools/publish/delivery.py) des ressources EXACTES du pack ; un asset modifié depuis
  le pack rend `pack-stale` (code 5). Cible publique : TOUT le pack est refusé (code 3, rien d'écrit) si une seule
  ressource n'a pas de licence vérifiée et autorisée (AT-08) ; sinon crédits (THIRD_PARTY_ASSETS.md), manifeste de
  provenance, textes de licence (LICENSES/) et verrou du pack (pack.lock.json) accompagnent les fichiers.
"""

import argparse
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from tools import asset_versions
from tools.core.catalog import CatalogueScopeError, json_text, read_json, write_json
from tools.core.exit_codes import ExitCode
from tools.discovery.scan import directory_lock
from tools.publish.delivery import Delivery, check_destination, output_path, put, scoped_path

NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SEMVER = re.compile(r"\d+\.\d+\.\d+")


def configure(parser, caller_path):
    sub = parser.add_subparsers(dest="pack_command", required=True)
    build = sub.add_parser("build", allow_abbrev=False)
    export = sub.add_parser("export", allow_abbrev=False)
    for command in (build, export):
        command.add_argument("name")
        command.add_argument("--version", required=True)
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        command.add_argument("--dry-run", action="store_true")
    build.add_argument("--asset", action="append", default=[])
    build.add_argument("--game", help="toutes les ressources utilisées par ce jeu")
    export.add_argument("--target", choices=("public", "private"), required=True)
    export.add_argument("--dest", type=caller_path, required=True)


def _path(root, name, version):
    return Path(root) / "catalog" / "packs" / name / f"{version}.json"


def _digest(rows):
    return hashlib.sha256(json_text(rows).encode()).hexdigest()


def build(root, args):
    if not NAME.fullmatch(args.name) or not SEMVER.fullmatch(args.version):
        return ExitCode.USAGE, {"ok": False, "error": "usage", "message": "nom en kebab-case et version semver"}
    delivery = Delivery(Path(root), args)
    ids = set(args.asset)
    if args.game:
        ids |= {i for i, a in delivery.assets.items() if any(u.get("game") == args.game for u in a.get("usages", []))}
    if not ids:
        return ExitCode.USAGE, {"ok": False, "error": "usage", "message": "pack vide : --asset ou --game"}
    rows = []
    for asset_id in sorted(ids):
        asset = delivery.asset(asset_id)
        rows.append({"id": asset_id, "version": asset_versions.version_number(asset), "sha256": asset["sha256"],
                     "license": asset["license"]})
    pack = {"schemaVersion": "1.0", "name": args.name, "version": args.version, "assets": rows,
            "assetsSha256": _digest(rows)}
    path = _path(root, args.name, args.version)
    if path.is_file():
        old = read_json(path)
        if old["assetsSha256"] == pack["assetsSha256"]:
            return ExitCode.OK, {"ok": True, "status": "unchanged", "pack": old}
        return ExitCode.VERSION_CONFLICT, {"ok": False, "error": "version-immutable",
                                           "message": f"{args.name}@{args.version} est déjà publiée avec un autre contenu"}
    pack["createdAt"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if not args.dry_run:
        with directory_lock(Path(root) / "catalog"):
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, pack)
    return ExitCode.OK, {"ok": True, "status": "created" if not args.dry_run else "dry-run",
                         "path": path.relative_to(root).as_posix(), "pack": pack}


def export(root, args):
    from argparse import Namespace

    from tools.publish.delivery import _publish

    root = Path(root)
    path = _path(root, args.name, args.version)
    if not path.is_file():
        return ExitCode.CHECK_FAILED, {"ok": False, "error": "pack-not-found"}
    pack = read_json(path)
    delivery = Delivery(root, args)
    stale, refused = [], []
    for row in pack["assets"]:
        asset = delivery.asset(row["id"])
        if asset["sha256"] != row["sha256"] or asset_versions.version_number(asset) != row["version"]:
            stale.append(row["id"])
        elif args.target == "public":
            try:
                delivery.require_public({**asset, "id": row["id"]})
            except CatalogueScopeError as exc:
                refused.append({"id": row["id"], "license": asset["license"], "reason": str(exc)})
    if stale:
        return ExitCode.VERSION_CONFLICT, {"ok": False, "error": "pack-stale", "assets": stale,
                                           "message": "des ressources ont changé depuis cette version du pack : "
                                                      "construire une nouvelle version"}
    if refused:
        return ExitCode.SAFETY, {"ok": False, "error": "public-export-refused", "refused": refused,
                                 "message": "export public refusé pour tout le pack (licence non vérifiée)"}
    code, result = _publish(root, Namespace(ids=[r["id"] for r in pack["assets"]], target=args.target,
                                            dest=args.dest, dry_run=args.dry_run, cache=None))
    if code != ExitCode.OK:
        return code, result
    directory = output_path(root, args.dest, kind="publish")
    extra = [(scoped_path(directory / "pack.lock.json"), json_text(pack).encode())]
    if args.target == "public":
        for row in pack["assets"]:
            asset = delivery.assets[row["id"]]
            external = asset.get("provenance", {}).get("external") or {}
            text = (external.get("license") or {}).get("textPath")
            ref = root / "LICENSES" / f"{asset['license']}.txt"
            source = root / text if text else ref if ref.is_file() else None
            if source and source.is_file():
                name = f"{asset['license']}-{hashlib.sha256(str(source).encode()).hexdigest()[:8]}.txt"
                extra.append((scoped_path(directory / "LICENSES" / name), source.read_bytes()))
    for target, raw in extra:
        check_destination(target, raw)
    if not args.dry_run:
        for target, raw in extra:
            target.parent.mkdir(parents=True, exist_ok=True)
            put(target, raw)
    return ExitCode.OK, {"ok": True, "pack": f"{args.name}@{args.version}", "target": args.target,
                         "assets": len(pack["assets"]), "dryRun": bool(args.dry_run)}


def run(root, args):
    return (build if args.pack_command == "build" else export)(root, args)
