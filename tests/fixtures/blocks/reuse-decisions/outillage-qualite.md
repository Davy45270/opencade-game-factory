# Décision de réutilisation : outillage de tests et de couverture

## Besoin

Tests unitaires TypeScript sans compilation séparée, tests de propriétés, tests de bout en bout dans un navigateur
sans affichage, mesure de couverture de branches fusionnable entre étapes de CI.

## Candidats

| Composant | Candidat | Version | Licence | Constat |
|---|---|---|---|---|
| unitaires | Vitest | 5.1.0 | MIT | TypeScript natif, même configuration que Vite, rapports « blob » fusionnables |
| unitaires | Jest | 30 | MIT | demande une transformation TypeScript et une configuration ESM à part |
| propriétés | fast-check | 4.10.3 | MIT | réducteurs, graine rejouable, intégré à Vitest |
| propriétés | jsverify | 0.8 | MIT | plus maintenu |
| e2e | Playwright | 1.65.1 | Apache-2.0 | image de CI officielle avec navigateurs, clavier et tactile |
| e2e | Cypress | 15 | MIT | binaire lourd, tactile limité, pas d'image alignée sur le parc |
| couverture | @vitest/coverage-v8 | 5.1.0 | MIT | couverture native du moteur V8, seuils par configuration |
| couverture | @vitest/coverage-istanbul | 5.1.0 | MIT | instrumentation plus lente, même résultat pour ce code |

Sources : registre npm et dépôts des projets, consultés le 2026-11-19.

## Choix

Vitest, fast-check, Playwright et coverage-v8. Alignés sur les autres jeux du mainteneur : une seule chaîne à
maintenir. Licences compatibles MIT, outils de développement non embarqués.

## Risques

Montée de version de Playwright : l'image de `e2e.yml` doit suivre (contrôle intégré à l'étape).

## Tests de qualification

`tests/unit/ci-pipeline.test.ts` (suites, seuil de couverture), `tests/unit/golden.test.ts`.
