#!/usr/bin/env python3
"""Import au registre des 14 planches « Metal Solid » de David (HL-538, 2026-11-22), découpées en cadres par animation.

Par planche : decoupe_ms.py, puis `import-sheet` de la planche de référence (sans marque) et, s'il y a des cadres,
`import-sheet --decoupe` de la planche détourée ; un reçu de recherche (`assetctl search`) par planche ; métadonnées.
Licence CC BY-SA 4.0, attribution « Davy45270 » (HL-538 7-3316). Étiquettes : run-and-gun, univers/metal-solid,
refonte-a-venir ; aucun lien vers un jeu existant (usage : refontes à venir, aucun jeu n'est démarré).
Idempotent : une planche dont la version importée est déjà au registre (même SHA-256) n'est pas réimportée.
Usage : importer_ms.py <racine-registre> <dossier-planches-drive> <dossier-travail>"""
import hashlib, json, subprocess, sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
from sections import PLANCHES, VARIANTES  # noqa: E402

REG, DRIVE, TRAV = map(Path, sys.argv[1:4])
sys.path.insert(0, str(REG))
from tools.core.catalog import write_json  # noqa: E402

EDIT = "sources/editable/metal-solid-2026-11-22"
LIC = "CC-BY-SA-4.0"
LIC_PREUVE = {"method": "décision du propriétaire", "ref": "HL-538 7-3316 (remplace 7-3162 et 7-3165)",
              "decision": "Dessins de David : Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0), "
                          "décision du 2026-11-22. Attribution : « Davy45270 ». Texte : LICENSES/CC-BY-SA-4.0.txt."}
AUTEUR = "Davy45270 (dessin fourni par David ; auteur ou outil de création non déclaré)"
CANAL = "Drive « Homelab/assets/Metal Solid » (dossier 1EGvSE0aigwfis8cgtEH2hmSlWGocVsEg), déposé le 2026-11-22"
DRIVE_ID = {"01_panda_guerrier.png": "1wEp9VmtJTiPUzpum-ugbKVIyOumXwWKg", "02_kangourou_guerrier.png": "1lylAOxJ8uvQ8lgnoeoEj-p5STCDezNv5",
            "03_dodo_guerrier.png": "15Pv3scEsnfQJtufecNCsBaXJfVmdWgoZ", "04_tank_equipe.png": "1mc1WzhpajBVDVFKvvP7kxlG91X0Vx0lC",
            "05_tank_gabarit_vide.png": "1LjFr6qF6BOKD_ZKiTjJI27y5NnG0CLQD", "06_tank_sans_personnage.png": "1jvSZpWIhL_2ygJCWRY4eRyDvuixIoMpp",
            "07_helicoptere_dodo.png": "1VwJR5wcP-W1qKFFVsHAcPcoLeGdj5e3M", "08_escargots_champignons.png": "138OZUIBWWJ1sigZrISYOffLqfBMmloPA",
            "09_koalas_champignons.png": "1e8cPILJ6aedS8O7apqcqk9wyGDHeaCq-", "10_moineaux_champignons.png": "16idk7Re_IeOLdXaGqJ3d8BeYyjjHfy4a",
            "11_serpents_champignons.png": "1u81xB14PxrQ7Xy5_GO77SSXXTDx5B27c", "12_alligators_champignons.png": "1tiK35IFtHCEXf25ahyKBkfuRSKhzuXYD",
            "13_batiments_jungle.png": "116-p10jksaBVKSx-VvtedjE5ZMpZ8toe", "14_habitations_jungle.png": "1N0opZsLcTeZc8OQmTSEKATSaUpQ69Knu"}
REQUETE = {"ms-panda": "panda", "ms-kangourou": "kangourou", "ms-dodo": "dodo", "ms-tank-equipe": "tank", "ms-tank": "tank",
           "ms-tank-gabarit": "tank", "ms-helico-dodo": "hélicoptère", "ms-escargot": "escargot", "ms-koala": "koala",
           "ms-moineau": "moineau", "ms-serpent": "serpent", "ms-alligator": "alligator",
           "ms-jungle-batiments": "jungle", "ms-jungle-habitations": "cabane"}
