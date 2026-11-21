#!/usr/bin/env python3
"""Cadres LIVRÉS par un jeu à un commit → registre d'assets, avec leurs usages (HL-538, P17 de l'usine).

Un jeu livre ses images en atlas (une image + un JSON à `frames`). Le registre doit connaître chaque cadre livré par
ses PIXELS, et savoir que ce jeu l'emploie à ce commit. Le cadre livré n'est souvent pas la découpe brute de la
planche, mais sa forme normalisée par le jeu (taille, détourage, projection, encodage WebP).

Pour chaque cadre distinct (même empreinte de pixels que la barrière P17), l'outil :
  - réemploie l'asset du registre qui a déjà ces pixels, s'il existe ;
  - sinon l'enregistre avec `assetctl register` et un reçu de recherche (`assetctl search --receipt`) ; chaque
    candidat du reçu est rejeté avec son motif mesuré. La fiche devient `derived` : `derivedFrom` est l'asset brut
    du même élément (table de découpe du jeu). La recette (table au commit, élément, empreinte, sha du jeu,
    paramètres d'encodage) va dans la provenance.
Il enregistre aussi chaque image d'atlas livrée, que le jeu pourra citer dans son assets.lock.json.
Enfin il écrit les usages `<jeu>@<sha>` dans les fiches et lance `assetctl index rebuild`. Il ne matérialise aucun
fichier dans le jeu : les fichiers livrés y sont déjà.

Les usages qu'il a posés pour ce jeu (marque « importer_livre ») sont remplacés à chaque passage. Une seconde passe
au même sha ne change donc rien, et une passe à un nouveau sha déplace les usages (le commit du lock, par exemple).

`--lock FICHIER` écrit en plus le assets.lock.json du jeu (schéma lock 1.0) : une ligne par image d'atlas livrée,
avec `path` = son chemin dans le jeu et `sha256` = ses octets. Le registryCommit est le HEAD du registre, qui doit
être publié (contenu dans origin/main).

Usage : scripts/importer_livre.py <jeu> <sha> [--depot DÉPÔT] [--travail DOSSIER] [--lock FICHIER] [--dry-run]
"""
import argparse, hashlib, json, re, subprocess, sys, tempfile
from pathlib import Path, PurePosixPath

REG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REG))
from tools.core.catalog import write_json  # noqa: E402
from tools.discovery.snapshots import DELIVERED_MARK as MARQUE  # noqa: E402  (le scan garde ces usages)
ASSETCTL = str(REG / "assetctl")

# Profil d'un jeu : où trouver la table de découpe d'un atlas, et la décision de licence de ses dessins bruts.
# Chantier 8 : chaque jeu publié ajoute son profil ici.
PROFILS = {
    "pestouille-rpg": {
        "manifestes": "assets/export/*.manifest.json",      # {source: table, frames: json de l'atlas}
        "prefixe_cadre": "sprite-",                          # cadre « sprite-<élément> » → élément de la table
        "planches": "~/Projets/homelab-docs/specs/pestouille-rpg-sources/planches",
        "univers": "pestouille",
        "licence": "LicenseRef-David-Prive-Tous-Droits-Reserves",
        "licence_preuve": {"method": "décision du propriétaire", "ref": "HL-538 7-3162",
                           "decision": "Dessins de Pestouille fournis par David : privé, tous droits réservés ; "
                                       "publiables à travers tout jeu de David qui les emploie (HL-538, 2026-11-21)."},
        "auteur": "David (dessin fourni par David ; auteur ou outil de création non déclaré)",
    },
}


# --- Empreinte de pixels : MÊME définition que la barrière P17 (homelab-diag arcade-lab/qualite-jeu.py) ---------------

def empreinte_pixels(im):
    """RGBA rogné à la boîte des pixels opaques, RGB des pixels transparents mis à 0, dimensions comprises."""
    import numpy as np
    a = np.asarray(im.convert("RGBA")).copy()
    a[a[..., 3] == 0] = 0
    ys, xs = np.nonzero(a[..., 3])
    if not len(xs):
        return "vide"
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return hashlib.sha256(f"{a.shape[1]}x{a.shape[0]}|".encode() + a.tobytes()).hexdigest()


