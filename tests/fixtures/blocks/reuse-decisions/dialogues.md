# Décision de réutilisation : dialogues

## Besoin

Des dialogues courts liés aux lieux : un locuteur, des lignes en français et en anglais, parfois un choix qui pose
un drapeau ou fait avancer une étape de quête, avec des prérequis par identifiants et un choix définitif par lieu.

## Candidats

| Candidat | Version | Licence | Constat |
|---|---|---|---|
| `inkjs` (npm) | 2.4.0 | MIT | moteur narratif complet (branches, variables) ; contenu dans un langage à compiler, état propre au moteur à sérialiser à part |
| `yarn-bound` (npm) | 0.5.5 | ISC | dialogues à nœuds et commandes ; peu maintenu, état interne mutable |
| Événements de scène du dépôt (`NodeEvent` « talk », `content/dialogues/`) | — | MIT | locuteur et lignes déjà là ; les choix réutilisent `achieve` et les drapeaux de la partie |

## Choix

Les événements de scène du dépôt, prolongés par des choix déclaratifs. Les dialogues du jeu tiennent en quelques
lignes par lieu : un moteur narratif ajouterait un second état à sauvegarder et un langage de plus à valider, sans
besoin réel. Les choix passent par les mêmes drapeaux et étapes que le reste de la partie, donc par la même
sauvegarde et le même rejeu.

## Risques

- Pas de variables ni de branches imbriquées : un dialogue plus riche demanderait de revoir ce choix.
- Les textes vivent dans des fichiers JSON par langue ; une ligne manquante n'est détectée qu'à la construction des
  données.

## Tests de qualification

- `tests/unit/slice.test.ts` : choix de dialogue, prérequis et drapeaux posés.
- `tests/unit/mvp-world.test.ts` : parcours complet jusqu'au retour au village.
