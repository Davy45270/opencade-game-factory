# ADR-0006 — EXT-002 fait foi, dans le registre ; un validateur par premier jeu

- **Statut :** approuvée
- **Date :** 2026-11-19
- **Approuvée par :** David, HL-538 7-2949

## Contexte

EXT-002 recouvre la « Level Factory » du 13/11 et prévoyait un dépôt `level-registry` séparé ; cinq familles de validateurs P0 d'un coup (relecture 7-2948, points 5 à 7).

## Décision

« EXT-002 fait foi, dans le registre. » EXT-002 remplace la Level Factory ; le code va dans l'usine (`tools/levels/`, `assetctl level`). Chaque validateur arrive avec le premier jeu qui en a besoin, et le jeu expose son moteur sans écran.

## Alternatives

- Garder la Level Factory du 13/11 : écartée, doublon de spec.
- Dépôt `level-registry` séparé : écartée (ADR 0002).

## Retour arrière

`ASSETCTL_LEVELS=off` désactive le module sans toucher au registre d'assets ; les fiches `catalog/levels/` sont indépendantes des fiches d'assets.

## Références

- `docs/ARCHITECTURE.md` § « Niveaux et mondes (EXT-002) ».
