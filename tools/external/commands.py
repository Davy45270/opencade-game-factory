"""`assetctl external …` (EXT-001 § 7) : providers, search, inspect, plan-import, import, sync, audit-licenses, decide.

Sorties JSON (`--json` ou `--format json`), `--dry-run` pour les mutations, aucun dialogue. Désactivé par
ASSETCTL_EXTERNAL=off : la commande rend 2 (`external-disabled`) et le reste du registre n'en dépend pas.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from tools.core.catalog import Catalogue, read_json, write_json
from tools.core.exit_codes import ExitCode
from tools.discovery.importer import read_assets
from tools.discovery.scan import directory_lock
from tools.external import enabled
from tools.external.adapters import ProviderUnavailable, providers, search_all

SUBCOMMANDS = ("providers", "search", "inspect", "plan-import", "import", "sync", "audit-licenses", "decide")


def configure(parser, caller_path):
    sub = parser.add_subparsers(dest="external_command", required=True)
    for name in SUBCOMMANDS:
        command = sub.add_parser(name, allow_abbrev=False)
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        command.add_argument("--format", choices=("json",), default=None)
        command.add_argument("--dry-run", action="store_true")
        if name in {"search", "decide"}:
            command.add_argument("--query", required=True)
            command.add_argument("--license")
            command.add_argument("--provider")
        if name == "decide":
            command.add_argument("--target", choices=("public", "private"), default="private")
            for field in ("orientation", "state"):
                command.add_argument(f"--{field}")
        if name in {"inspect", "plan-import"}:
            command.add_argument("--provider", required=True)
            command.add_argument("--id", required=True)
        if name == "plan-import":
            command.add_argument("--out", type=caller_path)
            command.add_argument("--target", choices=("public", "private"), default="private")
        if name == "import":
            command.add_argument("--plan", type=caller_path, required=True)
        if name == "sync":
            command.add_argument("--provider", required=True)
            command.add_argument("--from", dest="source", required=True, help="nouvel index du fournisseur (chemin ou URL)")
            command.add_argument("--incremental", action="store_true")


def run(root, args):
    if not enabled():
        return ExitCode.USAGE, {"ok": False, "error": "external-disabled",
                                "message": "Module EXT-001 désactivé (ASSETCTL_EXTERNAL=off)."}
    name = args.external_command
    if name == "providers":
        rows = []
        for adapter in providers(root).values():
            try:
                status, count = "available", len(adapter.packs())
            except ProviderUnavailable as exc:
                status, count = "unavailable", None
            rows.append({"id": adapter.id, "priority": adapter.priority, "policy": adapter.policy,
                         "status": status, "packs": count})
        return ExitCode.OK, {"ok": True, "providers": rows}
    if name == "search":
        overall, statuses, results = search_all(root, args.query, {"license": args.license}, args.provider)
        return ExitCode.OK, {"ok": True, "externalSearchStatus": overall, "providers": statuses,
                             "results": [candidate.to_json() for candidate in results]}
    if name == "inspect":
        adapter = providers(root).get(args.provider)
        if adapter is None:
            return ExitCode.USAGE, {"ok": False, "error": "unknown-provider"}
        try:
            return ExitCode.OK, {"ok": True, "candidate": adapter.inspect(args.id).to_json()}
        except KeyError:
            return ExitCode.CHECK_FAILED, {"ok": False, "error": "not-found"}
        except ProviderUnavailable as exc:
            return ExitCode.IO, {"ok": False, "error": "provider-unavailable", "externalSearchStatus": "unavailable",
                                 "message": str(exc)}
    if name == "decide":
        return decide_command(root, args)
    if name == "plan-import":
        from tools.external.importer import plan

        return plan(root, args)
    if name == "import":
        from tools.external.importer import execute

        return execute(root, args)
    if name == "sync":
        return sync(root, args)
    return audit(root)


def decide_command(root, args):
    from tools.external.decision import decide
    from tools.external.importer import _internal
    from tools.external.licenses import POLICY, LicenseEvaluator

    internal = _internal(root, args.query)
    overall, statuses, external = search_all(root, args.query, {"license": args.license}, args.provider)
    evaluator = LicenseEvaluator()

    def evaluate(candidate):
        # Sans archive lue, la licence de l'index n'est qu'annoncée : l'import passera par plan-import qui la vérifie.
        if candidate.licenseSpdx is None or candidate.metadataConfidence == "unknown":
            return {"allowed": False, "licenseStatus": "unknown", "reason": "licence non annoncée par la source"}
        verdict = {"status": "verified", "spdx": candidate.licenseSpdx, "evidence": "annoncée par l'index"}
        if candidate.licenseSpdx not in POLICY:
            return {"allowed": False, "licenseStatus": "unknown", "reason": f"licence {candidate.licenseSpdx} non prise en charge"}
        return evaluator.for_target(verdict, args.target)

    wanted = {key: getattr(args, key) for key in ("orientation", "state") if getattr(args, key)}
    decision = decide(internal, external, overall, args.target, evaluate, wanted)
    return ExitCode.OK, {"ok": True, "decision": decision, "providers": statuses}


def _external_assets(root):
    return {asset_id: asset for asset_id, asset in read_assets(root).items()
            if asset.get("provenance", {}).get("type") == "external"}


def sync(root, args):
    """EXT-001 § 9 : nouvelle version, retrait ou changement de licence à la source → alerte ; les fiches déjà
    importées gardent leur licence et leurs versions, l'historique est complété (jamais effacé)."""
    adapter = providers(root).get(args.provider)
    if adapter is None:
        return ExitCode.USAGE, {"ok": False, "error": "unknown-provider"}
    index_path = Path(adapter.index_location())
    try:
        previous = {c.externalId: c for c in adapter.packs()}
    except ProviderUnavailable:
        previous = {}
    import os
    key = f"ASSETCTL_EXTERNAL_INDEX_{adapter.id.upper().replace('-', '_')}"
    saved = os.environ.get(key)
    os.environ[key] = str(args.source)
    try:
        current = {c.externalId: c for c in adapter.packs()}
        raw_index = (Path(args.source).read_text(encoding="utf-8") if "://" not in str(args.source) else None)
    except ProviderUnavailable as exc:
        return ExitCode.IO, {"ok": False, "error": "provider-unavailable", "externalSearchStatus": "unavailable",
                             "message": str(exc)}
    finally:
        if saved is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = saved
    changes = {"new": sorted(current.keys() - previous.keys()), "removed": sorted(previous.keys() - current.keys()),
               "updated": sorted(i for i in current.keys() & previous.keys()
                                 if current[i].sourceVersion != previous[i].sourceVersion)}
    alerts, touched = [], {}
    observed = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for asset_id, asset in sorted(_external_assets(root).items()):
        external = asset["provenance"]["external"]
        if external["provider"] != adapter.id:
            continue
        pack = current.get(external["externalPackId"])
        if pack is None:
            if external.get("sourceStatus") != "removed":
                alerts.append({"assetId": asset_id, "alert": "removed-at-source", "pack": external["externalPackId"]})
                external["sourceStatus"] = "removed"
                touched[asset_id] = asset
            continue
        was = external["license"]["spdxId"]
        history = external.get("licenseHistory", [])
        last = history[-1]["to"] if history else was
        now_license = pack.licenseSpdx or "unknown"
        if now_license != last:
            alerts.append({"assetId": asset_id, "alert": "license-changed-at-source", "from": last, "to": now_license})
            external["licenseHistory"] = [*history, {"observedAt": observed, "from": last, "to": now_license,
                                                     "note": "changement à la source ; la version importée garde sa licence"}]
            touched[asset_id] = asset
    result = {"ok": True, "provider": adapter.id, "changes": changes, "alerts": alerts, "dryRun": bool(args.dry_run)}
    if args.dry_run:
        return ExitCode.OK, result
    with directory_lock(root / "catalog"):
        catalogue = Catalogue(root)
        for asset_id, asset in touched.items():
            write_json(catalogue._regular_path(catalogue.path / "assets" / f"{asset_id}.json"), asset)
        if raw_index is not None:
            index_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(index_path, json.loads(raw_index))
    return ExitCode.OK, result


def audit(root):
    """EXT-06 : par ressource externe, statut de licence ; tout écart entre licence déclarée et preuve est un échec."""
    rows, problems = [], []
    for asset_id, asset in sorted(_external_assets(root).items()):
        external = asset["provenance"]["external"]
        status = external["license"]["status"]
        rows.append({"assetId": asset_id, "provider": external["provider"], "pack": external["externalPackId"],
                     "license": asset["license"], "status": status,
                     "publicExport": "forbidden" if asset.get("publicExport") == "forbidden" or status != "verified"
                     else "allowed-with-credits" if external["license"].get("attribution") else "allowed",
                     "sourceStatus": external.get("sourceStatus", "available"),
                     "licenseChanges": len(external.get("licenseHistory", []))})
        if asset["license"] != "unknown" and status != "verified":
            problems.append({"assetId": asset_id, "problem": "licence déclarée sans preuve vérifiée"})
        if status != "verified" and asset.get("publicExport") != "forbidden":
            problems.append({"assetId": asset_id, "problem": "licence non vérifiée sans interdiction d'export public"})
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return (ExitCode.CHECK_FAILED if problems else ExitCode.OK), {"ok": not problems, "assets": rows,
                                                                    "counts": counts, "problems": problems}
