#!/usr/bin/env python3
"""Mesure du détourage d'un sprite (PNG RGBA), par fichier :
- fond : alpha maximal à plus de 6 px de tout pixel d'alpha >= 64 -> attendu 0 ;
- bordure : liseré extérieur = pixels SEMI-transparents (0 < alpha < 255) touchant un pixel transparent ;
- seuls comptent les pixels de bordure visibles (alpha >= 13, soit > 5 %, critère du runbook) ;
- halo clair : part de la bordure de couleur claire (min RGB > 209, soit > 0,82 comme au runbook) ;
- halo rose : part de la bordure claire ET rosée (min RGB > 170, R - B > 8, R - G > 3).
- halo voile : part de la bordure dont la couleur est à moins de 25 (distance RGB) de la couleur du voile de
  fond de la planche (--voile R,G,B : médiane des pixels de fond de la source) -> le critère.
Code 1 si fond > 0 ou halo voile > seuil (défaut 1 %).
Usage : mesurer-halo.py --voile R,G,B [--seuil 0.01] sprite.png..."""
import sys
import numpy as np
from PIL import Image, ImageFilter

args = sys.argv[1:]
seuil = 0.01
voile = None
while args[:1] in (["--seuil"], ["--voile"]):
    if args[0] == "--seuil":
        seuil = float(args[1])
    else:
        voile = np.array([int(v) for v in args[1].split(",")])
    args = args[2:]
mauvais = 0
for f in args:
    a = np.asarray(Image.open(f).convert("RGBA")).astype(int)
    al = a[..., 3]
    obj = Image.fromarray(((al >= 64) * 255).astype(np.uint8))
    dil = np.asarray(obj.filter(ImageFilter.MaxFilter(13))) > 0
    fond = int(al[~dil].max()) if (~dil).any() else 0
    transp = Image.fromarray(((al == 0) * 255).astype(np.uint8))
    pres = np.asarray(transp.filter(ImageFilter.MaxFilter(3))) > 0
    bord = (al >= 13) & (al < 255) & pres
    rgb = a[..., :3]
    mn = rgb.min(-1)
    clair = bord & (mn > 209)
    rose = bord & (mn > 170) & (rgb[..., 0] - rgb[..., 2] > 8) & (rgb[..., 0] - rgb[..., 1] > 3)
    vl = bord & (np.sqrt(((rgb - voile) ** 2).sum(-1)) < 25)
    n = max(1, int(bord.sum()))
    semi = int(((al > 0) & (al < 255)).sum())
    ok = fond == 0 and vl.sum() / n <= seuil
    mauvais += not ok
    print(f"{f.split('/')[-1]}: fond_alpha_max={fond} bordure={n} semi={semi} "
          f"halo_clair={clair.sum()/n:.4f} halo_rose={rose.sum()/n:.4f} halo_voile={vl.sum()/n:.4f} {'OK' if ok else 'ÉCHEC'}")
print(f"{len(args)-mauvais}/{len(args)} conformes")
sys.exit(1 if mauvais else 0)
