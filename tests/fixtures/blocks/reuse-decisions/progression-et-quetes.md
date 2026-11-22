# Décision de réutilisation : progression et quêtes

## Besoin

Expérience et niveaux, quêtes à objectifs avec événements uniques et récompenses idempotentes, dépendances entre
quêtes sans cycle, et contenu de quête validé contre le schéma d'origine.

## Candidats

| Candidat | Version | Licence | Constat |
|---|---|---|---|
| `xstate` (npm) | 5.33.4 | MIT | machines à états pour les phases d'une quête ; l'idempotence par identifiant d'événement reste à écrire |
| `robot3` (npm) | 1.4.0 | BSD-2-Clause | machines à états légères ; même limite, et une dépendance d'exécution de plus |
| `ajv` (npm, déjà employé) | 8.20.0 | MIT | valide le contenu contre les schémas JSON d'origine, avec erreurs localisées |
| Fonctions du dépôt `progression.ts`, `quests.ts`, `world-quests.ts` | — | MIT | phases, événements vus et récompense unique déjà écrits et testés |

## Choix

Les fonctions du dépôt pour la logique, Ajv pour la validation du contenu. Une machine à états ne couvre que la
partie simple (les phases) ; la partie difficile, traiter chaque événement une seule fois et ne payer la récompense
qu'une fois, reste dans notre code dans tous les cas. Ajv est déjà la bibliothèque de validation du paquet de
contenu.

## Risques

- Un objectif à quantité supérieure à un dépend de l'identifiant d'événement : deux collectes au même lieu peuvent
  être comptées comme une seule (cas relevé en revue, à couvrir par un test dédié).
- Le schéma d'origine doit rester octet pour octet celui de l'archive ; une retouche locale se verrait à l'empreinte.

## Tests de qualification

- `tests/unit/quests.test.ts` : événement unique, récompense idempotente.
- `tests/unit/progression.test.ts` : courbe d'expérience et statistiques par niveau.
- `tests/unit/quest-schema-ajv.test.ts` : contraintes des objectifs et des récompenses, une par une.
- `tests/unit/content.test.ts` : références et dépendances cycliques refusées.
