#!/usr/bin/env python3
"""Découpe d'une planche « Metal Solid » de David (HL-538, 2026-11-22) en cadres nommés par animation.

Entrées : la planche 1536x1024 (fond uni ~ RGB 19,21,23) et ses sections (sections.py).
Sorties :
  <sortie-sans-marque.png> : la planche entière, zones MARQUES remises au fond (référence lisible, sans marque tierce) ;
  <sortie-detouree.png>    : RGBA, seulement les cadres retenus ; ailleurs alpha 0 ET RGB 0 (rien d'autre ne survit) ;
  <table.decoupe.json>     : éléments {id, boite [w, h, x, y], animation, cadre, cadres, ...} pour `assetctl import-sheet --decoupe`.
Méthode, par section :
  1. masque de premier plan : écart au fond > 26 sur un canal ; exclusions remises au fond ;
  2. lignes de texte retirées : bande de moins de 28 px de haut dont au moins 45 % des pixels sont clairs (min RGB > 100) et peu saturés
     (titre de section en haut, numéros et libellés sous les cadres en bas), d'abord sur toute la section, puis par colonne ;
  3. n cadres attendus : projection des colonnes, petits morceaux (étincelles, poussière) rattachés au voisin le plus proche,
     puis fusion des plus proches ou coupe de la plus large au creux de projection jusqu'à obtenir n ;
     n = None : découpe XY récursive (bandes vides de 3 px), chaque feuille est un élément ;
  4. détourage : fond relié au bord de la boîte (écart <= 9) -> alpha 0 ; les noirs intérieurs du dessin sont gardés.
Usage : decoupe_ms.py <planche.png> <sortie-sans-marque.png> <sortie-detouree.png> <table.decoupe.json>"""
import hashlib, json, sys
from pathlib import Path
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sections import PLANCHES  # noqa: E402

FOND_MASQUE, FOND_DETOURAGE, TEXTE_H = 26, 9, 28
LETTRES = "abcdefghijklmnopqrstuvwxyz"


def runs(v, ecart):
    """Plages [a, b] où v est vrai, séparées par au moins `ecart` faux."""
    idx = np.flatnonzero(v)
    out = []
    for i in idx:
        i = int(i)
        if out and i - out[-1][1] <= ecart:
            out[-1][1] = i
        else:
            out.append([i, i])
    return [tuple(r) for r in out]


def est_texte(rgb, m):
    """Bande de texte : peu haute, pixels de premier plan surtout clairs et peu saturés."""
    if m.shape[0] > TEXTE_H or not m.any():
        return False
    p = rgb[m]
    clair = (p.min(1) > 100) & (p.max(1) - p.min(1) < 50)
    return clair.mean() >= 0.45


def sans_texte(rgb, m):
    """Retire les bandes de texte en haut et en bas ; rend (y0, y1) de ce qui reste, ou None."""
    bandes = runs(m.any(1), 2)
    while bandes and est_texte(rgb[bandes[0][0]:bandes[0][1] + 1], m[bandes[0][0]:bandes[0][1] + 1]):
        bandes.pop(0)
    while bandes and est_texte(rgb[bandes[-1][0]:bandes[-1][1] + 1], m[bandes[-1][0]:bandes[-1][1] + 1]):
        bandes.pop()
    return (bandes[0][0], bandes[-1][1]) if bandes else None


def colonnes(m, n):
    prof = m.sum(0)
    g = [list(r) for r in runs(prof > 0, 3)]
    # petits morceaux (effets détachés) : rattachés au voisin le plus proche
    def poids(r): return int(prof[r[0]:r[1] + 1].sum())
    while len(g) > 1:
        petits = [i for i, r in enumerate(g) if r[1] - r[0] < 14 or poids(r) < 60]
        if not petits or len(g) <= n:
            break
        i = petits[0]
        j = i - 1 if i == len(g) - 1 or (i > 0 and g[i][0] - g[i - 1][1] <= g[i + 1][0] - g[i][1]) else i + 1
        a, b = sorted((i, j))
        g[a] = [g[a][0], g[b][1]]; del g[b]
    while len(g) > n:
        i = min(range(len(g) - 1), key=lambda k: g[k + 1][0] - g[k][1])
        g[i] = [g[i][0], g[i + 1][1]]; del g[i + 1]
    coupes = 0
    while len(g) < n:
        i = max(range(len(g)), key=lambda k: g[k][1] - g[k][0])
        a, b = g[i]; w = b - a
        lo, hi = a + int(w * 0.3), a + int(w * 0.7)
        c = lo + int(np.argmin(prof[lo:hi + 1]))
        g[i:i + 1] = [[a, c], [c + 1, b]]; coupes += 1
    return [tuple(r) for r in g], coupes


def xy(m, x0, y0, out, profondeur=0):
    """Découpe XY récursive : alterne bandes de lignes et de colonnes vides."""
    for axe in (1, 0):
        r = runs(m.any(axe), 3)
        if len(r) > 1:
            for a, b in r:
                sub = m[a:b + 1] if axe == 1 else m[:, a:b + 1]
                xy(sub, x0 if axe == 1 else x0 + a, y0 + a if axe == 1 else y0, out, profondeur + 1)
            return
    ys, xs = np.nonzero(m)
    if len(xs):
        out.append((x0 + int(xs.min()), y0 + int(ys.min()), x0 + int(xs.max()), y0 + int(ys.max())))


