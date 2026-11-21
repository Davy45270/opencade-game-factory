"""Ouverture d'une PR sur la forge (spec § 5 et § 8 : « ouvre une PR lors d'une synchronisation »).

API Forgejo (compatible Gitea). Le jeton vient de ASSETCTL_FORGEJO_TOKEN ; il n'est jamais écrit
dans un résultat, un journal ou un fichier.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

FORGE_URL = "https://forgejo.pingfr.duckdns.org"
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class ForgeError(OSError):
    pass


def _call(url, token, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"token {token}", "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (OSError, ValueError):
        raise ForgeError("Forge injoignable ou réponse illisible.") from None


def open_pull_request(repo, head, base, title, body, *, forge_url=None, environ=None):
    """Ouvre la PR head → base, ou rend celle qui est déjà ouverte pour cette branche (idempotent)."""
    if not REPO.fullmatch(repo or ""):
        raise ValueError("--forge-repo attend propriétaire/dépôt.")
    token = (os.environ if environ is None else environ).get("ASSETCTL_FORGEJO_TOKEN")
    if not token:
        raise ForgeError("ASSETCTL_FORGEJO_TOKEN absent : PR non ouverte.")
    api = f"{(forge_url or FORGE_URL).rstrip('/')}/api/v1/repos/{repo}/pulls"
    status, created = _call(api, token, "POST", {"head": head, "base": base, "title": title, "body": body})
    if status in (200, 201) and isinstance(created, dict):
        return {"number": created["number"], "url": created.get("html_url"), "created": True}
    if status in (409, 422):
        status, rows = _call(f"{api}?{urllib.parse.urlencode({'state': 'open', 'limit': 50})}", token)
        for row in rows if status == 200 and isinstance(rows, list) else ():
            if (row.get("head") or {}).get("ref") == head and (row.get("base") or {}).get("ref") == base:
                return {"number": row["number"], "url": row.get("html_url"), "created": False}
    raise ForgeError(f"La forge a refusé l'ouverture de la PR (HTTP {status}).")
