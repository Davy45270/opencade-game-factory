#!/usr/bin/env python3
"""Découpe des planches Pestouille de David (Drive Homelab/assets/Pestouille, 2026-11-21) pour le registre.

Trois gabarits :
  gabarit4  : 1536x1024, rangées = directions (droite, gauche, bas, haut), colonnes = idle 4 / marche 6 /
              attaque 6 / blessé 3, cadres jaunes. La « grille 64x64 » annoncée n'est PAS utilisée (pas réel 65-72).
  variantes : 1774x887, colonnes = variantes de couleur, rangées = idle / marche / attaque / blessé.
  planche19 : 1774x887 sans texte, 6 x 4 cases égales, une image par case (idle 4, marche 6, attaque 6, blessé 3).
Détourage : fond noir relié au bord de chaque case -> alpha 0 (seuil sur max(R,G,B)) ; hors cases -> alpha 0 ;
pour une planche à alpha réel, l'alpha est conservé (option --seuil-alpha : alpha < seuil -> 0, voile de « dos »).
Découpe dans une case : projection des colonnes ; les petits morceaux (effets) rejoignent le voisin le plus proche ;
une plage beaucoup plus large que les autres est coupée au creux de projection (sprites jointifs).
Règle des cases « attaque » (consigne du 21/11) : acceptée si le nombre trouvé est le nombre RÉEL attendu et
qu'aucune coupe forcée n'a eu lieu, ou si la planche est dans --attaque-verifiee (contrôle visuel). Sinon le
bloc entier devient UN élément « …-attaque-bloc » (état « a-decouper »), rien n'est perdu.
Usage : decoupe.py <gabarit> <planche.png> <prefixe> <sortie-detouree.png> <sortie.decoupe.json>
        [--variantes a,b,c] [--attaque-reelle dir=n,...] [--attaque-verifiee] [--seuil-alpha N] [--seuil-fond N]"""
import argparse, hashlib, json
import numpy as np
from PIL import Image

ANIMS = [("idle", 4), ("marche", 6), ("attaque", 6), ("blesse", 3)]
LETTRES = "abcdefghijklmn"

def groupes(idx, ecart=6):
    g = []
    for i in idx:
        i = int(i)
        if g and i - g[-1][-1] <= ecart: g[-1].append(i)
        else: g.append([i])
    return [(a[0], a[-1]) for a in g]

def jaune(a):
    return (a[..., 0] > 140) & (a[..., 1] > 100) & (a[..., 2] < 100) & (a[..., 0] - a[..., 2] > 80)

def proche(cands, cible):
    return min(cands, key=lambda g: abs((g[0] + g[1]) / 2 - cible))

def cadre_gabarit4(a):
    H, W = a.shape[:2]; j = jaune(a)
    rows = groupes(np.flatnonzero(j.sum(1) > 0.45 * W))
    top = max(g[1] for g in rows if 150 <= g[1] <= 200) + 1
    bottom = min(g[0] for g in rows if g[0] > H * 0.85) - 1
    cols = groupes(np.flatnonzero(j[top:bottom].sum(0) > 0.45 * (bottom - top)))
    gauche = max(g[1] for g in cols if 130 <= g[1] <= 175) + 1
    droite = min(g[0] for g in cols if g[0] > W * 0.95) - 1
    ys = [top]
    for k in (1, 2, 3):
        g = proche([g for g in rows if top < g[0] < bottom], top + k * (bottom - top) / 4); ys += [g[0] - 1, g[1] + 1]
    ys.append(bottom)
    internes = [g for g in cols if gauche < g[0] < droite]
    xs = [gauche]
    for f in (289 / 1373, 680 / 1373, 1110 / 1373):   # largeurs relatives du gabarit, mesurées sur golem
        g = proche(internes, gauche + f * (droite - gauche)); xs += [g[0] - 1, g[1] + 1]
    xs.append(droite)
    bandes = [(ys[2 * i], ys[2 * i + 1]) for i in range(4)]
    colonnes = [(xs[2 * i], xs[2 * i + 1]) for i in range(4)]
    dirs = ["droite", "gauche", "bas", "haut"]
    return [(dirs[r], ANIMS[c], bandes[r], colonnes[c]) for r in range(4) for c in range(4)]

