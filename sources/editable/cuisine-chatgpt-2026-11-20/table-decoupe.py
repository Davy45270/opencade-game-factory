#!/usr/bin/env python3
"""Table de découpe d'une planche en grille 4 x 4 (colonnes = angles, rangées = objets), au format de la
recette 1 du runbook (boite = [w, h, x, y]). Chaque boîte est l'union des composantes connexes (alpha >= 128,
aire >= 200 px) dont le centroïde tombe dans la cellule ; un objet en plusieurs morceaux (couverts) est réuni.
Usage : table-decoupe.py <planche-detouree.png> <nom planche> <sha256 planche> <sortie.json>
        <taille> <marge> objet:ancre objet:ancre objet:ancre objet:ancre"""
import json
import re
import sys
import numpy as np
from PIL import Image
import subprocess

P, nom, sha, out, taille, marge = sys.argv[1:7]
objets = [x.split(":") for x in sys.argv[7:]]
H, W = np.asarray(Image.open(P).convert("RGBA")).shape[:2]
cc = subprocess.run(["magick", P, "-alpha", "extract", "-threshold", "50%", "-define", "connected-components:verbose=true",
                     "-define", "connected-components:area-threshold=200", "-connected-components", "8", "null:"],
                    capture_output=True, text=True, check=True).stdout
boites = {}
for m in re.finditer(r"^\s*\d+: (\d+)x(\d+)\+(\d+)\+(\d+) ([\d.]+),([\d.]+) (\d+) (\S+)", cc, re.M):
    w, h, x0, y0 = map(int, m.groups()[:4]); cx, cy = float(m[5]), float(m[6])
    if m[8] in ("gray(0)", "srgb(0,0,0)") or int(m[7]) < 200:
        continue
    x1, y1 = x0 + w, y0 + h
    r, c = int(cy // (H / 4)), int(cx // (W / 4))
    b = boites.get((r, c))
    boites[(r, c)] = (min(b[0], x0), min(b[1], y0), max(b[2], x1), max(b[3], y1)) if b else (x0, y0, x1, y1)
el = []
for r, (obj, ancre) in enumerate(objets):
    for c in range(4):
        x0, y0, x1, y1 = boites[(r, c)]
        el.append({"id": f"cuisine-{obj}-vue-{c+1}", "boite": [x1 - x0, y1 - y0, x0, y0], "ancre": ancre})
assert len(el) == 16 and len(boites) == 16, (len(boites), sorted(boites))
json.dump({"planche": nom, "planche_sha256": sha, "marge": int(marge), "taille": int(taille), "elements": el},
          open(out, "w"), ensure_ascii=False, indent=1)
print(out, len(el), "éléments")
