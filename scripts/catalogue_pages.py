#!/usr/bin/env python3
"""REG-08 (E108, HL-538) : catalogue statique PRIVÉ du registre, en pages Markdown que la forge rend en HTML.

Pages écrites dans `generated/catalogue/`, refaites depuis le catalogue et rien d'autre (aucune date : la même entrée
donne les mêmes octets) :
  - index.md               : accueil — jeux, sources, planches, licences, avec leurs comptes ;
  - jeux/<jeu>.md          : les assets qu'un jeu emploie (index d'usage), vignette, licence, commits ;
  - sources/<dépôt>.md     : un dépôt de catalog/sources.json, ses jeux et ses assets par licence ;
  - planches/<planche>.md  : une planche (catalog/sheets) et les assets qui en sont découpés ;
  - licences/<licence>.md  : les assets d'une licence, par jeu.
Chaque page renvoie à l'accueil et aux autres pages ; une liste longue est découpée en pages de LOT lignes.

Usage : scripts/catalogue_pages.py [--racine DIR]   écrit les pages (code 0), retire les pages devenues orphelines
        scripts/catalogue_pages.py --check          code 2 si une page est périmée, absente ou en trop (CI)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import defaultdict

RACINE = pathlib.Path(__file__).resolve().parents[1]
SORTIE = pathlib.Path("generated/catalogue")
MARQUE = "<!-- généré par scripts/catalogue_pages.py — ne pas éditer à la main -->"
LOT = 250          # lignes par page de liste
VIGNETTE = 48      # px


def lire(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8"))


def slug(texte: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "--", texte).strip("-") or "sans-nom"


def cellule(texte) -> str:
    return str(texte if texte not in (None, "") else "—").replace("|", "\\|").replace("\n", " ")


class Catalogue:
    def __init__(self, r: pathlib.Path):
        self.r = r
        self.assets = {a["id"]: a for a in map(lire, sorted((r / "catalog/assets").glob("*.json")))}
        self.planches = {s["id"]: s for s in map(lire, sorted((r / "catalog/sheets").glob("*.json")))}
        self.sources = lire(r / "catalog/sources.json").get("sources") or []
        usages = lire(r / "generated/usage-index.json").get("byAsset") or {}
        self.par_jeu = defaultdict(lambda: defaultdict(set))        # jeu → asset → commits (usages actifs)
        for aid, us in usages.items():
            for u in us:
                if u.get("status", "active") == "active" and u.get("game") and aid in self.assets:
                    self.par_jeu[u["game"]][aid].add(u.get("commit") or "")
        self.jeux_de = defaultdict(set)                             # asset → jeux
        for jeu, ids in self.par_jeu.items():
            for aid in ids:
                self.jeux_de[aid].add(jeu)
        self.par_planche = defaultdict(list)
        for a in self.assets.values():
            if a.get("sourceSheetId") in self.planches:
                self.par_planche[a["sourceSheetId"]].append(a["id"])
        self.par_licence = defaultdict(list)
        for a in self.assets.values():
            self.par_licence[a.get("license") or "unknown"].append(a["id"])


def lien_page(depuis: pathlib.PurePosixPath, cible: str) -> str:
    """Lien relatif d'une page de generated/catalogue vers une autre (chemins relatifs au dossier catalogue)."""
    return "../" * (len(depuis.parts) - 1) + cible


def vers_racine(depuis: pathlib.PurePosixPath) -> str:
    return "../" * (len(depuis.parts) + len(SORTIE.parts) - 1)


def entete(page: pathlib.PurePosixPath, titre: str, chemin: list[tuple[str, str]]) -> list[str]:
    fil = " › ".join([f"[Accueil]({lien_page(page, 'index.md')})"] +
                     [f"[{t}]({lien_page(page, c)})" for t, c in chemin])
    return [MARQUE, "", fil, "", f"# {titre}", ""]


def pages_de_liste(base: pathlib.PurePosixPath, titre, chemin, intro, colonnes, lignes):
    """Découpe `lignes` en pages de LOT : base.md, base-2.md… ; navigation entre elles."""
    lots = [lignes[i:i + LOT] for i in range(0, len(lignes), LOT)] or [[]]
    noms = [base.with_name(base.stem + ("" if i == 0 else f"-{i + 1}") + ".md") for i in range(len(lots))]
    for i, (nom, lot) in enumerate(zip(noms, lots)):
        l = entete(nom, titre + (f" (page {i + 1}/{len(lots)})" if len(lots) > 1 else ""), chemin) + intro(nom)
        if len(lots) > 1:
            l += ["Pages : " + " · ".join(f"**{j + 1}**" if j == i else f"[{j + 1}]({n.name})"
                                          for j, n in enumerate(noms)), ""]
        if lot:
            l += ["| " + " | ".join(colonnes) + " |", "|" + "---|" * len(colonnes)]
            l += [ligne(nom) for ligne in lot]
        else:
            l += ["_Aucun asset._"]
        yield nom, l


