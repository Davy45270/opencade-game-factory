# ADR-0007 — Priorités : jeux et registre, puis Tower ; 2e Codex si l'onduleur le permet

- **Statut :** approuvée
- **Date :** 2026-11-19
- **Approuvée par :** David, HL-538 7-2949

## Contexte

OPS-001, EXT-001, EXT-002, le registre et quatre jeux se partagent une seule file Codex (relecture 7-2948, point 8).

## Décision

« Jeux et registre, puis Tower. » Les jeux et le registre continuent ; le lot 1 d'OPS-001 est écrit par un agent Claude en parallèle ; ensuite Kenney, puis les niveaux puzzle et RPG. Un 2e Codex sur tank01 si l'onduleur reste sous 75 %.

## Alternatives

- Tower d'abord : écartée, elle aurait arrêté les jeux.
- Tout en parallèle dans la file Codex : écartée, la file saturait (jusqu'à 2 371 s d'attente).

## Retour arrière

L'ordre est une consigne de file : le changer ne demande qu'un nouvel arbitrage, aucun code n'en dépend ; le 2e Codex s'arrête par son unité systemd.

## Références

- `homelab-docs/specs/game-factory/gap-analysis.md` § 6.