def detourer(rgb, x0, y0, x1, y1):
    """Alpha de la boîte : fond relié au bord -> 0 (propagation 4-voisins sur les pixels proches du fond)."""
    c = rgb[y0:y1 + 1, x0:x1 + 1]
    proche = np.abs(c - FOND).max(2) <= FOND_DETOURAGE
    atteint = np.zeros_like(proche)
    atteint[0, :] = proche[0, :]; atteint[-1, :] = proche[-1, :]; atteint[:, 0] = proche[:, 0]; atteint[:, -1] = proche[:, -1]
    while True:
        n = atteint.copy()
        n[1:] |= atteint[:-1]; n[:-1] |= atteint[1:]; n[:, 1:] |= atteint[:, :-1]; n[:, :-1] |= atteint[:, 1:]
        n &= proche
        if (n == atteint).all():
            return ~atteint
        atteint = n


def main():
    src, sortie_sm, sortie_det, sortie_table = map(Path, sys.argv[1:5])
    p = PLANCHES[src.name]
    im = np.asarray(Image.open(src).convert("RGB")).astype(int)
    global FOND
    bord = np.concatenate([im[-4:].reshape(-1, 3), im[:, -4:].reshape(-1, 3)])
    FOND = np.median(bord, 0)
    sm = im.copy()
    for x0, y0, x1, y1 in p["marques"]:
        sm[y0:y1, x0:x1] = FOND
    Image.fromarray(sm.astype(np.uint8)).save(sortie_sm, optimize=True)
    m_all = np.abs(sm - FOND).max(2) > FOND_MASQUE
    alpha = np.zeros(sm.shape[:2], bool)
    elements, constats = [], []
    for anim, libelle, n, (x0, y0, x1, y1), excl in p["sections"]:
        m = m_all.copy()
        for a, b, c, d in excl:
            m[b:d, a:c] = False
        sub, rgb = m[y0:y1, x0:x1], sm[y0:y1, x0:x1]
        boites = []
        if n is None:
            feuilles = []
            xy(sub, 0, 0, feuilles)
            for a, b, c, d in feuilles:
                if (c - a + 1) * (d - b + 1) < 120 or est_texte(rgb[b:d + 1, a:c + 1], sub[b:d + 1, a:c + 1]):
                    continue
                boites.append((a, b, c, d))
            boites.sort(key=lambda t: (t[1] // 40, t[0]))
        else:
            yy = sans_texte(rgb, sub)
            if yy is None:
                constats.append(f"{anim} : section vide"); continue
            cols, coupes = colonnes(sub[yy[0]:yy[1] + 1], n)
            if coupes:
                constats.append(f"{anim} : {coupes} coupe(s) forcée(s) au creux de projection")
            for a, b in cols:
                cm = sub[:, a:b + 1].copy(); cm[:yy[0]] = False; cm[yy[1] + 1:] = False
                yy2 = sans_texte(rgb[:, a:b + 1], cm)
                if yy2 is None:
                    constats.append(f"{anim} : colonne vide"); continue
                cm[:yy2[0]] = False; cm[yy2[1] + 1:] = False
                ys, xs = np.nonzero(cm)
                boites.append((a + int(xs.min()), int(ys.min()), a + int(xs.max()), int(ys.max())))
        garde = np.ones(alpha.shape, bool)
        for a, b, c, d in excl:
            garde[b:d, a:c] = False
        for i, (a, b, c, d) in enumerate(boites):
            X0, Y0 = max(0, x0 + a - 2), max(0, y0 + b - 2)
            X1, Y1 = min(sm.shape[1] - 1, x0 + c + 2), min(sm.shape[0] - 1, y0 + d + 2)
            alpha[Y0:Y1 + 1, X0:X1 + 1] |= detourer(sm, X0, Y0, X1, Y1) & garde[Y0:Y1 + 1, X0:X1 + 1]
            e = {"id": f"{p['prefixe']}-{anim}" + (f"-{LETTRES[i]}" if len(boites) > 1 else ""),
                 "boite": [X1 - X0 + 1, Y1 - Y0 + 1, X0, Y0], "ancre": "bas", "animation": anim, "libelle": libelle,
                 "cadre": i + 1, "cadres": len(boites)}
            elements.append(e)
        if n and len(boites) != n:
            constats.append(f"{anim} : {len(boites)} cadres pour {n} attendus")
    det = np.zeros((*sm.shape[:2], 4), np.uint8)
    det[..., :3] = np.where(alpha[..., None], sm, 0).astype(np.uint8)
    det[..., 3] = alpha * 255
    Image.fromarray(det, "RGBA").save(sortie_det, optimize=True)
    sha = hashlib.sha256(sortie_det.read_bytes()).hexdigest()
    sortie_table.write_text(json.dumps({
        "planche": sortie_det.name, "planche_sha256": sha, "source": src.name,
        "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "sans_marque": sortie_sm.name, "sans_marque_sha256": hashlib.sha256(sortie_sm.read_bytes()).hexdigest(),
        "fond": [int(v) for v in FOND], "seuils": {"masque": FOND_MASQUE, "detourage": FOND_DETOURAGE, "texte_h": TEXTE_H},
        "constats": constats, "elements": elements}, ensure_ascii=False, indent=1) + "\n")
    print(f"{p['prefixe']}: {len(elements)} éléments ; {'; '.join(constats) or 'aucun constat'}")


if __name__ == "__main__":
    main()