def cadres_d_atlas(image, frames):
    """[(nom, PIL)] des cadres d'un atlas TexturePacker/Phaser (hash ou tableau ; `rotated` restitué)."""
    items = frames.items() if isinstance(frames, dict) else ((f.get("filename"), f) for f in frames if isinstance(f, dict))
    out = []
    for nom, f in items:
        r = (f or {}).get("frame") or {}
        try:
            x, y, w, h = (int(r[k]) for k in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError):
            continue
        c = image.crop((x, y, x + (h if f.get("rotated") else w), y + (w if f.get("rotated") else h)))
        if f.get("rotated"):
            c = c.rotate(90, expand=True)
        out.append((str(nom), c))
    return out


# --- Outils ------------------------------------------------------------------------------------------------------

def sh(*cmd, cwd=None, ok=(0,)):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode not in ok:
        raise SystemExit(f"{' '.join(map(str, cmd))[:200]} → {r.returncode}\n{r.stdout[-1500:]}\n{r.stderr[-800:]}")
    return r


def assetctl(*args):
    r = sh(ASSETCTL, *args, "--json", cwd=REG)
    return json.loads(r.stdout)


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def lire(p):
    return json.loads(Path(p).read_text())


def ecrire_si_change(p, doc, compte):
    if not Path(p).exists() or lire(p) != doc:
        write_json(Path(p), doc)
        compte["fiches_ecrites"] += 1


def mots(texte):
    return " ".join(re.findall(r"[a-z0-9]+", texte.lower())) or "cadre"


# --- Lecture du jeu au commit ---------------------------------------------------------------------------------------

def cloner(jeu, sha, depot, travail):
    if depot is None:
        sources = lire(REG / "catalog/sources.json")["sources"]
        entree = next((s for s in sources if s["name"] == jeu), None)
        if entree is None:
            raise SystemExit(f"{jeu} absent de catalog/sources.json : dépôt non autorisé.")
        locale = next((c for c in entree.get("copies") or [] if c.get("provider") == "local"), None)
        depot = Path(locale.get("path") or locale.get("url")) if locale else None
        if depot is None:
            raise SystemExit(f"{jeu} : aucune copie locale ; passer --depot.")
    clone = travail / f"{jeu}-{sha[:12]}"
    if not clone.exists():
        sh("git", "clone", "-q", "--no-local", "--no-checkout", str(depot), str(clone))
    complet = sh("git", "rev-parse", "--verify", f"{sha}^{{commit}}", cwd=clone).stdout.strip()
    sh("git", "checkout", "-q", "--force", complet, cwd=clone)
    return clone, complet


