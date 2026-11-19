"""Décisions de licence fondées sur les documents du commit."""

import re
import unicodedata

from tools import asset_versions
from tools.core.catalog import write_json, write_text
from tools.core.ids import parse_id
from tools.core.schemas import schemas
from tools.discovery.enrich import trace

DAVID_DECISION = "HL-538 condition 3 (David, 2026-11-19)"
DERIVABLE = {"CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "MIT", "Apache-2.0", "ISC", "BSD-2-Clause",
             "BSD-3-Clause", "0BSD", "Unlicense", "Zlib"}


def assign(asset, license_id, method, ref, decision):
    asset["license"] = license_id
    asset["licenseEvidence"] = {"method": method, "ref": ref, "decision": decision}


def explicit_spdx(value):
    return (isinstance(value, str) and value != "unknown"
            and value in schemas().validator("asset").schema["$defs"]["license"]["enum"])


def from_text(raw):
    if raw is None:
        return None
    text = " ".join(raw.decode("utf-8-sig", errors="replace").lower().split())
    # Match distinctive grant or license wording. A title or badge alone is insufficient.
    markers = {
        "MIT": ("permission is hereby granted, free of charge", "to deal in the software without restriction",
                "the software is provided"),
        "Apache-2.0": ("apache license", "version 2.0, january 2004", "terms and conditions for use"),
        "ISC": ("permission to use, copy, modify, and/or distribute this software",
                "with or without fee", "the software is provided"),
        "BSD-3-Clause": ("redistribution and use in source and binary forms", "neither the name",
                         "this software is provided"),
    }
    for license_id, phrases in markers.items():
        if all(phrase in text for phrase in phrases):
            return license_id
    return None


def apply_catalogue(asset, entry, ref):
    for source, field in (("desc", "description"), ("tags", "tags"), ("jeux", "historicalGames"),
                          ("statut", "historicalStatus")):
        value = entry.get(source)
        if field in {"tags", "historicalGames"}:
            value = list(dict.fromkeys(v for v in value if isinstance(v, str) and v.strip())) if isinstance(value, list) else []
        elif not isinstance(value, str) or not value.strip():
            continue
        if value:
            asset[field] = value
            asset["inference"][field] = trace("catalogue-import", 0.9, f"{ref} · {source}")
    author = entry.get("auteur")
    if isinstance(author, str) and author.strip() and asset["provenance"]["type"] in {"repo-file", "generated"}:
        asset["provenance"].update(type="generated", author=author, evidence=[ref])
        model = re.search(r"outil IA\s*\(([^)]+)\)", author, re.I)
        if model:
            asset["provenance"]["model"] = model[1]
        asset["inference"]["provenance"] = trace("catalogue-import", 0.9, f"{ref} · auteur")
    previous_license = asset.get("licenseEvidence")
    if isinstance(previous_license, dict) and previous_license["method"] == "catalogue-import":
        asset["license"] = "unknown"
        asset.pop("licenseEvidence")
    rights = entry.get("droits")
    if isinstance(rights, str):
        normalized = unicodedata.normalize("NFKD", rights).encode("ascii", "ignore").decode().lower()
        if (asset["license"] == "unknown" and "a confirmer" not in normalized
                and re.search(r"\bpublie dans un depot public sous mit\s*\(accord de david\b[^)]*\)", normalized)):
            assign(asset, "MIT", "catalogue-import", ref, rights)


def public_allowed(record, sheet_digests, find_parent):
    """Check the selected revision and each revision it names as a parent."""
    license_id = record.get("license")
    seen = set()
    while True:
        if (record.get("license") != license_id or not explicit_spdx(license_id)
                or not record.get("licenseEvidence") or record.get("publicExport") == "forbidden"
                or record["sha256"].lower() in sheet_digests):
            return False
        provenance = record.get("provenance")
        if not isinstance(provenance, dict) or "parentId" not in provenance:
            return True
        parent_id = provenance["parentId"]
        number = provenance.get("parentVersion")
        digest = provenance.get("parentSha256")
        if not (license_id in DERIVABLE and isinstance(parent_id, str) and parse_id(parent_id)
                and parent_id == provenance.get("derivedFrom")
                and type(number) is int and isinstance(digest, str)):
            return False
        key = parent_id, number
        if key in seen:
            return False
        seen.add(key)
        parent = find_parent(parent_id)
        if parent is None:
            return False
        versions = asset_versions.history(parent)
        if not 1 <= number <= len(versions):
            return False
        entry = versions[number - 1]
        if entry["sha256"].lower() != digest.lower():
            return False
        rights = parent if number == asset_versions.version_number(parent) else entry.get("publication", {})
        record = {**rights, "sha256": entry["sha256"]}


def emit(root, assets, sheets=()):
    assets = {asset["id"]: asset for asset in assets}
    sheets = tuple(sheets)
    sheet_digests = {sheet["sha256"].lower() for sheet in sheets}
    rows = []
    for record in sorted((*assets.values(), *sheets), key=lambda item: item["id"]):
        evidence = record.get("licenseEvidence")
        entire_sheet = record["sha256"].lower() in sheet_digests
        allowed = public_allowed(record, sheet_digests, assets.get)
        reason = ("Planche entière réservée." if entire_sheet else "Licence et preuve enregistrées." if allowed
                  else "Autorisation non établie.")
        rows.append({"id": record["id"], "license": record["license"], "evidence": evidence,
                     "publicExport": "allowed" if allowed else "forbidden",
                     "reason": reason})
    root = root / "generated"
    root.mkdir(exist_ok=True)
    write_json(root / "licenses.json", {"assets": rows})
    markdown = ["# Licences des ressources"]
    if rows:
        markdown.append("")
        markdown.extend(f"- `{row['id']}` — {row['license']} · {row['publicExport']} · {row['reason']}"
                        for row in rows)
    write_text(root / "licenses.md", "\n".join(markdown) + "\n")
    return rows
