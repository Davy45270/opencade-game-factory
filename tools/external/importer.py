"""ImportPlanner et ImportExecutor (EXT-001 § 3 étape 6, § 5, § 6, EXT-05).

plan-import : télécharge (borné), inspecte l'archive, vérifie la licence dans son texte, cherche d'abord dans le
registre interne, puis écrit un plan conforme à schemas/external-import.schema.json avec la décision justifiée.
import : rejoue la vérification (même archive à l'octet, même verdict), puis écrit de façon transactionnelle :
binaires adressés par SHA-256 (déduplication physique), archive d'origine, texte de licence, fiches et identités.
Relancé, il ne crée rien (identité : fournisseur, pack, version source, SHA-256 du fichier).
"""

import json
import re
import tempfile
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from tools import asset_versions
from tools.core.catalog import Catalogue, CatalogueScopeError, InvalidJSON, read_json, write_json
from tools.core.exit_codes import ExitCode
from tools.core.ids import IdRegistry
from tools.core.schemas import schemas
from tools.discovery.formats import inspect
from tools.discovery.scan import directory_lock
from tools.external.adapters import ProviderUnavailable, providers
from tools.external.archive import inspect_archive, quarantine
from tools.external.decision import decide
from tools.external.download import DownloadError, DownloadManager
from tools.external.licenses import POLICY, LicenseEvaluator
from tools.publish.delivery import check_destination, put

STORE = PurePosixPath("sources", "external")


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _download(root, adapter, candidate, folder):
    archive = Path(folder) / "pack.zip"
    meta = adapter.download(candidate.externalId, archive, DownloadManager())
    return archive, meta


def _declared(candidate):
    """Licence(s) annoncée(s) par la source : une liste quand elle en offre plusieurs au choix (EXT-08/09)."""
    return list(candidate.licenseOptions) if len(candidate.licenseOptions) > 1 else candidate.licenseSpdx


def _internal(root, query):
    from tools.index.search import search

    words = re.findall(r"[^\W_]+", query)
    if not words:
        return []
    code, payload = search(root, Namespace(query=" ".join(words[:6]), similar_to=None, limit=None, receipt=None,
                                           dry_run=True, **{name: None for name in (
                                               "tag", "universe", "orientation", "state", "license", "used_by",
                                               "category", "family")}))
    return payload.get("results", []) if code == ExitCode.OK else []


def plan(root, args):
    adapter = providers(root).get(args.provider)
    if adapter is None:
        return ExitCode.USAGE, {"ok": False, "error": "unknown-provider", "provider": args.provider}
    try:
        candidate = adapter.inspect(args.id)
    except KeyError:
        return ExitCode.CHECK_FAILED, {"ok": False, "error": "not-found", "provider": args.provider, "id": args.id}
    with tempfile.TemporaryDirectory(prefix="assetctl-external-") as folder:
        try:
            archive, meta = _download(root, adapter, candidate, folder)
        except (ProviderUnavailable, DownloadError) as exc:
            return ExitCode.IO, {"ok": False, "error": "provider-unavailable", "externalSearchStatus": "unavailable",
                                 "message": str(exc)}
        report = inspect_archive(archive)
        if not report["ok"]:
            result = {"ok": False, "error": "unsafe-archive", "problems": report["problems"],
                      "archiveSha256": meta["sha256"]}
            if not args.dry_run:
                result["quarantine"] = quarantine(root, archive, meta["sha256"], result)
            return ExitCode.SAFETY, result
    evaluator = LicenseEvaluator()
    verdict = evaluator.verify(_declared(candidate), report["texts"])
    target = getattr(args, "target", None) or "private"
    decision = decide(_internal(root, candidate.title), [candidate], "available", target,
                      lambda _c: evaluator.for_target(verdict, target))
    contract = {
        "schemaVersion": "1.0", "jobType": "external-library-import", "provider": candidate.provider,
        "externalPackId": candidate.externalId, "sourceUrl": candidate.sourceUrl, "downloadUrl": candidate.downloadUrl,
        "sourceVersion": candidate.sourceVersion or f"sha256:{meta['sha256'][:16]}",
        "archiveSha256": meta["sha256"], "observedAt": now(),
        "license": {"spdxId": verdict["spdx"] if verdict["status"] == "verified" else (candidate.licenseSpdx or "unknown"),
                    "verification": verdict["status"], "evidenceUrl": candidate.licenseEvidenceUrl,
                    "evidence": verdict["evidence"]},
        "policy": {"allowDownload": True, "publishOnlyVerified": True, "preserveOriginalArchive": True,
                   "detectDuplicates": True, "dryRun": bool(args.dry_run)},
        "files": [{"path": row["path"], "sha256": row["sha256"], "format": row["format"]} for row in report["media"]],
        "decision": decision,
    }
    _check_contract(contract)
    if getattr(args, "out", None):
        write_json(args.out, contract)
    return ExitCode.OK, {"ok": True, "plan": contract}


