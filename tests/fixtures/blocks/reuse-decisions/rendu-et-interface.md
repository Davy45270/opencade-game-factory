# Décision de réutilisation : rendu, interface, sauvegarde et hors-ligne

## Besoin

Afficher le village, la forêt, le temple, les combats et les énigmes dans un navigateur (bureau et téléphone),
jouable au clavier et au doigt, hors ligne après un premier chargement, avec une sauvegarde locale.

## Candidats

| Candidat | Licence | Constat |
|---|---|---|
| Phaser 4.2.1 | MIT | déjà employé et épinglé dans Opencade ; atlas, animations, mise à l'échelle, rendu pixel |
| PixiJS | MIT | rendu seul : scènes, entrées et chargement à écrire |
| Canvas 2D à la main | — | aucune dépendance, mais atlas, animations et redimensionnement à réécrire |
| vite-plugin-pwa 2.0.0 (Workbox) | MIT | déjà employé dans echecs-kid et Opencade pour le précache hors ligne |
| IndexedDB natif | — | aucune dépendance ; `idb-keyval` (Apache-2.0) n'apporte que 30 lignes d'enrobage |

## Choix

Phaser pour la scène (même version qu'Opencade), boutons HTML natifs pour les commandes (clavier, tactile et
lecteur d'écran sans code dédié), vite-plugin-pwa pour le hors-ligne, IndexedDB natif enrobé dans `web/store.ts`.
La sauvegarde elle-même (enveloppe versionnée et scellée) est dans le moteur (`packages/engine/src/save.ts`) et
testée en unitaire.

## Tests de qualification

- `tests/unit/web-assets.test.ts` : chaque texture employée est chargée, la vue ne dessine que des sprites.
- `tests/unit/atlas-generation.test.ts` : pixels des atlas livrés (alpha, cadres, durées, provenance).
- `tests/unit/options-web.test.ts`, `tests/unit/store-web.test.ts` : options et sauvegarde côté navigateur.
- `tests/e2e/parcours.spec.ts`, `tests/e2e/hors-ligne.spec.ts`, `tests/e2e/accessibilite.spec.ts` : parcours,
  hors-ligne et accessibilité dans un vrai navigateur.
