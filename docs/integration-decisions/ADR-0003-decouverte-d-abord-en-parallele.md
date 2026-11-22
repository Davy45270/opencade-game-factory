# ADR-0003 — Découverte de l'existant tout de suite, en parallèle des chantiers

- **Statut :** approuvée
- **Date :** 2026-11-19
- **Approuvée par :** David, HL-525 7-2955

## Contexte

ARCH-001 exige la découverte avant toute conception, alors que OPS-001, le registre, EXT-001 et EXT-002 étaient déjà lancés (relecture 7-2953, point 5).

## Décision

« Découverte maintenant, en parallèle. » Un agent Claude produit ARCH-01 à 03 (`existing-capabilities.json`, `process-map.md`, `gap-analysis.md`) hors file Codex ; les chantiers en cours continuent puis sont recadrés d'après la gap analysis. Six de chaque sert de tranche verticale (ARCH-12).

## Alternatives

- Geler tous les chantiers jusqu'à la fin de la découverte : écartée, coût d'arrêt sans gain mesuré.
- Pas de découverte formelle (graphify seul) : écartée, contraire au principe « Discover before design ».

## Retour arrière

Les recadrages sont des tickets ordinaires : en retirer un rétablit le plan précédent ; les livrables de découverte restent valables.

## Références

- `homelab-docs/specs/game-factory/` (ARCH-01 à 03, HL-525 7-2956).