def ligne_asset(c: Catalogue, aid: str, avec_vignette=True, commits=None):
    def rendu(page):
        a = c.assets[aid]
        r = vers_racine(page)
        fiche = f"[`{aid}`]({r}catalog/assets/{aid}.json)"
        vign = f'<img src="{r}{a["thumbnail"]}" width="{VIGNETTE}" alt="">' if a.get("thumbnail") else "—"
        lic = a.get("license") or "unknown"
        jeux = ", ".join(f"[{j}]({lien_page(page, 'jeux/' + slug(j) + '.md')})" for j in sorted(c.jeux_de.get(aid, ())))
        planche = a.get("sourceSheetId")
        pl = f"[{planche}]({lien_page(page, 'planches/' + slug(planche) + '.md')})" if planche in c.planches else "—"
        cols = ([vign] if avec_vignette else []) + [fiche, cellule(a.get("name")), cellule(a.get("category")),
                                                     f"[{lic}]({lien_page(page, 'licences/' + slug(lic) + '.md')})",
                                                     cellule((a.get("provenance") or {}).get("author"))]
        cols += [", ".join(f"`{s[:7]}`" for s in sorted(commits)) if commits is not None else (jeux or "—"), pl]
        return "| " + " | ".join(cols) + " |"
    return rendu


