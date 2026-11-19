# Décision de réutilisation : combat versionné

## Besoin

Un combat au tour par tour pur et déterministe : ordre par vitesse puis identifiant, dégâts, statuts, fuite et
recrutement selon des règles versionnées (`slice-1.1`, `v1.0`), rejouable à l'identique depuis une graine et une
liste de commandes, sans dépendre du rendu.

## Candidats

| Candidat | Version | Licence | Constat |
|---|---|---|---|
| `boardgame.io` (npm) | 0.50.2 | MIT | moteur de jeux au tour par tour complet (phases, tours, rejeu) ; impose son client, son serveur et son état ; aucune règle de combat fournie |
| `xstate` (npm) | 5.33.4 | MIT | machines à états typées ; décrit bien les phases, pas les calculs de dégâts ni le PRNG ; ajoute une dépendance d'exécution |
| `immer` (npm) | 11.2.10 | MIT | copies immuables commodes ; `structuredClone` du langage suffit pour un état de cette taille |
| Réducteur du dépôt `packages/engine/src/combat.ts` | — | MIT | `resolveRound(combat, commandes, règles)` déjà écrit pour le slice, branché sur le PRNG du moteur |

## Choix

Le réducteur du dépôt. Les règles de la spec (formules de dégâts, fuite, apprivoisement) sont propres au jeu :
aucune bibliothèque ne les fournit, et les deux cadres génériques n'apporteraient que l'ordonnancement, au prix
d'une dépendance d'exécution, de son arbre dans le SBOM et d'un état qu'ils possèdent. Le réducteur reste
utilisable sans rendu, et le contrat public `applyCombatAction` s'adapte à lui.

## Risques

- Tout le calcul est à notre charge : une erreur de formule n'est rattrapée que par les tests ci-dessous.
- Deux versions de règles cohabitent ; une modification doit dire laquelle elle touche, sinon les rejeux
  enregistrés divergent (les replays golden le détectent).

## Tests de qualification

- `tests/unit/scenarios-p0.test.ts` : les scénarios d'acceptation de combat, oracles tirés de la spec.
- `tests/unit/rulesets.test.ts` : formules exactes des deux versions de règles.
- `tests/unit/combat.test.ts`, `tests/unit/combat-api.test.ts` : réducteur et contrat public.
- `tests/unit/golden.test.ts` : rejeux enregistrés, identiques octet pour octet.
