# Décision de réutilisation : simulation d'équilibrage

## Besoin

Jouer chaque rencontre un grand nombre de fois avec des builds de référence, mesurer les taux de victoire (cible
75–95 % en normal, 50–80 % en tactique) et prouver qu'aucune rencontre obligatoire n'est à 0 %.

## Candidats

| Candidat | Version | Licence | Constat |
|---|---|---|---|
| `simple-statistics` (npm) | 8.0.0 | ISC | moyennes, écarts et intervalles ; un taux de victoire n'est qu'un ratio |
| `fast-check` (npm, déjà employé) | 4.10.3 | MIT | génère des graines et des groupes ; sert aux propriétés, pas à compter des taux |
| `boardgame.io` (npm) | 0.50.2 | MIT | contient un simulateur d'IA (MCTS) ; suppose son propre modèle de jeu |
| Réducteur et politique ennemie du dépôt (`simulation.ts`, `ai.ts`) | — | MIT | rejoue des commandes pour une graine ; il suffit d'injecter une politique de groupe |

## Choix

Le réducteur du moteur, avec une politique de groupe injectée par build. La simulation doit jouer exactement les
règles du jeu : réutiliser le réducteur l'assure, alors qu'un simulateur externe en jouerait une copie. Le calcul
statistique se réduit à un ratio sur un nombre fixé de combats : aucune bibliothèque n'est justifiée.

## Risques

- Les builds de référence décident du résultat : des héros sans compétences ou sans l'inventaire de campagne ne
  représentent pas le parcours équipé (constat de revue) ; ils doivent suivre le contenu réel.
- Mille combats par rencontre coûtent du temps de CI : la suite tourne dans sa propre étape.

## Tests de qualification

- `tests/unit/simulation.test.ts` : taux de victoire par difficulté et absence de rencontre à 0 %.
- `tests/unit/slice.test.ts` : le bot de recette traverse le parcours avec les mêmes règles.
