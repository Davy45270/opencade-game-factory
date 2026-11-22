#!/usr/bin/env python3
"""DOC-001 (ARCH-001 § 9, P1 ; backlog ARCH-14) : documentation générée depuis les sources, PR documentaires
traçables, sans écraser les documents existants.

Six pages dans `generated/docs/`, chacune refaite depuis ses sources et rien d'autre :
  - architecture.md  : carte des modules (CLI de l'usine, dossiers, registres, comptes) ;
  - contrats.md      : contrats transverses versionnés (contracts/index.json) ;
  - adr.md           : décisions d'intégration (docs/integration-decisions/ADR-*.md : statut, date, approbation) ;
  - dependances.md   : carte briques → jeux consommateurs → specs (blocks/catalog, liens REG-003 « specIds ») ;
  - exploitation.md  : manuel d'exploitation des pipelines (.woodpecker/*.yml : rôle, déclencheurs, étapes, rejeu) ;
  - changelog.md     : journal d'audit des registres (specs/registry/journal.jsonl, blocks/journal.jsonl), par jour.

Garde : une page cible qui existe SANS l'en-tête « généré » est un document humain ; il n'est jamais écrasé (code 5).

Usage : scripts/docs_generees.py [--racine DIR]            écrit les pages (code 0)
        scripts/docs_generees.py --check                    code 2 si une page est périmée ou absente (CI)
        scripts/docs_generees.py --pr --remote URL --api URL --depot OWNER/REPO
                                                            branche docs/auto-<sha>, commit des seules pages,
                                                            push, PR dont le corps cite sources et identifiants
                                                            (jeton : DOCS_FORGE_TOKEN ; jamais affiché).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.request

RACINE = pathlib.Path(__file__).resolve().parents[1]
SORTIE = pathlib.Path("generated/docs")
MARQUE = "<!-- généré par scripts/docs_generees.py — ne pas éditer à la main -->"
IDS = re.compile(r"\b(?:SPEC|BB|ADR|REQ)-[A-Z0-9-]*[0-9A-Z]\b")


class Refus(Exception):
    pass


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def entete(titre: str, sources: list[pathlib.Path], racine: pathlib.Path) -> list[str]:
    lignes = [MARQUE, "", f"# {titre}", "", "Sources :"]
    lignes += [f"- `{s.relative_to(racine)}` ({sha(s)})" for s in sources]
    return lignes + [""]


def lire_json(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8"))


def page_contrats(r):
    src = r / "contracts/index.json"
    d = lire_json(src)
    l = entete("Contrats transverses", [src], r)
    l += [f"Règle : {d.get('regle', '')}", "", "| Contrat | Version | Schéma | Versions publiées |", "|---|---|---|---|"]
    for nom, c in sorted(d["contrats"].items()):
        hist = ", ".join(h["version"] for h in c.get("historique", []))
        l.append(f"| {nom} | {c['version']} | `{c['schema']}` | {hist} |")
    return l


def page_adr(r):
    srcs = sorted((r / "docs/integration-decisions").glob("ADR-*.md"))
    l = entete("Décisions d'intégration (ADR)", srcs, r)
    l += ["| ADR | Titre | Statut | Date | Approbation |", "|---|---|---|---|---|"]
    for s in srcs:
        t = s.read_text(encoding="utf-8")
        titre = (re.search(r"^# (.+)$", t, re.M) or [None, s.stem])[1]
        champ = lambda nom: (re.search(rf"\*\*{nom} :\*\*\s*(.+)$", t, re.M) or [None, "—"])[1].strip()  # noqa: E731
        l.append(f"| {s.stem[:8]} | {titre.split('—', 1)[-1].strip()} | {champ('Statut')} | {champ('Date')} | "
                 f"{champ('Approuvée par')} |")
    return l


def page_dependances(r):
    srcs = sorted((r / "blocks/catalog").glob("*.json"))
    empreinte = hashlib.sha256("".join(s.name + sha(s) for s in srcs).encode()).hexdigest()[:12]
    l = entete("Carte des dépendances : briques, jeux, specs", [], r)
    l.insert(l.index("Sources :") + 1, f"- `blocks/catalog/` ({len(srcs)} fiches, {empreinte})")
    par_jeu = {}
    for s in srcs:
        b = lire_json(s)
        for u in b.get("usedBy") or []:
            par_jeu.setdefault(u.split("/")[0], []).append(b)
    for jeu, bs in sorted(par_jeu.items()):
        specs = sorted({x for b in bs for x in b.get("specIds") or []})
        l += [f"## {jeu}", "", f"Specs : {', '.join(specs) or '— (aucun lien REG-003)'}", "",
              "| Brique | Type | Version | Licence | Décision |", "|---|---|---|---|---|"]
        vus = set()
        for b in sorted(bs, key=lambda b: b["id"]):
            if b["id"] in vus:
                continue
            vus.add(b["id"])
            o = b.get("origin") or {}
            l.append(f"| {b['id']} | {b.get('kind', '—')} | {o.get('version') or '—'} | {o.get('licenseSpdx') or '—'} | "
                     f"{(b.get('decision') or {}).get('choice') or (b.get('decision') or {}).get('status') or '—'} |")
        l.append("")
    return l


def page_exploitation(r):
    srcs = sorted((r / ".woodpecker").glob("*.yml"))
    l = entete("Manuel d'exploitation des pipelines", srcs, r)
    for s in srcs:
        t = s.read_text(encoding="utf-8")
        tete = []
        for ligne in t.splitlines():
            if not ligne.startswith("#"):
                break
            tete.append(ligne.lstrip("# ").rstrip())
        rejeu = next((x for x in tete if "ci-local.sh" in x), None)
        etapes = re.findall(r"^  - name: (\S+)", t, re.M) or re.findall(r"^  ([a-z][\w-]*):\s*$", t, re.M)
        evts = sorted(set(re.findall(r"event: \[?([a-z_, ]+)\]?", t) and
                          ", ".join(re.findall(r"event: \[?([a-z_, ]+)\]?", t)).replace(" ", "").split(",")))
        l += [f"## {s.stem}", "", (tete[0] if tete else "—"), "", f"- Déclencheurs : {', '.join(evts) or '—'}",
              f"- Étapes : {', '.join(etapes) or '—'}", f"- Rejeu local : {rejeu.split(':', 1)[-1].strip() if rejeu else '—'}",
              ""]
    return l


def page_changelog(r):
    srcs = [p for p in (r / "specs/registry/journal.jsonl", r / "blocks/journal.jsonl") if p.is_file()]
    par_jour = {}
    for s in srcs:
        for ligne in s.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(ligne)
            except ValueError:
                continue
            ident = e.get("specId") or e.get("blockId") or e.get("repo") or "—"
            par_jour.setdefault(str(e.get("at", ""))[:10], {}).setdefault(e.get("command", "?"), set()).add(ident)
    l = entete("Changelog des registres", srcs, r)
    for jour in sorted(par_jour, reverse=True):
        l += [f"## {jour}", ""]
        for cmd, ids in sorted(par_jour[jour].items()):
            l.append(f"- `{cmd}` : {len(ids)} — {', '.join(sorted(ids)[:12])}{' …' if len(ids) > 12 else ''}")
        l.append("")
    return l


def page_architecture(r):
    clis = [p for p in ("specctl", "bbctl", "assetctl") if (r / p).is_file()]
    srcs = [r / p for p in clis] + [r / "contracts/index.json"]
    l = entete("Architecture de l'usine (carte des modules)", srcs, r)
    comptes = {"fiches de specs": len(list((r / "specs/registry").rglob("SPEC-*.json"))),
               "briques": len(list((r / "blocks/catalog").glob("*.json"))),
               "contrats": len(lire_json(r / "contracts/index.json")["contrats"]),
               "ADR": len(list((r / "docs/integration-decisions").glob("ADR-*.md"))),
               "pipelines": len(list((r / ".woodpecker").glob("*.yml")))}
    role = {"specctl": "REG-003, registre des spécifications (specs/)", "bbctl": "BB-001, briques et réutilisation (blocks/)",
            "assetctl": "registre d'assets et de niveaux (catalog/, tools/)"}
    l += ["| Module | Rôle |", "|---|---|"] + [f"| `{c}` | {role[c]} |" for c in clis] + [""]
    l += ["| Registre | Nombre |", "|---|---|"] + [f"| {k} | {v} |" for k, v in comptes.items()]
    return l


PAGES = {"architecture.md": page_architecture, "contrats.md": page_contrats, "adr.md": page_adr,
         "dependances.md": page_dependances, "exploitation.md": page_exploitation, "changelog.md": page_changelog}


def construire(r: pathlib.Path) -> dict[str, str]:
    return {nom: "\n".join(f(r)).rstrip() + "\n" for nom, f in PAGES.items()}


def ecrire(r: pathlib.Path, pages: dict[str, str]) -> list[str]:
    d = r / SORTIE
    for nom in pages:                                         # garde AVANT toute écriture : rien de partiel
        p = d / nom
        if p.exists() and not p.read_text(encoding="utf-8").startswith(MARQUE):
            raise Refus(f"{p.relative_to(r)} existe sans l'en-tête « généré » : document humain, jamais écrasé")
    d.mkdir(parents=True, exist_ok=True)
    changees = []
    for nom, texte in pages.items():
        p = d / nom
        if not p.exists() or p.read_text(encoding="utf-8") != texte:
            p.write_text(texte, encoding="utf-8")
            changees.append(str(SORTIE / nom))
    return changees


def perimees(r: pathlib.Path, pages: dict[str, str]) -> list[str]:
    return [nom for nom, t in pages.items() if not (r / SORTIE / nom).is_file()
            or (r / SORTIE / nom).read_text(encoding="utf-8") != t]


def git(r, *a):
    return subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True, text=True).stdout.strip()


def corps_pr(r, changees, pages):
    ids = sorted({i for nom in changees for i in IDS.findall(pages[pathlib.Path(nom).name])})
    sources = sorted({ligne for nom in changees for ligne in pages[pathlib.Path(nom).name].splitlines()
                      if ligne.startswith("- `")})
    return "\n".join(["PR documentaire générée par `scripts/docs_generees.py` (ARCH-001 DOC-001, ARCH-14).",
                      f"Commit source : {git(r, 'rev-parse', 'HEAD')}", "", "Pages :"] + [f"- `{c}`" for c in changees]
                     + ["", "Sources :"] + sources + ["", "Identifiants du registre cités : " + (", ".join(ids) or "—")])


def ouvrir_pr(r, remote, api, depot, jeton, base="main"):
    pages = construire(r)
    if not perimees(r, pages):
        return {"status": "a-jour", "pr": None}
    tete = git(r, "rev-parse", "--short=12", "HEAD")
    branche = f"docs/auto-{tete}"
    git(r, "switch", "-q", "-c", branche)
    changees = ecrire(r, pages)
    git(r, "add", "--", *changees)
    corps = corps_pr(r, changees, pages)
    git(r, "commit", "-q", "-m", f"Documentation générée depuis {tete} (DOC-001)", "-m", corps)
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    subprocess.run(["git", "-C", str(r), "push", "-q", remote, f"{branche}:refs/heads/{branche}"], check=True,
                   capture_output=True, env=env)
    req = urllib.request.Request(f"{api}/repos/{depot}/pulls", method="POST",
                                 data=json.dumps({"head": branche, "base": base, "body": corps,
                                                  "title": f"Documentation générée depuis {tete}"}).encode(),
                                 headers={"Content-Type": "application/json", **({"Authorization": f"token {jeton}"}
                                                                                  if jeton else {})})
    with urllib.request.urlopen(req, timeout=30) as rep:
        numero = json.load(rep).get("number")
    return {"status": "pr-ouverte", "pr": numero, "branche": branche, "pages": changees}


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--racine", type=pathlib.Path, default=RACINE)
    a.add_argument("--check", action="store_true")
    a.add_argument("--pr", action="store_true")
    a.add_argument("--remote")
    a.add_argument("--api")
    a.add_argument("--depot")
    o = a.parse_args(argv)
    r = o.racine.resolve()
    try:
        if o.check:
            p = perimees(r, construire(r))
            print(json.dumps({"status": "perimee" if p else "a-jour", "pages": p}, ensure_ascii=False))
            return 2 if p else 0
        if o.pr:
            if not (o.remote and o.api and o.depot):
                a.error("--pr exige --remote, --api et --depot")
            print(json.dumps(ouvrir_pr(r, o.remote, o.api, o.depot, os.environ.get("DOCS_FORGE_TOKEN")), ensure_ascii=False))
            return 0
        print(json.dumps({"status": "ecrit", "pages": ecrire(r, construire(r))}, ensure_ascii=False))
        return 0
    except Refus as e:
        print(json.dumps({"status": "refus", "error": str(e)}, ensure_ascii=False))
        return 5


if __name__ == "__main__":
    sys.exit(main())