def atlas_livres(clone):
    """[{json, image, cadres: [(nom, PIL, empreinte)]}] : même découverte que P17 (tout JSON à `frames` du commit)."""
    from PIL import Image
    fichiers = sh("git", "ls-files", cwd=clone).stdout.split()
    connus, out = set(fichiers), []
    for f in fichiers:
        if not f.endswith(".json") or "node_modules/" in f:
            continue
        try:
            doc = json.loads((clone / f).read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        pages = [doc] if doc.get("frames") else [t for t in doc.get("textures") or [] if isinstance(t, dict)]
        for page in pages:
            nom_img = page.get("image") or (doc.get("meta") or {}).get("image")
            cand = [PurePosixPath(f).parent / nom_img] if nom_img else []
            cand += [PurePosixPath(f).with_suffix(s) for s in (".png", ".webp")]
            img = next((str(c) for c in cand if str(c) in connus), None)
            if img is None or not page.get("frames"):
                continue
            with Image.open(clone / img) as im:
                im.load()
                cadres = [(n, c, empreinte_pixels(c)) for n, c in cadres_d_atlas(im, page["frames"])]
            lignes = (clone / f).read_text().splitlines()
            out.append({"json": f, "image": img, "cadres": cadres,
                        "ligne": {n: next((i + 1 for i, l in enumerate(lignes) if f'"{n}"' in l), 1) for n, _, _ in cadres}})
    return out


# --- Registre ------------------------------------------------------------------------------------------------------

def charger_registre():
    from PIL import Image
    fiches, par_empreinte, par_octets = {}, {}, {}
    for p in sorted((REG / "catalog/assets").glob("*.json")):
        a = lire(p)
        fiches[a["id"]] = a
        par_octets.setdefault(a["sha256"].lower(), []).append(a["id"])
        chemin = (a.get("files") or {}).get("registry")
        if chemin and (REG / chemin).is_file() and a["family"]["type"] in ("sprite", "image"):
            try:
                with Image.open(REG / chemin) as im:
                    par_empreinte.setdefault(empreinte_pixels(im), []).append(a["id"])
            except OSError:
                pass
    return fiches, par_empreinte, par_octets


def tables_des_atlas(clone, profil):
    """{json d'atlas → (chemin de la table, table)} par les manifestes du jeu."""
    out = {}
    for m in sorted(clone.glob(profil["manifestes"])):
        d = lire(m)
        if not d.get("source") or not d.get("frames"):
            continue
        table = clone / d["source"]
        stem = PurePosixPath(d["frames"]).stem
        out[stem] = (d["source"], lire(table), sha256(table.read_bytes()))
    return out


def brut_de(fiches, table_nom, element):
    """Asset brut (découpe de la planche) du même élément de la même table."""
    ids = [i for i, a in fiches.items()
           if ((a.get("family") or {}).get("sprite") or {}).get("frameName") == element
           and str((a.get("sourceRegion") or {}).get("evidence", "")).startswith(
               (f"{table_nom} ·", f"{PurePosixPath(table_nom).stem}.{element}.decoupe.json ·"))
           and a["provenance"]["type"] == "original-sheet-cut"]
    return sorted(ids)[0] if ids else None


def importer_brut(jeu, sha, profil, table_rel, table, element, travail, recu, compte):
    """Élément sans découpe brute au registre : `assetctl import-sheet` sur une table réduite à cet élément (boîte du
    jeu reprise telle quelle, sans redécoupe), puis la fiche reçoit la licence et l'auteur du profil du jeu."""
    planche = Path(profil["planches"]).expanduser() / table["planche"]
    nom = PurePosixPath(table_rel).name
    reduite = {**table, "elements": [e for e in table["elements"] if e["id"] == element],
               "planche_sha256": sha256(planche.read_bytes())}
    copie = REG / "sources/editable" / f"{jeu}-livre" / f"{PurePosixPath(nom).stem}.{element}.decoupe.json"
    copie.parent.mkdir(parents=True, exist_ok=True)
    copie.write_text(json.dumps(reduite, ensure_ascii=False, indent=1) + "\n")
    d = assetctl("import-sheet", str(planche), "--decoupe", str(copie))
    aid = d["assets"][0]["assetId"]
    p = REG / "catalog/assets" / f"{aid}.json"
    a = lire(p)
    ev = f"{jeu}@{sha[:12]}:{table_rel} · élément {element} ; copie {copie.relative_to(REG)} (SHA-256 {sha256(copie.read_bytes())})"
    a["description"] = f"{jeu} — élément « {element} » de la table {nom} (planche {table['planche']}) : découpe brute"
    a["tags"] = list(dict.fromkeys([profil["univers"], jeu, PurePosixPath(nom).stem.split(".")[0]]))
    for champ in ("description", "tags"):
        a.setdefault("inference", {})[champ] = {"method": "proven", "confidence": 1, "evidence": [ev]}
    a["originUniverse"] = profil["univers"]
    a["inference"]["originUniverse"] = {"method": "proven", "confidence": 1, "evidence": [f"{table['planche']} · planche du jeu"]}
    a["license"], a["licenseEvidence"] = profil["licence"], profil["licence_preuve"]
    a["provenance"].update(type="original-sheet-cut", author=profil["auteur"])
    a["provenance"]["evidence"] = [a["provenance"]["evidence"][0], ev]
    rejets = [{"assetId": c, "reason": f"pas la découpe de l'élément {element} de {nom} (autre élément ou autre boîte)"}
              for c in recu["results"]]
    a["creation"] = {"searchReceipt": {**recu, "rejectedCandidates": rejets}, "rejectedCandidates": rejets}
    write_json(p, a)
    compte["bruts_importes"] += 1
    return aid


def recu_motive(requete, jeu, motifs, travail, n):
    """Recherche avec reçu ; chaque candidat reçoit son motif de rejet MESURÉ (rend la liste des --reject)."""
    recu = travail / f"recu-{n}.json"
    assetctl("search", requete, "--tag", jeu, "--receipt", str(recu))
    rejets = []
    for cand in lire(recu)["results"]:
        rejets += ["--reject", f"{cand}:{motifs(cand)}"]
    return recu, rejets


def enregistrer(nom, png, recu, rejets):
    d = assetctl("register", str(png), "--name", nom, "--category", "sprite", "--receipt", str(recu), *rejets)
    return d["id"]


# --- Passe ---------------------------------------------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("jeu")
    ap.add_argument("sha")
    ap.add_argument("--depot", type=Path)
    ap.add_argument("--travail", type=Path)
    ap.add_argument("--lock", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    profil = PROFILS.get(args.jeu)
    if profil is None:
        raise SystemExit(f"{args.jeu} : aucun profil dans PROFILS (table de découpe, licence).")
    travail = args.travail or Path(tempfile.mkdtemp(prefix="importer-livre-"))
    travail.mkdir(parents=True, exist_ok=True)
    clone, sha = cloner(args.jeu, args.sha, args.depot, travail)
    atlas = atlas_livres(clone)
    tables = tables_des_atlas(clone, profil)
    fiches, par_empreinte, par_octets = charger_registre()
    compte = {"atlas": len(atlas), "cadres": sum(len(a["cadres"]) for a in atlas), "cadres_distincts": 0,
              "reemployes": 0, "enregistres": 0, "bruts_importes": 0, "atlas_enregistres": 0,
              "usages": 0, "fiches_ecrites": 0}
    if args.dry_run:
        manquants = {e for a in atlas for _, _, e in a["cadres"] if e not in par_empreinte}
        print(json.dumps({**compte, "a_enregistrer": len(manquants)}, ensure_ascii=False))
        return 0

    # 1. un asset par cadre distinct
    cible, n = {}, 0
    for at in atlas:
        stem = PurePosixPath(at["json"]).stem
        for nom, image, emp in at["cadres"]:
            if emp in cible:
                continue
            if par_empreinte.get(emp):
                # Un atlas d'un seul cadre a les pixels de ce cadre : l'asset du cadre passe avant celui de l'atlas,
                # sinon le second passage déplacerait l'usage (non idempotent).
                cible[emp] = min(par_empreinte[emp], key=lambda i: (fiches[i].get("category") == "atlas", i))
                compte["reemployes"] += 1
                continue
            if stem not in tables:
                raise SystemExit(f"{at['json']} : aucune table de découpe (manifeste) ; parent inconnu.")
            table_rel, table, sha_table = tables[stem]
            table_nom = PurePosixPath(table_rel).name
            element = nom[len(profil["prefixe_cadre"]):] if nom.startswith(profil["prefixe_cadre"]) else nom
            entree = next((e for e in table["elements"] if e["id"] == element), None)
            if entree is None:
                raise SystemExit(f"{at['json']} : cadre {nom} absent de {table_rel}.")
            n += 1
            parent = brut_de(fiches, table_nom, element)
            if parent is None:
                recu_brut, _ = recu_motive(mots(element), args.jeu, lambda c: "", travail, f"brut-{n}")
                parent = importer_brut(args.jeu, sha, profil, table_rel, table, element, travail, lire(recu_brut), compte)
                fiches[parent] = lire(REG / "catalog/assets" / f"{parent}.json")
            png = travail / f"cadre-{n}.png"
            image.save(png, format="PNG")
            region = {k: (fiches[parent].get("sourceRegion") or {}).get(k) for k in ("x", "y", "w", "h")}

            def motif(c, parent=parent):
                if c == parent:
                    return f"découpe brute de l'élément {element} : le jeu livre le cadre normalisé (parent derivedFrom)"
                return f"pixels différents du cadre livré {nom} (empreinte {emp[:12]})"
            recu, rejets = recu_motive(mots(element), args.jeu, motif, travail, n)
            aid = enregistrer(f"{args.jeu} {element} (cadre livré)", png, recu, rejets)
            p = REG / "catalog/assets" / f"{aid}.json"
            a, pa = lire(p), fiches[parent]
            recette = {"table": f"{args.jeu}@{sha}:{table_rel}", "tableSha256": sha_table, "element": element,
                       "boite": entree.get("boite"), "regionDuBrut": region,
                       "parametres": {k: table.get(k) for k in ("taille", "marge", "detoure", "modele", "unique") if k in table},
                       "atlas": f"{at['image']} ({PurePosixPath(at['image']).suffix[1:]})", "cadre": nom,
                       "empreintePixels": emp}
            a["provenance"] = {"type": "derived", "derivedFrom": parent, "parentId": parent,
                               "parentVersion": pa.get("version", 1), "parentSha256": pa["sha256"],
                               "author": pa["provenance"]["author"],
                               "evidence": [f"{MARQUE} : cadre {nom} livré par {args.jeu}@{sha} dans {at['image']}",
                                            "recette " + json.dumps(recette, ensure_ascii=False, sort_keys=True)]}
            a["license"], a["licenseEvidence"] = pa["license"], pa.get("licenseEvidence")
            if a["licenseEvidence"] is None:
                a.pop("licenseEvidence")
            a["description"] = f"{args.jeu} — cadre livré « {nom} » ({at['image']}), forme normalisée par le jeu de l'élément {element}"
            a["tags"] = list(dict.fromkeys([profil["univers"], args.jeu, PurePosixPath(table_nom).stem, "cadre-livre"]))
            ev = f"{args.jeu}@{sha[:12]}:{at['json']} · cadre {nom}"
            for champ in ("description", "tags"):
                a.setdefault("inference", {})[champ] = {"method": "proven", "confidence": 1, "evidence": [ev]}
            if pa.get("originUniverse"):
                a["originUniverse"] = pa["originUniverse"]
                a["inference"]["originUniverse"] = {"method": "proven", "confidence": 1, "evidence": [f"parent {parent}"]}
            write_json(p, a)
            fiches[aid] = a
            if aid not in pa["variants"]:
                pa["variants"] = sorted({*pa["variants"], aid})
                write_json(REG / "catalog/assets" / f"{parent}.json", pa)
            cible[emp] = aid
            par_empreinte.setdefault(emp, []).append(aid)
            compte["enregistres"] += 1
    compte["cadres_distincts"] = len(cible)

    # 2. les images d'atlas livrées (ce que le assets.lock.json du jeu cite)
    atlas_ids = {}
    for at in atlas:
        brut = (clone / at["image"]).read_bytes()
        d = sha256(brut)
        if par_octets.get(d):
            atlas_ids[at["image"]] = sorted(par_octets[d])[0]
            continue
        n += 1
        licences = {fiches[cible[e]]["license"] for _, _, e in at["cadres"]}
        recu, rejets = recu_motive(mots(PurePosixPath(at["image"]).stem + " atlas"), args.jeu,
                                   lambda c: "autre image : octets différents de l'atlas livré", travail, n)
        aid = assetctl("register", str(clone / at["image"]), "--name", f"{args.jeu} atlas {PurePosixPath(at['image']).stem}",
                       "--category", "atlas", "--receipt", str(recu), *rejets)["id"]
        p = REG / "catalog/assets" / f"{aid}.json"
        a = lire(p)
        a["provenance"] = {"type": "repo-file", "author": profil["auteur"],
                           "evidence": [f"{MARQUE} : atlas {at['image']} livré par {args.jeu}@{sha}, cadres de {at['json']}"]}
        if len(licences) == 1:
            unique = next(iter(licences))
            src = next(fiches[cible[e]] for _, _, e in at["cadres"])
            a["license"] = unique
            if src.get("licenseEvidence"):
                a["licenseEvidence"] = src["licenseEvidence"]
        a["description"] = f"{args.jeu} — atlas livré {at['image']} ({len(at['cadres'])} cadres)"
        a["tags"] = [profil["univers"], args.jeu, "atlas-livre"]
        ev = f"{args.jeu}@{sha[:12]}:{at['image']}"
        for champ in ("description", "tags"):
            a.setdefault("inference", {})[champ] = {"method": "proven", "confidence": 1, "evidence": [ev]}
        write_json(p, a)
        fiches[aid] = a
        par_octets.setdefault(d, []).append(aid)
        atlas_ids[at["image"]] = aid
        compte["atlas_enregistres"] += 1

    # 3. usages <jeu>@<sha> : ceux de cet outil pour ce jeu sont remplacés (idempotent, et un nouveau sha les déplace)
    nouveaux = {}
    for at in atlas:
        for nom, _, emp in at["cadres"]:
            aid = cible[emp]
            nouveaux.setdefault(aid, []).append({
                "repo": args.jeu, "game": args.jeu, "provider": "forgejo", "commit": sha, "status": "active",
                "releases": [], "scene": at["json"], "role": "atlas-frame", "importName": nom,
                "assetPath": at["image"], "assetVersion": fiches[aid].get("version", 1),
                "codeRef": {"path": at["json"], "line": at["ligne"][nom]},
                "evidence": [f"{MARQUE} : cadre {nom} de {at['image']} (empreinte de pixels {emp[:16]})"],
                "inference": {"role": {"method": "proven", "confidence": 1, "evidence": [f"{at['json']} · frames"]}}})
        aid = atlas_ids[at["image"]]
        nouveaux.setdefault(aid, []).append({
            "repo": args.jeu, "game": args.jeu, "provider": "forgejo", "commit": sha, "status": "active", "releases": [],
            "scene": at["json"], "role": "atlas", "importName": PurePosixPath(at["image"]).stem,
            "assetPath": at["image"], "assetVersion": fiches[aid].get("version", 1),
            "codeRef": {"path": at["json"], "line": 1},
            "evidence": [f"{MARQUE} : image d'atlas {at['image']} livrée"],
            "inference": {"role": {"method": "proven", "confidence": 1, "evidence": [f"{at['json']} · meta.image"]}}})
    cle = lambda u: (u["scene"], u["importName"], u["assetPath"], u["role"])
    for aid, a in fiches.items():
        anciens = [u for u in a.get("usages") or []
                   if u.get("game") == args.jeu and any(str(e).startswith(MARQUE) for e in u.get("evidence") or [])]
        if not anciens and aid not in nouveaux:
            continue
        garde = [u for u in a.get("usages") or [] if u not in anciens]
        doc = {**a, "usages": garde + sorted(nouveaux.get(aid, []), key=cle)}
        compte["usages"] += len(nouveaux.get(aid, []))
        ecrire_si_change(REG / "catalog/assets" / f"{aid}.json", doc, compte)
    assetctl("index", "rebuild")

    # 4. assets.lock.json du jeu (facultatif) : les images d'atlas livrées, déjà présentes dans le jeu
    if args.lock:
        tete = sh("git", "rev-parse", "HEAD", cwd=REG).stdout.strip()
        publie = sh("git", "merge-base", "--is-ancestor", tete, "origin/main", cwd=REG, ok=(0, 1)).returncode == 0
        if not publie or sh("git", "status", "--porcelain", "--", "catalog", cwd=REG).stdout.strip():
            raise SystemExit("--lock : le catalogue doit être celui d'un commit publié (origin/main), sans modification.")
        lignes = [{"assetId": atlas_ids[at["image"]], "assetVersion": str(fiches[atlas_ids[at["image"]]].get("version", 1)),
                   "sha256": sha256((clone / at["image"]).read_bytes()), "scene": at["json"], "role": "atlas",
                   "path": at["image"]} for at in atlas]
        lock = {"schemaVersion": "1.0", "game": args.jeu, "registryCommit": tete,
                "assets": sorted(lignes, key=lambda r: (r["scene"], r["role"], r["path"], r["assetId"]))}
        write_json(args.lock, lock)
        compte["lock"] = {"fichier": str(args.lock), "lignes": len(lignes), "registryCommit": tete}
    compte["sha"] = sha
    print(json.dumps(compte, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
