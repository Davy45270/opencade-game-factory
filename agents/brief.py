#!/usr/bin/env python3
"""Gabarit de brief d'agent et garde (ARCH-001 AGENTS_ADDENDUM, REG-003/BB-001 AGENTS.md).

  brief.py rendre --tache <titre>        écrit le squelette d'un brief : une section par règle (agents/regles.json)
  brief.py verifier <brief.md> [--json]  0 si chaque section est présente, non vide et sans « À REMPLIR » ; 1 sinon
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ICI = pathlib.Path(__file__).resolve().parent
A_REMPLIR = "À REMPLIR"


def regles() -> list[dict]:
    return json.loads((ICI / "regles.json").read_text(encoding="utf-8"))["regles"]


def sections() -> list[str]:
    vues: list[str] = []
    for r in regles():
        if r["section"] not in vues:
            vues.append(r["section"])
    return vues


def rendre(tache: str) -> str:
    gabarit = (ICI / "gabarit-brief.md").read_text(encoding="utf-8")
    return gabarit.replace("# Brief d'agent", f"# Brief d'agent : {tache}", 1)


def verifier(texte: str) -> dict:
    corps: dict[str, list[str]] = {}
    courante = None
    for ligne in texte.splitlines():
        if ligne.startswith("## "):
            courante = ligne[3:].strip()
            corps.setdefault(courante, [])
        elif courante is not None:
            corps[courante].append(ligne)
    manquantes = [s for s in sections() if s not in corps]
    vides = [s for s in sections() if s in corps and not any(l.strip() and not l.lstrip().startswith(">")
                                                              for l in corps[s])]
    a_remplir = [s for s in sections() if s in corps and any(A_REMPLIR in l for l in corps[s])]
    return {"ok": not (manquantes or vides or a_remplir), "manquantes": manquantes, "vides": vides, "a_remplir": a_remplir}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="brief.py")
    sp = p.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("rendre")
    r.add_argument("--tache", required=True)
    v = sp.add_parser("verifier")
    v.add_argument("brief")
    v.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "rendre":
        sys.stdout.write(rendre(a.tache))
        return 0
    try:
        texte = pathlib.Path(a.brief).read_text(encoding="utf-8")
    except OSError as e:
        print(f"brief illisible : {e}", file=sys.stderr)
        return 4
    res = verifier(texte)
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        for cle in ("manquantes", "vides", "a_remplir"):
            for s in res[cle]:
                print(f"{cle} : {s}")
        print("brief conforme" if res["ok"] else "brief REFUSÉ")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
