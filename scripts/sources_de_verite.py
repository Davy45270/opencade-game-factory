#!/usr/bin/env python3
"""ARCH-001 E009 : la registry indexe et relie les sources de vérité sans dupliquer les documents.

Décision (HL-525, amendement E095 et HL-538) : l'usine est un dépôt unique, et le registre d'assets EST le magasin
d'assets voulu. Ses originaux (`originals/sha256/`, `sources/original-sheets/`) ne sont donc pas des copies
orphelines : chacun doit être référencé par une fiche du catalogue qui porte SON empreinte (octets relus) et SON
origine. Les documents de spec, eux, ne sont jamais copiés : le registre des specs ne tient que des références
(dépôt, chemin, commit, sha256).

Écarts rendus (liste vide = conforme) :
  - `original-orphelin`      : fichier du magasin qu'aucune fiche ne cite ;
  - `empreinte-differente`   : la fiche cite le fichier, mais son sha256 n'est pas celui des octets ;
  - `origine-absente`        : la fiche cite le fichier sans origine (dépôt/commit/chemin, ou preuve de provenance) ;
  - `reference-incomplete`   : provenance d'un document de spec sans dépôt, chemin, commit ou sha256 ;
  - `copie-de-document`      : un fichier sous `specs/registry/` qui n'est pas une donnée du registre.

Usage : scripts/sources_de_verite.py [--racine DIR] [--json] ; code 0 conforme, 1 écart.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

RACINE = pathlib.Path(__file__).resolve().parents[1]
# Fichiers de données du registre des specs : fiches SPEC-*, registre d'IDs, journal, file d'import Drive.
DONNEES_SPECS = {".json", ".jsonl"}


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _fiches(dossier: pathlib.Path):
    for f in sorted(dossier.glob("*.json")) if dossier.is_dir() else []:
        yield f, json.loads(f.read_text(encoding="utf-8"))


def _niveaux(racine: pathlib.Path, ecarts: list) -> int:
    """`originals/sha256/<sha>.<ext>` : octets d'un niveau, cités par une observation (dépôt, commit, chemin)."""
    obs: dict[str, list[dict]] = {}
    for _, d in _fiches(racine / "catalog" / "levels"):
        for o in d.get("observations") or []:
            obs.setdefault(o.get("contentSha256"), []).append(o)
    n = 0
    for f in sorted((racine / "originals" / "sha256").glob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        n += 1
        rel = f.relative_to(racine).as_posix()
        nom = f.name.split(".")[0]
        if _sha(f) != nom:
            ecarts.append({"type": "empreinte-differente", "fichier": rel})
        elif nom not in obs:
            ecarts.append({"type": "original-orphelin", "fichier": rel})
        elif not any(o.get("repo") and o.get("commit") and o.get("path") for o in obs[nom]):
            ecarts.append({"type": "origine-absente", "fichier": rel})
    return n


def _planches(racine: pathlib.Path, ecarts: list) -> int:
    """`sources/original-sheets/*` : planches citées par `files.registry` d'une fiche, avec sha256 et origine."""
    cites: dict[str, list[dict]] = {}
    for sous in ("sheets", "assets"):
        for _, d in _fiches(racine / "catalog" / sous):
            r = (d.get("files") or {}).get("registry")
            if r:
                cites.setdefault(r, []).append(d)
    n = 0
    for f in sorted((racine / "sources" / "original-sheets").glob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        n += 1
        rel = f.relative_to(racine).as_posix()
        fiches = cites.get(rel, [])
        if not fiches:
            ecarts.append({"type": "original-orphelin", "fichier": rel})
            continue
        h = _sha(f)
        bonnes = [d for d in fiches if d.get("sha256") == h]
        if not bonnes:
            ecarts.append({"type": "empreinte-differente", "fichier": rel, "fiches": [d.get("id") for d in fiches]})
            continue

        def origine(d: dict) -> bool:
            locs = (d.get("files") or {}).get("locations") or []
            if any(l.get("repo") and l.get("commit") and l.get("path") for l in locs):
                return True
            p = d.get("provenance") or {}
            return bool(p.get("type") and [e for e in p.get("evidence") or [] if str(e).strip()])

        if not any(origine(d) for d in bonnes):
            ecarts.append({"type": "origine-absente", "fichier": rel, "fiches": [d.get("id") for d in bonnes]})
    return n


def _specs(racine: pathlib.Path, ecarts: list) -> int:
    """Registre des specs : des références seulement, jamais une copie de document."""
    reg = racine / "specs" / "registry"
    n = 0
    for f in sorted(reg.rglob("*")) if reg.is_dir() else []:
        if f.is_file() and f.name != ".gitkeep" and f.suffix not in DONNEES_SPECS:
            ecarts.append({"type": "copie-de-document", "fichier": f.relative_to(racine).as_posix()})
    for f, d in ((f, json.loads(f.read_text(encoding="utf-8"))) for f in sorted(reg.rglob("SPEC-*.json"))):
        if not f.name.startswith("SPEC-"):
            continue
        groupes = [(v.get("version"), v.get("documents") or []) for v in d.get("versions") or []]
        groupes.append((None, d.get("unversionedDocuments") or []))
        for version, docs in groupes:
            for doc in docs:
                for p in doc.get("provenances") or []:
                    n += 1
                    if not (p.get("repo") and p.get("path") and p.get("commitSha") and doc.get("sha256")):
                        ecarts.append({"type": "reference-incomplete", "fichier": f.relative_to(racine).as_posix(),
                                       "version": version, "chemin": p.get("path")})
    return n


def mesurer(racine: pathlib.Path = RACINE) -> dict:
    ecarts: list[dict] = []
    compte = {"originauxNiveaux": _niveaux(racine, ecarts), "originauxPlanches": _planches(racine, ecarts),
              "referencesSpecs": _specs(racine, ecarts)}
    return {"compte": compte, "ecarts": ecarts, "conforme": not ecarts}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--racine", type=pathlib.Path, default=RACINE)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = mesurer(a.racine)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"{r['compte']} ; {len(r['ecarts'])} écart(s)")
        for e in r["ecarts"]:
            print(" ", e)
    return 0 if r["conforme"] else 1


if __name__ == "__main__":
    sys.exit(main())