ROLE = {"joueur": "personnage joueur", "vehicule": "véhicule joueur", "ennemi": "ennemi", "decor": "décor", "gabarit": "gabarit"}
ETIQUETTES = ["run-and-gun", "univers/metal-solid", "refonte-a-venir"]
STYLE = "pixel art 2D (run-and-gun)"
USAGE = ("Usage possible : refontes à venir d'un jeu de tir à défilement horizontal (run-and-gun 2D pixel art) ; "
         "aucun jeu n'est démarré à partir de ces planches (HL-525 7-3314) et aucune fiche ne les lie à un jeu existant.")
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()


def ctl(*args):
    r = subprocess.run([str(REG / "assetctl"), *map(str, args), "--json"], cwd=REG, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"assetctl {args[:2]} -> {r.returncode}\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return json.loads(r.stdout)


def trace(ev, conf=1, method="proven"):
    return {"method": method, "confidence": conf, "evidence": list(ev)}


connus = {}
for p in (REG / "catalog" / "sheets").glob("*.json"):
    d = json.loads(p.read_text())
    connus[d["sha256"].lower()] = d["id"]
TRAV.mkdir(parents=True, exist_ok=True)
sha_outils = {o: sha(ICI / o) for o in ("decoupe_ms.py", "sections.py", "importer_ms.py")}
bilan = []
for fichier, p in PLANCHES.items():
    src, pre = DRIVE / fichier, p["prefixe"]
    sm, det, table = TRAV / f"{pre}-sans-marque.png", TRAV / f"{pre}-detouree.png", REG / EDIT / f"{pre}.decoupe.json"
    subprocess.run([sys.executable, "-I", str(ICI / "decoupe_ms.py"), str(src), str(sm), str(det), str(table)], check=True)
    t = json.loads(table.read_text())
    h_src, h_sm = sha(src), sha(sm)
    marques = "le bandeau de style en haut à droite" + (" et le logo en haut à gauche" if len(p["marques"]) > 1 else "")
    ev_src = [f"Dessin fourni par David : {fichier} · SHA-256 {h_src}",
              f"Canal : {CANAL} (Drive id {DRIVE_ID[fichier]}) ; copie locale gelée ~/sauvegarde-session-hl538/drive-2026-11-22/metal-solid."]
    ev_marque = (f"Version importée : {marques} portent une marque commerciale tierce ; ces zones sont remises au fond "
                 f"(RGB {t['fond']}) par {EDIT}/decoupe_ms.py (SHA-256 {sha_outils['decoupe_ms.py']}). Le reste du dessin est inchangé ; "
                 f"l'original n'entre pas au registre.")
    feuilles = []
    if h_sm not in connus:
        o = ctl("import-sheet", sm)
        connus[h_sm] = o["sheetId"]
    feuilles.append((connus[h_sm], "reference"))
    if t["elements"]:
        h_det = sha(det)
        if h_det not in connus:
            o = ctl("import-sheet", det, "--decoupe", table)
            connus[h_det] = o["sheetId"]
        feuilles.append((connus[h_det], "detouree"))
    for sid, role in feuilles:
        fp = REG / "catalog" / "sheets" / f"{sid}.json"
        f = json.loads(fp.read_text())
        ev = ev_src + [ev_marque]
        if role == "detouree":
            ev.append(f"Détourage : seuls les cadres de {EDIT}/{table.name} (SHA-256 {sha(table)}) sont gardés ; ailleurs alpha 0 et "
                      "RGB 0 (titres, numéros, nuancier, logo et bandeau ne survivent pas).")
        ev += [f"Étiquettes : {', '.join(ETIQUETTES)}, {ROLE[p['role']]}.", USAGE]
        if p["role"] == "gabarit":
            ev.append("Gabarit vide : les cases du tank d'équipe (mêmes animations que la planche 04) sont à remplir ; aucun cadre à découper.")
        f["name"] = p["sujet"] + (" — planche de référence" if role == "reference" else " — cadres détourés")
        f["license"], f["licenseEvidence"] = LIC, LIC_PREUVE
        f["provenance"] = {"type": "derived", "author": AUTEUR, "tool": "decoupe_ms.py (Pillow, numpy)", "evidence": ev}
        write_json(fp, f)
    if not t["elements"]:
        bilan.append({"planche": fichier, "feuilles": [s for s, _ in feuilles], "cadres": 0})
        continue
    recu_p = TRAV / f"{pre}.recu.json"
    ctl("search", REQUETE[pre], "--receipt", recu_p)
    recu = json.loads(recu_p.read_text())
    noms = {}
    for i in recu.get("results", []):
        a = json.loads((REG / "catalog" / "assets" / f"{i}.json").read_text())
        noms[i] = f"autre dessin ({a.get('name')}, univers {a.get('originUniverse')}) : aucun cadre de {fichier}"
    rows = [{"assetId": i, "reason": noms[i]} for i in recu.get("results", [])]
    elements = {e["id"]: e for e in t["elements"]}
    sid_det = feuilles[-1][0]
    n = 0
    for ap in sorted((REG / "catalog" / "assets").glob("*.json")):
        a = json.loads(ap.read_text())
        if a.get("sourceSheetId") != sid_det:
            continue
        e = elements[a["family"]["sprite"]["frameName"]]
        anim, decor = e["animation"], p["role"] == "decor"
        variante = VARIANTES.get(pre, [None] * 99)[e["cadre"] - 1] if anim == "variantes" else None
        if anim == "portrait":
            tete = f"{p['sujet']} — portrait (illustration grand format)"
        elif decor:
            tete = f"{p['sujet']} — {e['libelle']} — élément {e['cadre']}/{e['cadres']}"
        elif variante:
            tete = f"{p['sujet']} — variante {variante} ({e['libelle']}) — {e['cadre']}/{e['cadres']}"
        else:
            tete = f"{p['sujet']} — {e['libelle']} — cadre {e['cadre']}/{e['cadres']}"
        a["description"] = tete
        a["state"] = anim
        a["category"] = "environments" if decor else "sprite"
        a["visualStyle"] = STYLE
        a["tags"] = list(dict.fromkeys(ETIQUETTES + [ROLE[p["role"]], REQUETE[pre], anim] + ([variante] if variante else [])))
        a["orientation"], a["facing"] = ("unknown", None) if decor else ("right", "east")
        a["originUniverse"] = "metal-solid"
        ev_table = f"{EDIT}/{table.name} · SHA-256 {sha(table)} · élément {e['id']}"
        lu = f"{fichier} · libellé lu sur la planche : « {e['libelle']} »"
        for champ in ("description", "state", "tags", "category"):
            a.setdefault("inference", {})[champ] = trace([lu, ev_table])
        a["inference"]["orientation"] = trace([f"{fichier} · cadres tournés vers la droite sur la planche"] if not decor
                                              else [f"{fichier} · élément de décor sans orientation"], 0.9, "heuristic")
        a["inference"]["facing"] = a["inference"]["orientation"]
        a["inference"]["originUniverse"] = trace([f"{fichier} · logo « Metal Solid » de la planche, dossier Drive « Metal Solid »"])
        a["license"], a["licenseEvidence"] = LIC, LIC_PREUVE
        a["provenance"]["author"] = AUTEUR
        a["provenance"]["type"] = "original-sheet-cut"
        a["provenance"]["evidence"] = [a["provenance"]["evidence"][0], *ev_src,
                                       "Licence décidée par David le 2026-11-22 (HL-538 7-3316) : CC BY-SA 4.0, attribution « Davy45270 ».",
                                       USAGE]
        a["creation"] = {"searchReceipt": {**recu, "rejectedCandidates": rows}, "rejectedCandidates": rows}
        write_json(ap, a)
        n += 1
    bilan.append({"planche": fichier, "feuilles": [s for s, _ in feuilles], "cadres": n, "constats": t["constats"]})
print(json.dumps(bilan, ensure_ascii=False))
