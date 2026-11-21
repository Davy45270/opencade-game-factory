"""Découverte open source (BB-001 § 4) : registre officiel et base OSV, métadonnées seulement.

Aucun téléchargement d'archive, aucune exécution de code externe (§ 10) : on lit la recherche du registre, la fiche
JSON de la version exacte (licence, dépôt) et la date de publication, puis les vulnérabilités connues par OSV.
Une source injoignable est une erreur explicite (code 4), jamais un résultat vide ni une valeur inventée (T12).
"""

import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import quote

from tools.core.catalog import json_text, read_json, write_json

from .discover import allocate, slug
from .registry import spdx_ids

NPM = "https://registry.npmjs.org"
OSV = "https://api.osv.dev"
TIMEOUT = 20


class SourceUnavailable(OSError):
    pass


def fetch(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers={"Accept": "application/json",
                                                              "User-Agent": "bbctl (opencade usine)",
                                                              **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise SourceUnavailable(f"{url} : HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
        raise SourceUnavailable(f"{url} : {exc}") from exc


def canonical(url):
    """git+https://github.com/o/r.git → https://github.com/o/r ; une URL non https reste inconnue (None)."""
    if not isinstance(url, str):
        return None
    url = re.sub(r"^git\+", "", url.strip()).removesuffix(".git").rstrip("/")
    url = re.sub(r"^git://", "https://", url)
    url = re.sub(r"^git@github\.com:", "https://github.com/", url)
    return url if url.startswith("https://") else None


def npm_candidates(query, size):
    registry = os.environ.get("BBCTL_NPM_REGISTRY", NPM).rstrip("/")
    osv = os.environ.get("BBCTL_OSV_URL", OSV).rstrip("/")
    found = fetch(f"{registry}/-/v1/search?text={quote(query)}&size={size}") or {}
    candidates = []
    for item in found.get("objects") or []:
        package = item.get("package") or {}
        name, version = package.get("name"), package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            continue
        manifest = fetch(f"{registry}/{quote(name, safe='@')}/{quote(version)}") or {}
        times = (fetch(f"{registry}/{quote(name, safe='@')}") or {}).get("time") or {}
        license_raw = manifest.get("license")
        repository = manifest.get("repository")
        repository = repository.get("url") if isinstance(repository, dict) else repository
        vulns = (fetch(f"{osv}/v1/query", {"package": {"name": name, "ecosystem": "npm"}, "version": version})
                 or {}).get("vulns") or []
        critical = sum(1 for v in vulns if str((v.get("database_specific") or {}).get("severity", "")).upper() == "CRITICAL")
        candidates.append({
            "name": name, "ecosystem": "npm", "version": version,
            "repositoryUrl": canonical(repository) or canonical((package.get("links") or {}).get("repository")),
            "licenseSpdx": license_raw if isinstance(license_raw, str) and license_raw in spdx_ids() else "UNKNOWN",
            "licenseRaw": license_raw if isinstance(license_raw, str) else None,
            "published": times.get(version) if isinstance(times.get(version), str) else None,
            "vulnerabilities": {"count": len(vulns), "critical": critical},
            "source": registry,
        })
    return candidates


def search_opensource(blocks, query, ecosystem, size, record):
    if ecosystem != "npm":
        raise ValueError("Seul l'écosystème npm est branché (registre officiel et OSV).")
    candidates = npm_candidates(query, size)
    written = []
    if record and candidates:
        catalog, ids_path = blocks / "catalog", blocks / "ids.json"
        ids = read_json(ids_path) if ids_path.is_file() else {}
        catalog.mkdir(parents=True, exist_ok=True)
        for c in candidates:
            key = f"npm:{c['name']}@{c['version']}"
            block_id = allocate(ids, key, f"BB-NPM-{slug(c['name'])}")
            target = catalog / f"{block_id}.json"
            if target.is_file():
                written.append(block_id)
                continue                                    # déjà connue (découverte interne ou recherche antérieure)
            write_json(target, {
                "schemaVersion": "1.0", "id": block_id, "name": c["name"], "kind": "external-library",
                "origin": {"repositoryUrl": c["repositoryUrl"], "licenseSpdx": c["licenseSpdx"], "commitSha": None,
                           "version": c["version"]},
                "capabilities": [], "interfaces": [{"language": "javascript", "runtime": "browser"}],
                "specIds": [], "usedBy": [],
                "quality": {"status": "candidate", "sbomRef": None, "securityReportRef": None},
                "decision": {"status": "pending", "rationale": None},
                "provenance": {"discoveredBy": f"bbctl search opensource « {query} »", "verifiedAt": None},
                "discovery": {"key": key, "ecosystem": "npm"},
                "opensource": {"source": c["source"], "published": c["published"], "licenseRaw": c["licenseRaw"],
                               "vulnerabilities": c["vulnerabilities"]},
            })
            written.append(block_id)
        if not ids_path.is_file() or ids_path.read_text(encoding="utf-8") != json_text(dict(sorted(ids.items()))):
            write_json(ids_path, dict(sorted(ids.items())))
    return {"scope": "opensource", "query": query, "candidates": candidates, "recorded": written}
