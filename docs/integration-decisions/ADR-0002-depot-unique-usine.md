# ADR-0002 — Un seul dépôt usine : assets, niveaux, specs et briques

- **Statut :** approuvée
- **Date :** 2026-11-19
- **Approuvée par :** David, HL-525 7-2955

## Contexte

Prolifération de dépôts proposée par les specs (`opencade-asset-registry`, `opencade-spec-registry`, un dépôt BB, `level-registry`), chacun avec sa CI, ses schémas et sa CLI (relecture 7-2953, point 2).

## Décision

« Un seul dépôt usine. » Le dépôt privé `opencade-asset-registry` devient l'usine : modules `assets`, `levels`, `specs` et `blocks`, une CI Woodpecker et des schémas communs, sous-commandes `assetctl`, `assetctl level`, `specctl` et `bbctl`. Le registre d'assets y est le magasin d'assets (originaux référencés par empreinte et origine, voir E009).

## Alternatives

- Un dépôt par spec (REG-003, BB-001, EXT-002 tels qu'écrits) : écartée, quatre CI et quatre jeux de schémas à tenir alignés.
- Garder le registre seul et loger specs et briques dans homelab-docs : écartée, la doc n'a ni CI de schémas ni CLI.

## Retour arrière

Chaque module vit dans son dossier (`specs/`, `blocks/`, `tools/levels/`, `tools/`) : il s'extrait dans un dépôt neuf avec son historique par `git filter-repo --path <module>`, en recopiant ce qu'il importe de `tools/core/` ou d'un autre module.

## Références

- `docs/ARCHITECTURE.md` § « Modules à venir : le dépôt unique de l'usine ».
