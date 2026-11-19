"""Décisions de licence fondées sur les documents du commit."""

import re
import unicodedata

from tools.core.catalog import write_json, write_text
from tools.core.schemas import schemas
from tools.discovery.enrich import trace

DAVID_DECISION = "HL-538 condition 3 (David, 2026-11-19)"


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


def emit(root, assets, sheets=()):
    sheets = tuple(sheets)
    sheet_digests = {sheet["sha256"] for sheet in sheets}
    rows = []
    for record in sorted((*assets, *sheets), key=lambda item: item["id"]):
        evidence = record.get("licenseEvidence")
        entire_sheet = record["sha256"] in sheet_digests
        allowed = record["license"] != "unknown" and bool(evidence) and not entire_sheet
        reason = ("Planche entière réservée." if entire_sheet else "Licence et preuve enregistrées." if allowed
                  else "Autorisation non établie.")
        rows.append({"id": record["id"], "license": record["license"], "evidence": evidence,
                     "publicExport": "allowed" if allowed else "forbidden",
                     "reason": reason})
    root = root / "generated"
    root.mkdir(exist_ok=True)
    write_json(root / "licenses.json", {"assets": rows})
    write_text(root / "licenses.md", "# Licences des ressources\n\n" + "\n".join(
        f"- `{row['id']}` — {row['license']} · {row['publicExport']} · {row['reason']}" for row in rows) + "\n")
    return rows
