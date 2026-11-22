"""Reçu commun de la politique « reuse before build » (BB-001 § 5, matrice E184).

Chaque étape lancée avec `--receipt <fichier>` y AJOUTE sa trace (`steps`) : 1. `specctl resolve` (par
`bbctl search --project`), 2. `bbctl search --scope internal`, 4. `bbctl evaluate`, 5. `bbctl decide`. Une étape
n'efface jamais celles d'avant ; une résolution impossible est tracée telle quelle, jamais inventée.
"""

import json
import os
import subprocess
from datetime import datetime, timezone

from tools.core.catalog import CatalogueScopeError, write_json


def maintenant():
    return datetime.now(timezone.utc).isoformat()


def verifier_emplacement(receipt, blocks, protected=()):
    target = receipt.resolve()
    for other in protected:
        if target == other.resolve() or (receipt.exists() and other.exists() and receipt.samefile(other)):
            raise CatalogueScopeError("Le reçu ne peut pas remplacer le graphe.")
    if any(target.is_relative_to((blocks / name).resolve()) for name in ("catalog", "decisions", "evaluations")):
        raise CatalogueScopeError("Le reçu doit être placé hors des dossiers de données du registre.")


def lire(receipt):
    if receipt.is_file():
        try:
            data = json.loads(receipt.read_text(encoding="utf-8"))
        except ValueError:
            data = None
        if isinstance(data, dict):
            return data
    return {}


def ajouter(receipt, blocks, steps, extra=None, protected=()):
    verifier_emplacement(receipt, blocks, protected)
    data = lire(receipt)
    data.update(extra or {})
    data["steps"] = [s for s in data.get("steps") or [] if isinstance(s, dict)] + [
        {**s, "at": s.get("at") or maintenant()} for s in steps]
    write_json(receipt, data)


def resoudre(root, project):
    """Étape 1 : `specctl resolve --project` sur le registre de cette usine (USINE_RACINE)."""
    specctl = root / "specctl"
    if not specctl.is_file():
        from tools.core.catalog import ROOT
        specctl = ROOT / "specctl"
    env = {**os.environ, "USINE_RACINE": str(root)}
    try:
        r = subprocess.run([str(specctl), "--json", "resolve", "--project", project], capture_output=True, text=True,
                           env=env, timeout=120)
        v = json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"step": "specctl resolve", "project": project, "status": "source-unavailable",
                "error": exc.__class__.__name__}
    v = v if isinstance(v, dict) else {}
    return {"step": "specctl resolve", "project": project, "code": r.returncode,
            "status": v.get("status") or ("ok" if r.returncode == 0 else f"code-{r.returncode}"),
            "specs": [{"specId": s.get("specId"), "version": s.get("version")} for s in v.get("specs") or []
                      if isinstance(s, dict)],
            "registryDigest": v.get("registryDigest")}