def _check_contract(contract):
    error = next(schemas().validator("external-import").iter_errors(contract), None)
    if error:
        raise InvalidJSON(f"Plan d'import invalide : {error.message}")


def _slug(text):
    words = re.findall(r"[a-z0-9]+", text.casefold())
    return "-".join(words)[:32].strip("-") or "ressource"


def execute(root, args):
    contract = read_json(args.plan)
    _check_contract(contract)
    decision = contract.get("decision") or {}
    if decision.get("action") != "import":
        return ExitCode.SAFETY, {"ok": False, "error": "decision-not-import", "decision": decision.get("action"),
                                 "message": "La décision du plan n'est pas « import » : rien n'est importé."}
    adapter = providers(root).get(contract["provider"])
    if adapter is None:
        return ExitCode.USAGE, {"ok": False, "error": "unknown-provider"}
    try:
        candidate = adapter.inspect(contract["externalPackId"])
    except KeyError:
        return ExitCode.CHECK_FAILED, {"ok": False, "error": "not-found"}
    except ProviderUnavailable as exc:
        return ExitCode.IO, {"ok": False, "error": "provider-unavailable", "message": str(exc)}
    with tempfile.TemporaryDirectory(prefix="assetctl-external-") as folder:
        try:
            archive, meta = _download(root, adapter, candidate, folder)
        except (ProviderUnavailable, DownloadError) as exc:
            return ExitCode.IO, {"ok": False, "error": "provider-unavailable", "message": str(exc)}
        if meta["sha256"] != contract["archiveSha256"]:
            return ExitCode.VERSION_CONFLICT, {"ok": False, "error": "archive-changed",
                                               "message": "L'archive diffère de celle du plan : refaire plan-import."}
        report = inspect_archive(archive)
        if not report["ok"]:
            return ExitCode.SAFETY, {"ok": False, "error": "unsafe-archive", "problems": report["problems"]}
        verdict = LicenseEvaluator().verify(_declared(candidate), report["texts"])
        if verdict["status"] != contract["license"]["verification"]:
            return ExitCode.VERSION_CONFLICT, {"ok": False, "error": "license-changed"}
        raw_archive = archive.read_bytes()
        import zipfile
        with zipfile.ZipFile(archive) as zipped:
            payloads = {row["path"]: zipped.read(row["path"]) for row in report["media"]}
    with directory_lock(root / "catalog"):
        return _write(root, contract, candidate, verdict, report, raw_archive, payloads, args.dry_run)