def cadre_variantes(a, noms):
    H, W = a.shape[:2]; j = jaune(a)
    rows = groupes(np.flatnonzero(j.sum(1) > 0.45 * W))
    rows = [g for g in rows if g[0] > 40][-5:]          # 5 traits : haut du tableau puis 4 séparations/bas
    cols = groupes(np.flatnonzero(j[rows[0][1]:rows[-1][0]].sum(0) > 0.45 * (rows[-1][0] - rows[0][1])))
    cols = cols[-(len(noms) + 1):]
    cases = []
    for r in range(4):
        y0, y1 = rows[r][1] + 1, rows[r + 1][0] - 1
        for c, nom in enumerate(noms):
            x0, x1 = cols[c][1] + 1, cols[c + 1][0] - 1
            cases.append((nom, ANIMS[r], (y0, y1), (x0, x1)))
    return cases

def cadre_planche19(a):
    H, W = a.shape[:2]; cw, rh = W / 6, H / 4
    cases = []
    for r, anim in enumerate(ANIMS):
        cases.append(("", anim, (int(r * rh), int((r + 1) * rh) - 1), (0, W - 1)))
    return cases, cw

def detourer(rgb, alpha_src, cases, seuil, seuil_alpha):
    H, W = rgb.shape[:2]
    alpha = np.zeros((H, W), np.uint8)
    for _, _, (y0, y1), (x0, x1) in cases:
        if alpha_src is not None:
            sub = alpha_src[y0:y1 + 1, x0:x1 + 1].copy()
            sub[sub < seuil_alpha] = 0
            alpha[y0:y1 + 1, x0:x1 + 1] = sub
            continue
        c = rgb[y0:y1 + 1, x0:x1 + 1]
        bas = (c.max(2) <= seuil) & ~jaune(c)
        m = 4; bord = np.zeros_like(bas); bord[:m] = bord[-m:] = True; bord[:, :m] = bord[:, -m:] = True
        # quadrillage fin (filet orange de « profil droit ») : colonne ou rangée allumée sur > 92 % de la case
        allume = c.max(2) > 40
        for x in np.flatnonzero(allume.mean(0) > 0.92): bord[:, max(0, x - 1):x + 2] = True
        for y in np.flatnonzero(allume.mean(1) > 0.92): bord[max(0, y - 1):y + 2, :] = True
        fond = bord | (bas & False); bas |= bord
        fond[0] |= bas[0]
        while True:
            d = fond.copy()
            d[1:] |= fond[:-1]; d[:-1] |= fond[1:]; d[:, 1:] |= fond[:, :-1]; d[:, :-1] |= fond[:, 1:]
            d &= bas
            if (d == fond).all(): break
            fond = d
        alpha[y0:y1 + 1, x0:x1 + 1] = np.where(fond, 0, 255)
    return alpha

def plages(sub, attendu, largeur_case):
    proj = sub.sum(0); idx = np.flatnonzero(proj > 0)
    rs = groupes(idx, 2) if len(idx) else []
    poids = lambda r: int(proj[r[0]:r[1] + 1].sum())
    gros = [r for r in rs if poids(r) >= 250 and r[1] - r[0] >= 14]
    for r in rs:
        if r in gros or not gros: continue
        k = min(range(len(gros)), key=lambda i: min(abs(r[0] - gros[i][1]), abs(gros[i][0] - r[1])))
        gros[k] = (min(gros[k][0], r[0]), max(gros[k][1], r[1]))
    gros.sort(); coupe = False
    if gros:
        med = float(np.median([r[1] - r[0] + 1 for r in gros]))
        ref = min(med, largeur_case / attendu * 0.95)
        sortie = []
        for r in gros:
            w = r[1] - r[0] + 1; n = int(round(w / ref)) if w > 1.6 * ref else 1
            if n > 1:
                coupe = True; b = [r[0]]
                for q in range(1, n):
                    c = r[0] + q * w / n; lo, hi = int(c - ref * 0.25), int(c + ref * 0.25)
                    b.append(lo + int(np.argmin(proj[lo:hi + 1])))
                b.append(r[1] + 1)
                sortie += [(b[i], b[i + 1] - 1) for i in range(n)]
            else:
                sortie.append(r)
        gros = sortie
    return gros, coupe

