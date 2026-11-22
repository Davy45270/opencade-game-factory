#!/usr/bin/env python3
"""Contrôle de l'index visuel CLIP en mode CPU (CI, E110) : sans GPU, on retrouve les vecteurs calculés sur tank01.

1. Recalcule sur CPU les vecteurs de N vignettes tirées de l'index commité (generated/visual/) et exige un cosinus
   ≥ 0,99 avec ceux de l'XPU (même modèle, mêmes vignettes) : l'index n'est pas une boîte noire.
2. Requêtes textuelles témoins : chaque requête doit ramener, dans ses 5 premiers, une fiche dont l'identifiant porte
   le mot attendu (« a cat » → chat). Mesure qui distingue un index sain d'un index permuté ou d'un modèle changé.
Code 0 si tout passe, 1 sinon ; rapport JSON sur stdout.
"""
import json
import sys
from pathlib import Path

import numpy as np

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
from tools.index.visual import Clip, _charger, vignettes  # noqa: E402

TEMOINS = {"a cat": "chat", "a cardboard box": "carton", "a red apple": "pommier"}


def main(n=40):
    shas, matrice, meta = _charger(RACINE, Clip.nom)
    clip = Clip("cpu")
    rows = vignettes(RACINE)
    pas = max(1, len(shas) // n)
    choix = list(range(0, len(shas), pas))[:n]
    cpu = clip.images([rows[shas[i]][0] for i in choix])
    cos = (cpu * matrice[choix]).sum(axis=1)
    temoins = {}
    for requete, mot in TEMOINS.items():
        top = np.argsort(-(matrice @ clip.texte(requete)))[:5]
        ids = [i for k in top for i in rows.get(shas[k], (None, []))[1]]
        temoins[requete] = {"attendu": mot, "trouve": any(mot in i for i in ids), "top": ids[:5]}
    ok = bool(cos.min() >= 0.99) and all(t["trouve"] for t in temoins.values())
    print(json.dumps({"ok": ok, "index": meta, "vecteursRecalcules": len(choix),
                      "cosinusMin": round(float(cos.min()), 5), "temoins": temoins}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
