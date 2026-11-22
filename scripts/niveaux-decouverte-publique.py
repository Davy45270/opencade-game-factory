#!/usr/bin/env python3
"""EXT-002 `discover` en CI (E258) : clone en lecture les copies GitHub PUBLIQUES des jeux autorisés
(`catalog/sources.json`, rôle `game`), écrit la portée et lance `assetctl level discover --dry-run`.

Aucun jeton : un dépôt sans copie publique est déclaré `sans-copie-publique` (jamais compté comme découvert).
Sortie : code de `level discover` (0 si 100 % des fichiers classés et sources intactes), rapport JSON sur stdout.

    python3 scripts/niveaux-decouverte-publique.py [--dossier DOSSIER] [--only NOM ...]
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def copies_publiques(only=None):
    sources = json.loads((RACINE / "catalog" / "sources.json").read_text(encoding="utf-8"))["sources"]
    retenues, sans = [], []
    for source in sources:
        if source.get("role") != "game" or (only and source["name"] not in only):
            continue
        copie = next((c for c in source["copies"] if c["provider"] == "github" and c.get("visibility") == "public"),
                     None)
        (retenues if copie else sans).append((source, copie))
    return retenues, [s["name"] for s, _ in sans]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--dossier", type=Path)
    p.add_argument("--only", nargs="*")
    a = p.parse_args(argv)
    retenues, sans = copies_publiques(a.only)
    with tempfile.TemporaryDirectory(prefix="niveaux-") as temporaire:
        dossier = a.dossier or Path(temporaire)
        dossier.mkdir(parents=True, exist_ok=True)
        repos = []
        for source, copie in retenues:
            cible = dossier / source["name"]
            if not cible.exists():
                subprocess.run(["git", "clone", "--quiet", "--depth", "1", copie["url"], str(cible)], check=True,
                               env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin"})
            repos.append({"name": source["name"], "path": source["name"]})
        portee = dossier / "repos.json"
        portee.write_text(json.dumps({"repos": repos}, ensure_ascii=False, indent=2), encoding="utf-8")
        r = subprocess.run([sys.executable, str(RACINE / "assetctl"), "level", "discover", "--scope", str(portee),
                            "--dry-run", "--json"], cwd=RACINE, capture_output=True, text=True)
        try:
            rapport = json.loads(r.stdout)
        except ValueError:
            print(r.stdout[-2000:], r.stderr[-2000:], file=sys.stderr)
            return 7
        resume = {"code": r.returncode, "status": rapport.get("status"), "coverage": rapport.get("coverage"),
                  "sourcesUnchanged": rapport.get("sourcesUnchanged"), "sansCopiePublique": sans,
                  "repos": [{"name": x["name"], "commit": x["commit"], "levels": len(x["levels"]),
                             "exceptions": len(x["exceptions"])} for x in rapport.get("repos", [])],
                  "diagnostics": rapport.get("diagnostics")}
        print(json.dumps(resume, ensure_ascii=False, indent=2))
        return r.returncode


if __name__ == "__main__":
    sys.exit(main())
