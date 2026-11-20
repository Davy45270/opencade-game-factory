#!/usr/bin/env python3
"""Planche « détourée » : RGB inchangé, alpha recalé par niveaux (lo -> 0, hi -> 255, linéaire entre).
Le fond (voile, lueurs) tombe à alpha 0 ; l'anticrénelage du contour est conservé.
Puis tout pixel à plus de 4 px du masque objet (alpha recalé >= 128) passe à alpha 0 (poussières, lueur).
Usage : nettoyer.py <planche> <sortie.png> <lo> <hi>"""
import sys
import numpy as np
from PIL import Image, ImageFilter

src, out, lo, hi = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
a = np.asarray(Image.open(src).convert("RGBA")).copy()
al = a[..., 3].astype(np.float64)
al = np.clip((al - lo) / (hi - lo), 0, 1) * 255
a[..., 3] = np.round(al).astype(np.uint8)
obj = Image.fromarray(((a[..., 3] >= 128) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))
a[np.asarray(obj) == 0, 3] = 0
a[a[..., 3] == 0, :3] = 0  # pixels transparents sans couleur résiduelle
Image.fromarray(a, "RGBA").save(out)
