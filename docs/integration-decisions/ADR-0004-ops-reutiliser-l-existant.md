# ADR-0004 — OPS-001 : réutiliser Prometheus, VictoriaLogs et Grafana

- **Statut :** approuvée
- **Date :** 2026-11-19
- **Approuvée par :** David, HL-538 7-2949

## Contexte

OPS-001 prévoit PostgreSQL, une interface React, OIDC et RBAC à six rôles : surdimensionné pour un homelab qui a déjà Prometheus, VictoriaLogs, Grafana et Authelia (relecture HL-538 7-2948, point 2).

## Décision

« Réutiliser l'existant d'abord. » Les événements des agents et de la file Codex vont vers Prometheus et VictoriaLogs, avec Grafana ; une interface sur mesure seulement pour ce que Grafana ne sait pas faire. Premier lot : file Codex, verrous, fichiers touchés. Les événements REG/BB sont des FactoryEvent ingérés par `towerctl`.

## Alternatives

- Construire OPS-001 tel qu'écrit (PostgreSQL, React, SSE, huit vues) : écartée, contraire à « Integrate before replace ».
- Pas d'OPS du tout : écartée, les contentions du 19/11 (pkill par motif, index git partagé) restaient invisibles.

## Retour arrière

Arrêter les collecteurs de la Tower et retirer ses tableaux Grafana ; les métriques et journaux déjà collectés restent dans Prometheus et VictoriaLogs.

## Références

- homelab-diag `tower/` (lot 1, HL-539).
