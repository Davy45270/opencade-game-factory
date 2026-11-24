"""Décisions de licence fondées sur les documents du commit."""

import re
import unicodedata

from tools import asset_versions
from tools.core.catalog import write_json, write_text
from tools.core.ids import parse_id
from tools.core.schemas import schemas
from tools.discovery.enrich import trace

DAVID_DECISION = "HL-538 condition 3 (David, 2026-11-19)"
# Les dessins de David sont sous CC BY-SA 4.0 depuis le 2026-11-22 (HL-538 7-3316) : licence libre, publiables partout.
# Seule une licence NON LIBRE (PRIVATE_LICENSES) bloque une publication publique. La licence privée ci-dessous n'est plus
# portée par aucune fiche ; elle reste connue (schéma, test L10) comme exemple de licence non libre.
# Ancien régime (HL-538 7-3162) : jamais publique, sauf à travers un JEU de David qui emploie l'asset.
# Règle centrale unique, sans liste de jeux à tenir : tout dépôt de rôle « game » de catalog/sources.json (le registre
# n'inventorie que les dépôts de David) peut publier ce qu'il emploie. Dérivable sous la même licence, vers un tel jeu.
# Conditions de source de photos tierces (NASA, JPL, MESSENGER ; HL-538 2026-11-22) : ce ne sont pas des licences libres
# et elles exigent un crédit que le registre ne garantit pas ailleurs. Même régime que la licence privée : publiables
# seulement à travers un jeu de David qui les emploie (et affiche leur crédit), jamais dérivables sous une autre licence.
# Le nom PRIVATE_LICENSES est gardé : la barrière P17 (homelab-diag, GARDE_REGISTRE) l'importe.
THIRD_PARTY_GAME_ONLY = frozenset({"LicenseRef-NASA-Media-Usage-Guidelines", "LicenseRef-JPL-Image-Use-Policy",
                                   "LicenseRef-MESSENGER-Usage-Statement"})
PRIVATE_LICENSES = frozenset({"LicenseRef-David-Prive-Tous-Droits-Reserves"}) | THIRD_PARTY_GAME_ONLY
GAME_GRANT = {"ref": "HL-538 (David, 2026-11-21)",
              "decision": "« autorise pour tous mes jeux sans exceptions !!! » : remplace l'autorisation réservée à "
                          "pestouille-rpg (HL-537 7-3167). Restent bloqués : un dépôt public qui n'est pas un jeu de David, "
                          "et la publication d'une planche source brute hors d'un jeu."}
# HL-538 7-3316 : un provenance.json de jeu antérieur au 22/11 qui déclare encore la licence privée de David est
# périmé. La déclaration est remplacée par la décision (CC-BY-SA-4.0, attribution « Davy45270 »).
DAVID_PRIVATE_SUPERSEDED = "LicenseRef-David-Prive-Tous-Droits-Reserves"
DAVID_ATTRIBUTION = "Davy45270"
DAVID_CC_BY_SA = ("CC-BY-SA-4.0", "décision du propriétaire", "HL-538 7-3316 (remplace 7-3162 et 7-3165)",
                  "Dessins de David : Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0), "
                  f"décision du 2026-11-22. Attribution : « {DAVID_ATTRIBUTION} ». Texte : LICENSES/CC-BY-SA-4.0.txt.")
DAVID_FULL_NAME = "David " + "Sevin"  # jamais publié : attribution « Davy45270 » seulement (HL-538, 2026-11-24)


def david_cc_by_sa(ref):
    """Preuve 7-3316 d'un dessin de David ; `ref` garde la trace de la déclaration remplacée."""
    _, _, decision_ref, decision = DAVID_CC_BY_SA
    return {"method": "décision du propriétaire", "ref": f"{decision_ref} ; remplace : {ref}" if ref else decision_ref,
            "decision": decision}


def _sans_nom_complet(noeud):
    if isinstance(noeud, str):
        return noeud.replace(DAVID_FULL_NAME, DAVID_ATTRIBUTION)
    if isinstance(noeud, list):
        return [_sans_nom_complet(v) for v in noeud]
    if isinstance(noeud, dict):
        return {k: _sans_nom_complet(v) for k, v in noeud.items()}
    return noeud


def is_david_drawing(asset):
    """Dessin de David : attribué à Davy45270 (hors icônes dessinées par du code, sous la licence du code), ou licence
    posée par la décision David du 19/11 (`DAVID_DECISION`), que 7-3316 remplace."""
    author = str((asset.get("provenance") or {}).get("author", ""))
    by_code = "dessinées par" in author and ("code" in author or "make-icons" in author)
    evidence = asset.get("licenseEvidence") if isinstance(asset.get("licenseEvidence"), dict) else {}
    return (author.startswith(DAVID_ATTRIBUTION) and not by_code) or evidence.get("decision") == DAVID_DECISION


def david_drawing(asset):
    """HL-538 7-3316 (2026-11-22, arbitrage du 2026-11-24) : TOUS les dessins de David sont CC-BY-SA-4.0, attribués à
    « Davy45270 », jamais à son nom complet. Normalise une fiche en place (versions comprises) et la rend."""
    clean = _sans_nom_complet(asset)
    asset.clear()
    asset.update(clean)
    if not is_david_drawing(asset):
        return asset
    if (asset.get("provenance") or {}).get("author") in (None, "unknown"):
        asset.setdefault("provenance", {})["author"] = DAVID_ATTRIBUTION

    def walk(noeud):
        if isinstance(noeud, dict):
            if noeud.get("license") in ("CC-BY-4.0", DAVID_PRIVATE_SUPERSEDED):
                old = noeud.get("licenseEvidence") if isinstance(noeud.get("licenseEvidence"), dict) else {}
                noeud["license"] = "CC-BY-SA-4.0"
                if "licenseEvidence" in noeud or noeud is asset:
                    noeud["licenseEvidence"] = david_cc_by_sa(old.get("ref"))
            for v in noeud.values():
                walk(v)
        elif isinstance(noeud, list):
            for v in noeud:
                walk(v)
    walk(asset)
    return asset


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


def public_allowed(record, sheet_digests, find_parent, granted=frozenset()):
    """Check the selected revision and each revision it names as a parent.

    `granted` lists the private licenses that the destination (a game of David, GAME_GRANT) may publish."""
    license_id = record.get("license")
    if license_id in PRIVATE_LICENSES and license_id not in granted:
        return False
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
        # Dérivable : licence libre, ou licence privée accordée à la destination (jeu de David). Le texte de la licence
        # privée (LICENSES/, point 4) n'exclut que la dérivation sous une AUTRE licence ; la chaîne entière reste
        # sous la même licence (contrôle ci-dessus). Cas : cadre livré d'atlas, redimensionné d'une découpe brute.
        if not ((license_id in DERIVABLE or license_id in granted) and isinstance(parent_id, str) and parse_id(parent_id)
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
