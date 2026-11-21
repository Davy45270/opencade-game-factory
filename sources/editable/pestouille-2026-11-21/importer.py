#!/usr/bin/env python3
"""Import Pestouille au registre (HL-538, 2026-11-21) : découpe, import-sheet, puis métadonnées.
Usage : importer.py <racine-registre> <dossier-drive> <dossier-planches-docs> <dossier-recus> <dossier-travail>"""
import hashlib, json, shutil, subprocess, sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import manifeste as M

REG, DRIVE, DOCS, RECUS, TRAV = map(Path, sys.argv[1:6])
sys.path.insert(0, str(REG))
from tools.core.catalog import write_json, json_text  # noqa: E402

LIC = "LicenseRef-David-Prive-Tous-Droits-Reserves"
LIC_PREUVE = {"method": "décision du propriétaire", "ref": "HL-538 7-3162",
              "decision": "Dessins de Pestouille fournis par David (héros, créatures, variantes) : privé, tous droits réservés. "
                          "Utilisables dans les jeux de David, jamais exposés publiquement sans son accord."}
AUTEUR = "David (dessin fourni par David ; auteur ou outil de création non déclaré)"
EDIT = "sources/editable/pestouille-2026-11-21"
DIRS = {"droite": ("right", "east", "droite"), "gauche": ("left", "west", "gauche"),
        "bas": ("front", "south", "bas (face)"), "haut": ("back", "north", "haut (dos)")}
PLANCHE19 = {"pestouille-face": ("front", "south", "face"), "pestouille-dos": ("back", "north", "dos"),
             "pestouille-profil-droit": ("right", "east", "profil droit")}
ANIM_FR = {"idle": "repos (idle)", "marche": "marche / vol / nage", "attaque": "attaque", "blesse": "blessé (hurt)"}
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()

