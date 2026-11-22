#!/usr/bin/env python3
"""EXT-002 `validate` du catalogue entier en CI (E258) : chaque fiche de `catalog/levels/` passe les gates communes et
le validateur de son genre, avec le profil du jeu s'il est fourni (`--profils DOSSIER`, fichiers `<jeu>.json`).

Un niveau `fail` fait échouer la CI (code 4). Un niveau `inconclusive` (moteur du jeu non fourni, budget atteint) est
COMPTÉ et listé, jamais rangé en `pass` ; `--exiger-pass` le rend bloquant. Rapport JSON sur stdout.
"""
import argparse
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from tools.levels.commands import _known_assets, _load_all  # noqa: E402
from tools.levels.validators import validate  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--profils", type=Path)
    p.add_argument("--exiger-pass", action="store_true")
    a = p.parse_args(argv)
    niveaux, assets = _load_all(RACINE), _known_assets(RACINE)
    compte, echecs, indetermines = {}, [], []
    for niveau_id, fiche in sorted(niveaux.items()):
        jeu = fiche["origin"]["game"]
        profil = None
        if a.profils and (a.profils / f"{jeu}.json").is_file():
            profil = json.loads((a.profils / f"{jeu}.json").read_text(encoding="utf-8"))
        rapport = validate(fiche, profil, assets, niveaux)
        compte[rapport["status"]] = compte.get(rapport["status"], 0) + 1
        ligne = {"id": niveau_id, "codes": sorted({d["code"] for d in rapport["diagnostics"]})}
        if rapport["status"] == "fail":
            echecs.append(ligne)
        elif rapport["status"] == "inconclusive":
            indetermines.append(ligne)
    print(json.dumps({"niveaux": len(niveaux), "statuts": compte, "echecs": echecs,
                      "indetermines": indetermines}, ensure_ascii=False, indent=2))
    if echecs:
        return 4
    return 6 if a.exiger_pass and indetermines else 0


if __name__ == "__main__":
    sys.exit(main())
