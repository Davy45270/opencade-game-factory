#!/usr/bin/env python3
"""Planche de contrôle : planche détourée aplatie sur damier gris, boîtes de la table en magenta, index en blanc.
Usage : controle.py <planche-detouree.png> <decoupe.json> <sortie.png> [echelle=1.0]"""
import json, sys
from PIL import Image, ImageDraw
P, D, O = sys.argv[1:4]; e = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
im = Image.open(P).convert("RGBA"); W, H = im.size
fond = Image.new("RGBA", im.size, (90, 120, 90, 255))
d0 = ImageDraw.Draw(fond)
for y in range(0, H, 16):
    for x in range(0, W, 16):
        if (x // 16 + y // 16) % 2: d0.rectangle([x, y, x + 15, y + 15], fill=(110, 140, 110, 255))
fond.alpha_composite(im); dr = ImageDraw.Draw(fond)
for i, el in enumerate(json.load(open(D))["elements"]):
    w, h, x, y = el["boite"]; dr.rectangle([x - 1, y - 1, x + w, y + h], outline=(255, 0, 255, 255), width=1)
    dr.text((x + 1, y + h - 10), str(i % 100), fill=(255, 255, 255, 255))
if e != 1.0: fond = fond.resize((int(W * e), int(H * e)), Image.LANCZOS)
fond.convert("RGB").save(O)