def ctl(*args):
    r = subprocess.run([str(REG / "assetctl"), *map(str, args), "--json"], cwd=REG, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"assetctl {args[:2]} -> {r.returncode}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return json.loads(r.stdout)

def trace(method, conf, *ev):
    return {"method": method, "confidence": conf, "evidence": list(ev)}

TRAV.mkdir(parents=True, exist_ok=True)
(REG / EDIT).mkdir(parents=True, exist_ok=True)
for outil in ("decoupe.py", "controle.py", "manifeste.py", "importer.py"):
    shutil.copyfile(ICI / outil, REG / EDIT / outil)
sha_decoupe = sha(REG / EDIT / "decoupe.py")

feuilles = {}   # sheetId -> dict(meta)
elements = {}   # frameName -> (element, meta)
for fichier, prefixe, sujet, famille, gabarit, opts, requete in M.DECOUPEES:
    src = DRIVE / fichier
    det, table = TRAV / f"{prefixe}-detouree.png", REG / EDIT / f"{prefixe}.decoupe.json"
    subprocess.run([sys.executable, "-I", str(REG / EDIT / "decoupe.py"), gabarit, str(src), prefixe, str(det), str(table), *opts],
                   check=True)
    direct = gabarit == "planche19" and "--seuil-alpha" not in opts   # alpha réel conservé tel quel : on découpe l'original
    if direct:
        t = json.loads(table.read_text()); t.update(planche=fichier, planche_sha256=sha(src)); table.write_text(json.dumps(t, ensure_ascii=False, indent=1))
    orig = ctl("import-sheet", src, *(["--decoupe", table] if direct else []))
    meta = dict(fichier=fichier, prefixe=prefixe, sujet=sujet, famille=famille, gabarit=gabarit, requete=requete, opts=opts,
                table=table.name, sha_table=sha(table), sha=sha(src))
    feuilles[orig["sheetId"]] = dict(meta, role="original")
    if not direct:
        d = ctl("import-sheet", det, "--decoupe", table)
        feuilles[d["sheetId"]] = dict(meta, role="detouree", parent=orig["sheetId"], sha_det=sha(det))
    for e in json.loads(table.read_text())["elements"]:
        elements[e["id"]] = (e, meta)
for fichier, sous, sujet, canal, raison in M.SEULES:
    src = (DOCS / fichier) if sous else (DRIVE / fichier)
    o = ctl("import-sheet", src)
    feuilles[o["sheetId"]] = dict(fichier=fichier, sujet=sujet, canal=canal, raison=raison, role="seule", sha=sha(src))

par_fichier = {m["fichier"]: i for i, m in feuilles.items() if m["role"] in ("original", "seule")}
cat = REG / "catalog"
for sid, m in feuilles.items():
    p = cat / "sheets" / f"{sid}.json"; f = json.loads(p.read_text())
    canal = m.get("canal", M.DRIVE)
    ev = [f"Dessin fourni par David : {m['fichier']} · SHA-256 {m['sha']}", f"Canal : {canal}."]
    if m["fichier"] in M.JPEG_DE and m["role"] != "seule":
        j = M.JPEG_DE[m["fichier"]]
        ev.append(f"Même dessin que {par_fichier[j]} ({j}, JPEG Telegram HL-541), en PNG sans perte 1774x887 au lieu de 1280x640 : "
                  f"RMSE {M.RMSE[m['fichier']]} après mise à l'échelle et fond noir (INVENTAIRE du 21/11). Nouvelle source de découpe, le JPEG est conservé.")
        if m["fichier"] in ("pestouille_face.png", "pestouille_dos.png", "pestouille_profil_droit.png"):
            ev.append("Copie identique (même SHA-256) dans homelab-docs/specs/pestouille-rpg-sources/planches/Pestouille_RPG_Animations_*_Drive.png.")
    if m["role"] == "seule":
        ev.append(m["raison"])
        jpg = {v: k for k, v in M.JPEG_DE.items()}.get(m["fichier"])
        if jpg:
            ev.append(f"Version PNG sans perte du même dessin : {par_fichier[jpg]} ({jpg}), d'où sont découpés les cadres.")
    if m["role"] == "detouree":
        ev = [f"Détourage de {m['parent']} ({m['fichier']}, SHA-256 {m['sha']}) par {EDIT}/decoupe.py (SHA-256 {sha_decoupe}), "
              f"gabarit {m['gabarit']}, options {' '.join(m['opts']) or 'aucune'} : fond noir relié au bord des cases -> alpha 0, "
              f"hors cases (titres, cartouches, cadres jaunes, portraits) -> alpha 0 ; RGB inchangé.",
              f"Table de découpe : {EDIT}/{m['table']} (SHA-256 {m['sha_table']}).",
              "La « grille 64x64 » annoncée par le cartouche n'est pas utilisée : pas réel 65 à 72 px (INVENTAIRE du 21/11)."]
        f["provenance"] = {"type": "derived", "author": AUTEUR, "tool": "decoupe.py (Pillow, numpy)", "evidence": ev}
    else:
        f["provenance"] = {"type": "unknown", "author": AUTEUR, "evidence": ev}
    f["name"] = (m["sujet"] + (" — détourée" if m["role"] == "detouree" else ""))
    f["license"], f["licenseEvidence"] = LIC, LIC_PREUVE
    write_json(p, f)

recus = {}
for a_path in sorted((cat / "assets").glob("*.json")):
    a = json.loads(a_path.read_text())
    if a.get("sourceSheetId") not in feuilles:
        continue
    frame = a["family"]["sprite"]["frameName"]
    e, m = elements[frame]
    sujet, ligne, anim = m["sujet"], e.get("ligne", ""), e["animation"]
    if m["prefixe"] in PLANCHE19:
        orient, facing, dir_fr = PLANCHE19[m["prefixe"]]
    elif m["gabarit"] == "variantes":
        orient, facing, dir_fr = ("right", "east", "profil droit")
    else:
        orient, facing, dir_fr = DIRS[ligne]
    variante = ligne if m["gabarit"] == "variantes" else None
    tete = f"{sujet}{' — variante ' + variante if variante else ''} — {dir_fr} — {ANIM_FR[anim]}"
    if "etat" in e:
        a["description"] = f"{tete} : bloc entier À DÉCOUPER ({e['trouves']} plages trouvées pour {e['attendus']} cadres attendus ; effets détachés)"
        a["state"] = "a-decouper"
    else:
        a["description"] = f"{tete} — cadre {e['cadre']}/{e['cadres']}"
        a["state"] = anim
    ev_table = f"{EDIT}/{m['table']} · SHA-256 {m['sha_table']} · élément {frame}"
    tags = ["pestouille", m["famille"], m["requete"], anim, orient] + ([variante] if variante else []) + (["a-decouper"] if "etat" in e else [])
    a["tags"] = list(dict.fromkeys(tags))
    a["orientation"], a["facing"], a["originUniverse"] = orient, facing, "pestouille"
    src_ev = "rangée/colonne lue sur la planche (étiquettes Droite/Gauche/Bas/Haut et Repos/Marche/Attaque/Blessé)" \
        if m["gabarit"] != "planche19" else "nom de fichier donné par David et rangées de la planche (repos 4, marche 6, attaque 6, blessé 3)"
    for champ in ("description", "state", "tags", "orientation", "facing"):
        a.setdefault("inference", {})[champ] = trace("proven" if m["gabarit"] != "planche19" else "path-tokens",
                                                     1 if m["gabarit"] != "planche19" else 0.9, f"{m['fichier']} · {src_ev}", ev_table)
    a["inference"]["originUniverse"] = trace("proven", 1, f"{m['fichier']} · logo « Pestouille » / dossier Drive Homelab/assets/Pestouille")
    a["license"], a["licenseEvidence"] = LIC, LIC_PREUVE
    a["provenance"]["author"] = AUTEUR
    a["provenance"]["type"] = "original-sheet-cut"     # découpe d'une planche fournie par David (comme la cuisine)
    a["provenance"]["evidence"] = [a["provenance"]["evidence"][0],
                                   f"Planche {m['fichier']} (SHA-256 {m['sha']}) fournie par David ; canal : {M.DRIVE}.",
                                   "Licence décidée par David le 2026-11-21 (HL-538 7-3162) : privé, tous droits réservés."]
    q = m["requete"]
    if q not in recus:
        recus[q] = json.loads((RECUS / f"{q}.json").read_text())
    r = recus[q]
    raisons = {i: "robot pâtissier de cuisine (objet de décor), pas le personnage robot « Netoyer X1 »" for i in r["results"]}
    rows = [{"assetId": i, "reason": raisons[i]} for i in r["results"]]
    a["creation"] = {"searchReceipt": {**r, "rejectedCandidates": rows}, "rejectedCandidates": rows}
    write_json(a_path, a)
print(json.dumps({"planches": len(feuilles), "assets": len(elements),
                  "blocs": sorted(k for k, (e, _) in elements.items() if "etat" in e)}, ensure_ascii=False))
