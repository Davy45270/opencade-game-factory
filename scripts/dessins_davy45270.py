#!/usr/bin/env python3
"""HL-538 7-3316, arbitrage du 2026-11-24 : tous les dessins de David (Cozy et Capsule compris) passent en
CC-BY-SA-4.0, attribués à « Davy45270 » ; son nom complet est retiré de toutes les fiches du catalogue.
Règle unique : tools.publish.licenses.david_drawing. Idempotent. Usage : scripts/dessins_davy45270.py <racine-registre>"""
import collections
import json
import pathlib
import sys


def main(racine):
    racine = pathlib.Path(racine)
    sys.path.insert(0, str(racine))
    from tools.core.catalog import write_json
    from tools.publish import licenses
    compte = collections.Counter()
    for chemin in sorted((racine / "catalog").rglob("*.json")):
        texte = chemin.read_text(encoding="utf-8")
        if licenses.DAVID_FULL_NAME not in texte and '"CC-BY-4.0"' not in texte:
            continue
        avant = json.loads(texte)
        if not isinstance(avant, dict):
            continue
        apres = json.loads(texte)
        if "license" in apres:
            licenses.david_drawing(apres)
        else:
            apres = licenses._sans_nom_complet(apres)
        if apres != avant:
            write_json(chemin, apres)
            dossier = chemin.parent.name
            compte[f"{dossier}:fiches"] += 1
            if avant.get("license") != apres.get("license"):
                compte[f"{dossier}:{avant.get('license')}->{apres.get('license')}"] += 1
            if licenses.DAVID_FULL_NAME in texte:
                compte[f"{dossier}:nom_complet_retire"] += 1
    print(json.dumps(dict(sorted(compte.items())), ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
