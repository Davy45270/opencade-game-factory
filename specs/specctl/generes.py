"""Index générés du registre (REG-003 § 3 : `generated/{search-index,dependency-graph,coverage}`) et SBOM de specctl
(§ 9). Les index se reconstruisent depuis les fiches seules : aucun horodatage, aucun chemin de machine, tri stable ;
Git reste la seule histoire qui fait foi. Le SBOM lit les métadonnées des paquets INSTALLÉS (fermeture des dépendances
de specctl), licence comprise ; une licence hors politique est une non-conformité.
"""

import re
import uuid
from importlib import metadata
from urllib.parse import quote

from tools.core.catalog import json_text, write_json
from tools.core.exit_codes import ExitCode

from .commandes import spec_version, tokens

FICHIERS = ("coverage.json", "dependency-graph.json", "search-index.json")
RACINES = ("jsonschema",)          # dépendances directes de specctl (le reste du code n'importe que la stdlib)
POLITIQUE = ("MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "PSF-2.0", "ISC", "MPL-2.0", "Unlicense")
CLASSIFIEURS = {"MIT License": "MIT", "BSD License": "BSD-3-Clause", "Apache Software License": "Apache-2.0",
                "Python Software Foundation License": "PSF-2.0", "ISC License (ISCL)": "ISC",
                "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0"}


def construire(records):
    entries, nodes, edges, coverage = [], [], [], {}
    for spec_id, record in sorted(records.items()):
        entries.append({"id": spec_id, "kind": "spec", "specId": spec_id, "terms": sorted(set(tokens(record["title"])))})
        for row in record["requirements"]:
            entries.append({"id": row["id"], "kind": "requirement", "specId": spec_id,
                            "terms": sorted(set(tokens(row["statement"])))})
        nodes.append({"id": spec_id, "project": record["project"], "version": spec_version(spec_id, records),
                      "lifecycle": record["lifecycle"], "decisions": record.get("decisions", [])})
        edges.extend({"from": spec_id, **relation} for relation in record.get("relations", []))
        rows = [row for row in record["requirements"] if row["matrixStatus"] != "ecartee"]
        proved = [row["id"] for row in rows if row["matrixStatus"] == "faite" and "evidence" in row]
        coverage[spec_id] = {"applicable": len(rows), "proved": len(proved),
                             "ratio": round(len(proved) / len(rows), 4) if rows else None,
                             "withoutEvidence": sorted(row["id"] for row in rows if "evidence" not in row)}
    return {"search-index.json": {"schemaVersion": 1, "entries": entries},
            "dependency-graph.json": {"schemaVersion": 1, "nodes": nodes,
                                      "edges": sorted(edges, key=lambda e: (e["from"], e["type"], e["target"]))},
            "coverage.json": coverage}


def index(records, out, check):
    contenus = {nom: json_text(valeur) for nom, valeur in construire(records).items()}
    if check:
        stale = sorted(nom for nom, texte in contenus.items()
                       if not (out / nom).is_file() or (out / nom).read_text(encoding="utf-8") != texte)
        return (ExitCode.CHECK_FAILED if stale else ExitCode.OK), {
            "status": "stale" if stale else "ok", "stale": stale, "files": list(FICHIERS)}
    out.mkdir(parents=True, exist_ok=True)
    changed = []
    for nom, texte in contenus.items():
        if not (out / nom).is_file() or (out / nom).read_text(encoding="utf-8") != texte:
            (out / nom).write_text(texte, encoding="utf-8")
            changed.append(nom)
    return ExitCode.OK, {"status": "ok", "files": list(FICHIERS), "changed": changed}


def _nom(texte):
    return re.sub(r"[-_.]+", "-", texte.lower())


def licence(dist):
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    for classifier in meta.get_all("Classifier") or []:
        if classifier.startswith("License :: OSI Approved :: "):
            nom = classifier.rsplit(" :: ", 1)[1]
            if nom in CLASSIFIEURS:
                return CLASSIFIEURS[nom]
    brut = (meta.get("License") or "").strip()
    return brut if brut and "\n" not in brut and len(brut) < 64 else "UNKNOWN"


def fermeture():
    vus, pile = {}, list(RACINES)
    while pile:
        nom = _nom(pile.pop())
        if nom in vus:
            continue
        try:
            dist = metadata.distribution(nom)
        except metadata.PackageNotFoundError:
            continue
        vus[nom] = dist
        for exigence in dist.requires or []:
            if "extra ==" in exigence:
                continue
            match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", exigence)
            if match and ";" in exigence:
                marqueur = exigence.split(";", 1)[1]
                if "python_version" in marqueur and "<" in marqueur:
                    continue
            if match:
                pile.append(match[1])
    return vus


def sbom(out, allow, dry_run=False):
    vus = fermeture()
    if not vus:
        return ExitCode.IO, {"status": "source-unavailable", "message": "jsonschema n'est pas installé."}
    politique = set(allow or POLITIQUE)
    composants, violations = [], []
    for nom in sorted(vus):
        dist = vus[nom]
        version = dist.version
        purl = f"pkg:pypi/{nom}@{quote(version, safe='')}"
        lic = licence(dist)
        ids = [part.strip("() ") for part in re.split(r"\s+(?:OR|AND)\s+", lic)]
        if lic == "UNKNOWN" or not any(part in politique for part in ids):
            violations.append({"name": dist.metadata["Name"], "license": lic})
        composants.append({"type": "library", "name": dist.metadata["Name"], "version": version, "purl": purl,
                           "bom-ref": purl, "licenses": [{"expression": lic}]})
    document = {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
                "metadata": {"component": {"name": "specctl", "type": "application", "bom-ref": "specctl"}},
                "components": composants,
                "dependencies": [{"ref": "specctl", "dependsOn": [c["bom-ref"] for c in composants]}]}
    document["serialNumber"] = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, json_text(document))}"
    if not dry_run:
        out.parent.mkdir(parents=True, exist_ok=True)
        write_json(out, document)
    return (ExitCode.CHECK_FAILED if violations else ExitCode.OK), {
        "status": "non-compliant" if violations else "ok", "path": str(out), "components": len(composants),
        "violations": violations, "policy": sorted(politique)}