def boite(sub, c0, c1, x0, y0):
    lignes = np.flatnonzero(sub[:, c0:c1 + 1].any(1))
    return [int(c1 - c0 + 1), int(lignes[-1] - lignes[0] + 1), int(x0 + c0), int(y0 + lignes[0])]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gabarit", choices=["gabarit4", "variantes", "planche19"])
    ap.add_argument("planche"); ap.add_argument("prefixe"); ap.add_argument("detouree"); ap.add_argument("table")
    ap.add_argument("--variantes", default=""); ap.add_argument("--attaque-reelle", default="")
    ap.add_argument("--attaque-verifiee", action="store_true")
    ap.add_argument("--seuil-alpha", type=int, default=0); ap.add_argument("--seuil-fond", type=int, default=28)
    a = ap.parse_args()
    img = Image.open(a.planche); has_alpha = img.mode == "RGBA"
    rgba = np.asarray(img.convert("RGBA")); rgb = rgba[..., :3].astype(int)
    reelle = dict(x.split("=") for x in a.attaque_reelle.split(",") if x)
    if a.gabarit == "gabarit4":
        cases = cadre_gabarit4(rgb)
    elif a.gabarit == "variantes":
        cases = cadre_variantes(rgb, a.variantes.split(","))
    else:
        cases, _ = cadre_planche19(rgb)
    alpha = detourer(rgb, rgba[..., 3] if has_alpha else None, cases, a.seuil_fond, a.seuil_alpha)
    out = rgba.copy(); out[..., 3] = alpha
    Image.fromarray(out, "RGBA").save(a.detouree, optimize=True)
    elements, constats = [], []
    for ligne, (anim, annonce), (y0, y1), (x0, x1) in cases:
        sub = alpha[y0:y1 + 1, x0:x1 + 1] >= 128
        base = "-".join(p for p in (a.prefixe, ligne, anim) if p)
        rs, coupe = plages(sub, annonce, (x1 - x0 + 1) * (annonce / 6 if a.gabarit == "planche19" else 1))
        attendu = int(reelle.get(ligne or "_", annonce)) if anim == "attaque" else annonce
        ok = len(rs) == attendu and (anim != "attaque" or not coupe or a.attaque_verifiee)
        if anim != "attaque" and len(rs) != attendu:
            ok = False
        if ok:
            for i, (c0, c1) in enumerate(rs):
                elements.append({"id": f"{base}-{LETTRES[i]}", "boite": boite(sub, c0, c1, x0, y0), "ancre": "bas",
                                 "animation": anim, "ligne": ligne, "cadre": i + 1, "cadres": len(rs)})
        else:
            ys = np.flatnonzero(sub.any(1)); xs = np.flatnonzero(sub.any(0))
            elements.append({"id": f"{base}-bloc", "boite": [int(xs[-1] - xs[0] + 1), int(ys[-1] - ys[0] + 1),
                             int(x0 + xs[0]), int(y0 + ys[0])], "ancre": "bas", "animation": anim, "ligne": ligne,
                             "etat": "a-decouper", "trouves": len(rs), "attendus": attendu})
        constats.append({"ligne": ligne, "animation": anim, "annonce": annonce, "attendu": attendu,
                         "trouve": len(rs), "coupe_forcee": coupe, "accepte": ok})
    sha = hashlib.sha256(open(a.detouree, "rb").read()).hexdigest()
    json.dump({"planche": a.detouree.rsplit("/", 1)[-1], "planche_sha256": sha, "marge": 0,
               "source": a.planche.rsplit("/", 1)[-1],
               "source_sha256": hashlib.sha256(open(a.planche, "rb").read()).hexdigest(),
               "gabarit": a.gabarit, "seuil_fond": None if has_alpha else a.seuil_fond,
               "seuil_alpha": a.seuil_alpha if has_alpha else None, "constats": constats, "elements": elements},
              open(a.table, "w"), ensure_ascii=False, indent=1)
    blocs = [c for c in constats if not c["accepte"]]
    print(f"{a.prefixe}: {sum('cadre' in e for e in elements)} cadres, {len(blocs)} blocs à découper "
          f"{[(c['ligne'], c['animation'], c['trouve'], c['attendu']) for c in blocs]}")

if __name__ == "__main__":
    main()
