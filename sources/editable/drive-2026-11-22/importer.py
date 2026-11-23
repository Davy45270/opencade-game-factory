#!/usr/bin/env python3
"""Import au registre des dessins déposés par David sur le Drive le 2026-11-22 (HL-538) : planches entières, sans découpe.

Licence : CC BY-SA 4.0, attribution « Davy45270 » (décision de David, HL-538 7-3316).
Sources : Drive « Homelab/assets/Pestouille » (planches + un YAML par planche), « assets/coloriages », « coloriages/puzzles ».
Les YAML de David sont des PROPOSITIONS (capacités, attaques, animations) : reprises en preuve, jamais comme faits.
Une planche dont le SHA-256 est déjà au registre n'est pas réimportée (la fiche existante est citée).
Usage : importer.py <racine-registre> <dossier-drive-local>"""
import hashlib, json, subprocess, sys
from pathlib import Path

import yaml

REG, DRIVE = map(Path, sys.argv[1:3])
sys.path.insert(0, str(REG))
from tools.core.catalog import write_json  # noqa: E402

LIC = "CC-BY-SA-4.0"
LIC_PREUVE = {"method": "décision du propriétaire", "ref": "HL-538 7-3316 (remplace 7-3162 et 7-3165)",
              "decision": "Dessins de David : Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0), "
                          "décision du 2026-11-22. Attribution : « Davy45270 ». Texte : LICENSES/CC-BY-SA-4.0.txt."}
AUTEUR = "Davy45270 (dessin fourni par David ; auteur ou outil de création non déclaré)"
CANAUX = {"pestouille": "Drive « Homelab/assets/Pestouille » (dossier 1scASvVoE8lhWVHn6bViMsocWWMrAkJ65)",
          "coloriages": "Drive « assets/coloriages » (dossier 1qDUBpS0Dh0UDDDqdKWPlSvdDhQ90ihQx)",
          "puzzles": "Drive « assets/coloriages/puzzles » (dossier 1Ii87HrWoGcpz18sIZ0h-dmEJYDHNSMOs)"}
TYPES = {"pnj": "personnage RPG (PNJ)", "heros": "personnage RPG (héros)", "monstre": "monstre RPG", "creature": "créature RPG",
         "animal": "animal (compagnon ou élevage)", "batiment": "bâtiment", "planche": "planche de décor"}
# Contenu observé différent du nom de fichier (vérifié à l'œil le 2026-11-22) : le nom du Drive est gardé en preuve.
OBSERVE = {"02_lezards_ecureuil.png": "cochons et sangliers en vitrine de muséum",
           "05_antilopes.png": "coquillages numérotés en vitrine (pas d'antilopes)"}
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()


def ctl(*args):
    r = subprocess.run([str(REG / "assetctl"), *map(str, args), "--json"], cwd=REG, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"assetctl {args[:2]} -> {r.returncode}\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return json.loads(r.stdout)


connus = {}
for p in (REG / "catalog").rglob("*.json"):
    d = json.loads(p.read_text())
    if isinstance(d, dict) and isinstance(d.get("sha256"), str):
        connus.setdefault(d["sha256"].lower(), d["id"])

manifeste = json.loads((DRIVE / "MANIFESTE.json").read_text())
bilan = {"importees": [], "deja_connues": 0, "doublons_drive": []}
vus = {}
for m in sorted(manifeste, key=lambda r: (r["dossier"], r["title"])):
    if not m["title"].endswith(".png"):
        continue
    src = DRIVE / m["dossier"] / m["title"]
    h = sha(src)
    assert h == m["sha256"], src
    if h in vus:
        bilan["doublons_drive"].append(f"{m['dossier']}/{m['title']} = {vus[h]}")
        continue
    vus[h] = f"{m['dossier']}/{m['title']}"
    if h in connus:
        bilan["deja_connues"] += 1
        continue
    stem = m["title"][:-4]
    ev = [f"Dessin fourni par David : {m['title']} · SHA-256 {h}",
          f"Canal : {CANAUX[m['dossier']]}, déposé le 2026-11-22 (Drive id {m['id']}) ; copie locale gelée "
          f"~/sauvegarde-session-hl538/drive-2026-11-22, MANIFESTE.json."]
    if m["dossier"] == "pestouille":
        y = yaml.safe_load((DRIVE / "pestouille" / f"{stem}.yaml").read_text())
        nom = y.get("nom") or stem
        genre = TYPES.get(y.get("type"), y.get("type") or "planche")
        ev.append(f"Métadonnées de David ({stem}.yaml) : type « {y.get('type')} », statut « {y.get('statut')} » ; "
                  f"{y.get('description_visuelle', '')}")
        props = []
        for k in ("role_propose", "habitat_propose", "capacites_ou_interactions_proposees", "attaques_proposees",
                  "animations_recommandees"):
            v = y.get(k)
            if v:
                props.append(f"{k} : {', '.join(map(str, v if isinstance(v, list) else [v]))}")
        if props:
            ev.append("Propositions de David (non validées, à arbitrer en jeu) : " + " ; ".join(props) + ".")
        etiquettes = ["pestouille", genre, "référence artistique (non découpée)"]
    elif m["dossier"] == "coloriages":
        num, _, sujet = stem.partition("_")
        nom = f"Coloriage {num} — {sujet.replace('_', ' ')}"
        etiquettes = ["coloriage", "trait noir sur blanc", "animaux / muséum"]
    else:
        nom = f"Puzzle — {stem.removeprefix('puzzle_').replace('_', ' ')}"
        etiquettes = ["puzzle", "illustration couleur" if "photo" not in stem else "image façon photo"]
    if m["title"] in OBSERVE:
        # Le nom de David est gardé (consigne du coordinateur, 22/11) ; la description fidèle va en preuve.
        ev.append(f"Description fidèle au dessin : {OBSERVE[m['title']]} — le nom du fichier ne correspond pas au dessin.")
    ev.append(f"Étiquettes : {', '.join(etiquettes)}. Statut : référence à découper, pas un sprite de jeu.")
    o = ctl("import-sheet", src)
    p = REG / "catalog" / "sheets" / f"{o['sheetId']}.json"
    f = json.loads(p.read_text())
    f["name"] = nom
    f["license"], f["licenseEvidence"] = LIC, LIC_PREUVE
    f["provenance"] = {"type": "unknown", "author": AUTEUR, "evidence": ev}
    write_json(p, f)
    bilan["importees"].append(o["sheetId"])
print(json.dumps({**bilan, "importees": len(bilan["importees"])}, ensure_ascii=False))
