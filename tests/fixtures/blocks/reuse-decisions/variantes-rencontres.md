# Décision de réutilisation : variantes de rencontre

## Besoin

Faire varier une rencontre d'une partie à l'autre (offensive, santé des ennemis, difficulté) de façon déclarée dans
les données et reproductible par la graine, sans casser le rejeu.

## Candidats

| Candidat | Version | Licence | Constat |
|---|---|---|---|
| `rot-js` (npm) | 2.2.1 | BSD-3-Clause | boîte à outils de jeu (RNG, cartes, tables pondérées) ; seul le RNG servirait, et il ne partage pas l'état du moteur |
| `chance` (npm) | 1.1.13 | MIT | générateurs aléatoires variés ; graine possible, état non sérialisable simplement |
| `pure-rand` (npm) | 8.4.2 | MIT | générateurs purs à état sérialisable ; ferait doublon avec le PRNG du moteur |
| Profils de difficulté et PRNG du moteur (`progression.ts`, `rng.ts`, `EncounterBalance`) | — | MIT | variation tirée à la création de la rencontre dans l'état de combat, donc sauvegardée et rejouée |

## Choix

Les profils de difficulté et le PRNG du moteur. La variation est tirée une fois, à la création de la rencontre, à
partir du même état de hasard que le combat : elle entre dans la sauvegarde et dans le rejeu sans mécanisme de
plus. Une seconde source de hasard obligerait à sérialiser deux états.

## Risques

- La plage d'offensive et les bonus de santé sont des données : une plage trop large rend une rencontre
  injouable ; seule la simulation d'équilibrage le détecte.
- Ajouter un tirage à la création d'une rencontre décale tous les tirages suivants et change les rejeux
  enregistrés : à faire avec une nouvelle version de règles.

## Tests de qualification

- `tests/unit/slice.test.ts` : effet de chaque difficulté sur l'offensive ennemie.
- `tests/unit/simulation.test.ts` : taux de victoire mesurés sur les variantes.
- `tests/unit/save.test.ts` : une sauvegarde antérieure sans difficulté est migrée.