def construire(r: pathlib.Path) -> dict[pathlib.PurePosixPath, str]:
    c = Catalogue(r)
    pages: dict[pathlib.PurePosixPath, list[str]] = {}
    P = pathlib.PurePosixPath
    cols_jeu = ["Vignette", "Fiche", "Nom", "Catégorie", "Licence", "Auteur", "Commits", "Planche"]
    cols_lic = ["Fiche", "Nom", "Catégorie", "Licence", "Auteur", "Jeux", "Planche"]

    # Jeux
    for jeu in sorted(c.par_jeu):
        ids = c.par_jeu[jeu]
        depot = jeu.split("/", 1)[0]
        lic = defaultdict(int)
        for aid in ids:
            lic[c.assets[aid].get("license") or "unknown"] += 1
        def intro(page, jeu=jeu, depot=depot, ids=ids, lic=lic):
            return [f"Dépôt : [{depot}]({lien_page(page, 'sources/' + slug(depot) + '.md')}) · "
                    f"{len(ids)} asset(s) employés (usages actifs de l'index d'usage)", "",
                    "Licences : " + " · ".join(f"[{k}]({lien_page(page, 'licences/' + slug(k) + '.md')}) {v}"
                                               for k, v in sorted(lic.items())), ""]
        lignes = [ligne_asset(c, aid, True, ids[aid]) for aid in sorted(ids, key=lambda i: (c.assets[i].get("category"), i))]
        pages.update(pages_de_liste(P("jeux") / f"{slug(jeu)}.md", f"Jeu {jeu}", [], intro, cols_jeu, lignes))

    # Sources (dépôts)
    for s in sorted(c.sources, key=lambda s: s["name"]):
        nom = s["name"]
        jeux = sorted(j for j in c.par_jeu if j.split("/", 1)[0] == nom)
        ids = sorted({aid for j in jeux for aid in c.par_jeu[j]})
        page = P("sources") / f"{slug(nom)}.md"
        l = entete(page, f"Source {nom}", [])
        l += [f"Rôle : {s.get('role', '—')}", ""]
        l += ["| Copie | Visibilité |", "|---|---|"] + [f"| {cellule(cp.get('url') or cp.get('path'))} | "
                                                       f"{cellule(cp.get('visibility'))} |" for cp in s.get("copies") or []]
        l += ["", f"## Jeux ({len(jeux)})", ""]
        l += [f"- [{j}]({lien_page(page, 'jeux/' + slug(j) + '.md')}) — {len(c.par_jeu[j])} asset(s)" for j in jeux] or ["_Aucun._"]
        lic = defaultdict(int)
        for aid in ids:
            lic[c.assets[aid].get("license") or "unknown"] += 1
        l += ["", f"## Licences des {len(ids)} asset(s) employés", ""]
        l += [f"- [{k}]({lien_page(page, 'licences/' + slug(k) + '.md')}) : {v}" for k, v in sorted(lic.items())] or ["_Aucun._"]
        pages[page] = l

    # Planches
    for pid in sorted(c.planches):
        p = c.planches[pid]
        ids = sorted(c.par_planche.get(pid, ()))
        locs = (p.get("files") or {}).get("locations") or []
        def intro(page, p=p, locs=locs, ids=ids):
            dims = p.get("dimensions") or {}
            out = [f"Licence : [{p.get('license') or 'unknown'}]"
                   f"({lien_page(page, 'licences/' + slug(p.get('license') or 'unknown') + '.md')}) · "
                   f"auteur : {cellule((p.get('provenance') or {}).get('author'))} · "
                   f"{dims.get('width', '?')}×{dims.get('height', '?')} · SHA-256 `{p.get('sha256', '')[:12]}`", "",
                   f"Fiche : [`{p['id']}`]({vers_racine(page)}catalog/sheets/{p['id']}.json)", ""]
            out += [f"- copie : {cellule(x.get('repo'))} `{cellule(x.get('path'))}`" for x in locs[:5]]
            return out + ["", f"{len(ids)} asset(s) découpés de cette planche.", ""]
        lignes = [ligne_asset(c, aid, True) for aid in ids]
        pages.update(pages_de_liste(P("planches") / f"{slug(pid)}.md", f"Planche {p.get('name') or pid}",
                                    [], intro, ["Vignette"] + cols_lic, lignes))

    # Licences
    for lic in sorted(c.par_licence):
        ids = sorted(c.par_licence[lic], key=lambda i: (",".join(sorted(c.jeux_de.get(i, ()))) or "~", i))
        texte = r / "LICENSES" / f"{lic}.txt"
        def intro(page, lic=lic, ids=ids, texte=texte):
            out = [f"{len(ids)} asset(s) sous `{lic}`."]
            if texte.is_file():
                out += ["", f"Texte : [LICENSES/{lic}.txt]({vers_racine(page)}LICENSES/{lic}.txt)"]
            return out + [""]
        lignes = [ligne_asset(c, aid, False) for aid in ids]
        pages.update(pages_de_liste(P("licences") / f"{slug(lic)}.md", f"Licence {lic}", [], intro, cols_lic, lignes))

    # Accueil
    page = P("index.md")
    l = [MARQUE, "", "# Catalogue du registre d'assets", "",
         f"{len(c.assets)} assets · {len(c.planches)} planches · {len(c.par_jeu)} jeux employant des assets · "
         f"{len(c.sources)} sources · {len(c.par_licence)} licences. Pages générées depuis `catalog/` et "
         "`generated/usage-index.json` par `scripts/catalogue_pages.py` (contrôle CI : `--check`).", "",
         "## Jeux", "", "| Jeu | Assets employés | Source |", "|---|---|---|"]
    l += [f"| [{j}](jeux/{slug(j)}.md) | {len(c.par_jeu[j])} | [{j.split('/', 1)[0]}](sources/{slug(j.split('/', 1)[0])}.md) |"
          for j in sorted(c.par_jeu)]
    l += ["", "## Sources", ""] + [f"- [{s['name']}](sources/{slug(s['name'])}.md) — {s.get('role', '—')}"
                                   for s in sorted(c.sources, key=lambda s: s["name"])]
    l += ["", "## Licences", "", "| Licence | Assets |", "|---|---|"]
    l += [f"| [{k}](licences/{slug(k)}.md) | {len(v)} |" for k, v in sorted(c.par_licence.items())]
    l += ["", f"## Planches ({len(c.planches)})", "", "| Planche | Licence | Assets découpés |", "|---|---|---|"]
    l += [f"| [{cellule(c.planches[p].get('name') or p)}](planches/{slug(p)}.md) | {c.planches[p].get('license') or 'unknown'} | "
          f"{len(c.par_planche.get(p, ()))} |" for p in sorted(c.planches)]
    rapports = sorted((r / "generated/reports").glob("*.md")) + [r / "generated/licenses.md"]
    rapports += sorted((r / "generated/docs").glob("*.md"))
    l += ["", "## Rapports existants", ""]
    l += [f"- [{x.relative_to(r / 'generated').as_posix()}](../{x.relative_to(r / 'generated').as_posix()})"
          for x in rapports if x.is_file()]
    pages[page] = l
    return {k: "\n".join(v).rstrip() + "\n" for k, v in pages.items()}


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    a.add_argument("--racine", type=pathlib.Path, default=RACINE)
    a.add_argument("--check", action="store_true")
    o = a.parse_args(argv)
    r = o.racine.resolve()
    voulu = construire(r)
    dossier = r / SORTIE
    present = {pathlib.PurePosixPath(p.relative_to(dossier).as_posix()) for p in dossier.rglob("*.md")} \
        if dossier.is_dir() else set()
    perimees = sorted((k for k, v in voulu.items()
                      if not (dossier / k).is_file() or (dossier / k).read_text(encoding="utf-8") != v), key=str)
    en_trop = sorted(present - set(voulu), key=str)
    if o.check:
        for k in perimees[:20]:
            print(f"périmée ou absente : {SORTIE / k}", file=sys.stderr)
        for k in en_trop[:20]:
            print(f"en trop : {SORTIE / k}", file=sys.stderr)
        if len(perimees) + len(en_trop) > 40:
            print(f"… {len(perimees)} périmée(s) ou absente(s), {len(en_trop)} en trop", file=sys.stderr)
        if perimees or en_trop:
            print("régénérer : python3 scripts/catalogue_pages.py", file=sys.stderr)
            return 2
        print(f"catalogue à jour : {len(voulu)} pages")
        return 0
    for k in perimees:
        (dossier / k).parent.mkdir(parents=True, exist_ok=True)
        (dossier / k).write_text(voulu[k], encoding="utf-8")
    for k in en_trop:
        if (dossier / k).read_text(encoding="utf-8").startswith(MARQUE):
            (dossier / k).unlink()
    print(json.dumps({"pages": len(voulu), "ecrites": len(perimees), "retirees": len(en_trop)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