def _write(root, contract, candidate, verdict, report, raw_archive, payloads, dry_run):
    catalogue = Catalogue(root)
    ids_path = catalogue._regular_path(catalogue.path / "ids.json")
    ids = IdRegistry(catalogue.read(ids_path))
    time = now()
    verified = verdict["status"] == "verified"
    rules = POLICY.get(verdict["spdx"], {}) if verified else {}
    archive_path = STORE / "archives" / f"{contract['archiveSha256']}.zip"
    license_text = None
    if verified:
        license_text = STORE / "licenses" / f"{contract['archiveSha256']}.txt"
    restrictions = []
    if not verified:
        restrictions.append("licence non vérifiée : aucune redistribution publique")
    elif rules.get("copyleft"):
        restrictions.append(f"{verdict['spdx']} copyleft : redistribution publique soumise à revue")
    if rules.get("attribution"):
        restrictions.append("attribution requise (THIRD_PARTY_ASSETS.md à chaque export public)")
    records, writes, created = [], {}, []
    for row in report["media"]:
        key = (f"external:{contract['provider']}:{contract['externalPackId']}:{contract['sourceVersion']}:"
               f"{row['sha256']}")
        raw = payloads[row["path"]]
        measured = inspect(row["path"], raw)
        family = measured.family if measured else {"type": "image"}
        stem = PurePosixPath(row["path"]).stem
        known = key in ids.entries
        asset_id = ids.allouer(key, family["type"].replace("-", ""), _slug(f"{candidate.externalId} {stem}"))
        record_path = catalogue._regular_path(catalogue.path / "assets" / f"{asset_id}.json")
        if known and record_path.exists():
            continue
        binary = STORE / "sha256" / f"{row['sha256']}.{row['format']}"
        evidence = f"{contract['provider']}/{contract['externalPackId']}@{contract['sourceVersion']} : {row['path']}"
        trace = {"method": "proven", "confidence": 1, "evidence": [evidence]}
        heuristic = {"method": "path-tokens", "confidence": 0.4, "evidence": [f"nom du fichier {row['path']}"]}
        asset = {
            "schemaVersion": "1.0", "id": asset_id, "name": stem.replace("_", " ").replace("-", " ").strip() or stem,
            "description": f"Ressource externe {candidate.title} : {row['path']}",
            "category": family["type"].replace("-", ""), "subcategory": None,
            "tags": sorted({*candidate.tags, *re.findall(r"[a-z0-9]+", stem.casefold())}),
            "originUniverse": f"{contract['provider']}-{_slug(candidate.externalId)}", "visualStyle": None,
            "sourceSheetId": None, "sourceRegion": None, "orientation": "unknown", "facing": "unknown", "state": None,
            "dimensions": measured.dimensions if measured else None, "format": row["format"],
            "alpha": measured.alpha if measured else None, "pivot": "unknown",
            "files": {"registry": binary.as_posix(), "locations": []}, "sha256": row["sha256"],
            "provenance": {
                "type": "external", "author": candidate.author or "unknown", "evidence": [evidence],
                "external": {
                    "provider": contract["provider"], "externalPackId": contract["externalPackId"],
                    "sourceVersion": contract["sourceVersion"], "sourceUrl": contract["sourceUrl"],
                    **({"downloadUrl": contract["downloadUrl"]} if contract.get("downloadUrl") else {}),
                    **({"author": candidate.author} if candidate.author else {}),
                    "license": {"spdxId": verdict["spdx"], "status": verdict["status"], "evidence": verdict["evidence"],
                                "evidenceUrl": contract["license"].get("evidenceUrl"),
                                "textPath": license_text.as_posix() if license_text else None,
                                "attribution": bool(rules.get("attribution"))},
                    "observedAt": contract.get("observedAt") or time, "importedAt": time,
                    "archiveSha256": contract["archiveSha256"], "archivePath": archive_path.as_posix(),
                    "pathInArchive": row["path"], "restrictions": restrictions, "sourceStatus": "available",
                    **({"licenseOptions": list(candidate.licenseOptions)} if candidate.licenseOptions else {}),
                    **({"credits": candidate.credits} if candidate.credits else {})}},
            "license": verdict["spdx"] if verified else "unknown",
            "status": "active" if verified else "needs-review", "usages": [], "variants": [],
            "createdAt": time, "updatedAt": time, "family": family,
            "inference": {"family": trace, "format": trace, "sha256": trace, "category": trace,
                          "description": trace, "originUniverse": trace, "tags": heuristic,
                          **({"dimensions": trace} if measured and measured.dimensions else {}),
                          **({"alpha": trace} if measured and measured.alpha is not None else {})},
            "creation": {"importJob": contract},
        }
        if verified:
            asset["licenseEvidence"] = {"method": "external-license-file",
                                        "ref": f"{archive_path.as_posix()}#{verdict['evidence']}",
                                        "decision": f"{verdict['spdx']} confirmée par le texte de licence du pack"}
        if not verified or rules.get("copyleft"):
            asset["publicExport"] = "forbidden"
        if measured is not None and measured.image is not None:
            from tools.index.dedup import fingerprints

            asset["perceptual"] = fingerprints(measured.image)
            asset["inference"]["perceptual"] = trace
        asset_versions.initialize(asset)
        error = next(schemas().validator("asset").iter_errors(asset), None)
        if error:
            raise InvalidJSON(f"Fiche externe invalide ({asset_id}) : {error.message}")
        records.append((record_path, asset))
        writes[root / binary] = raw
        created.append(asset_id)
    if records:
        writes[root / archive_path] = raw_archive
        if license_text:
            writes[root / license_text] = report["texts"][verdict["evidence"]].encode("utf-8")
    result = {"ok": True, "newAssets": len(created), "ids": created, "archive": archive_path.as_posix(),
              "license": verdict, "dryRun": bool(dry_run)}
    for path, raw in writes.items():
        check_destination(path, raw)
    if dry_run or not records:
        return ExitCode.OK, result
    done = []
    try:
        for path, raw in writes.items():
            existed = path.exists()
            put(path, raw)
            if not existed:
                done.append(path)
        for path, asset in records:
            write_json(path, asset)
            done.append(path)
        write_json(ids_path, ids.entries)
    except (OSError, CatalogueScopeError):
        for path in done:
            path.unlink(missing_ok=True)
        raise
    return ExitCode.OK, result
