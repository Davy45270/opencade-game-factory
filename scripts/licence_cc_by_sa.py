#!/usr/bin/env python3
"""HL-538 7-3316 (David, 2026-11-22) : les dessins de David passent de la licence privée à CC BY-SA 4.0.

Toute fiche du catalogue sous LicenseRef-David-Prive-Tous-Droits-Reserves (dictionnaire porteur d'un champ
`license`, à n'importe quelle profondeur : fiche, version antérieure) passe en CC-BY-SA-4.0, avec la nouvelle preuve.
L'auteur affiché devient « Davy45270 » (attribution exigée par David, jamais son nom complet).
Les fiches déjà en CC-BY-4.0 (Capsule Panic, Cozy) gardent leur licence. Idempotent.
Usage : scripts/licence_cc_by_sa.py <racine-registre>"""
import json
import pathlib
import sys

AVANT = "LicenseRef-David-Prive-Tous-Droits-Reserves"
APRES = "CC-BY-SA-4.0"
ATTRIBUTION = "Davy45270"
PREUVE = {"method": "décision du propriétaire", "ref": "HL-538 7-3316 (remplace 7-3162 et 7-3165)",
          "decision": "Dessins de David : Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0), "
                      f"décision du 2026-11-22. Attribution : « {ATTRIBUTION} ». Texte : LICENSES/CC-BY-SA-4.0.txt."}
# Auteur affiché des fiches passées en CC BY-SA : « Davy45270 », jamais le nom complet (consigne de David, 7-3316).
# Les citations des preuves restent telles quelles ; les fiches CC BY 4.0 (Capsule, Cozy…) ne sont pas touchées.
AUTEURS = (("David (dessin fourni par David", "Davy45270 (dessin fourni par David"),
           ("David (planche découpée", "Davy45270 (planche découpée"),
           ("Davy45270", "Davy45270"))


def migrer(noeud):
    n = 0
    if isinstance(noeud, dict):
        if noeud.get("license") == AVANT:
            noeud["license"] = APRES
            if "licenseEvidence" in noeud:
                noeud["licenseEvidence"] = dict(PREUVE)
            n += 1
        prov = noeud.get("provenance")
        if noeud.get("license") == APRES and isinstance(prov, dict) and isinstance(prov.get("author"), str):
            for avant, apres in AUTEURS:
                prov["author"] = prov["author"].replace(avant, apres)
        for v in noeud.values():
            n += migrer(v)
    elif isinstance(noeud, list):
        for v in noeud:
            n += migrer(v)
    return n


def main(racine):
    racine = pathlib.Path(racine)
    sys.path.insert(0, str(racine))
    from tools.core.catalog import write_json
    fiches = total = 0
    for chemin in sorted((racine / "catalog").rglob("*.json")):
        texte = chemin.read_text(encoding="utf-8")
        if AVANT not in texte and "David" not in texte:
            continue
        donnees = json.loads(texte)
        k = migrer(donnees)
        if k or json.loads(texte) != donnees:
            write_json(chemin, donnees)
            fiches, total = fiches + 1, total + k
    print(json.dumps({"fiches": fiches, "licences": total}))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
