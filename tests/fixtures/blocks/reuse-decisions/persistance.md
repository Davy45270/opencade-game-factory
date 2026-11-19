# Décision de réutilisation : persistance et essais hors navigateur

## Besoin

Écrire et relire la sauvegarde dans le navigateur, hors ligne, sans annoncer « sauvegardé » avant que la
transaction soit validée ; et tester cet adaptateur sous Node, sans navigateur.

## Candidats

| Candidat | Version | Licence | Constat |
|---|---|---|---|
| `dexie` (npm) | 4.4.7 | Apache-2.0 | enrobage complet d'IndexedDB (schémas, requêtes) ; démesuré pour une seule clé |
| `idb` (npm) | 8.0.4 | ISC | promesses autour d'IndexedDB, fin et fidèle à l'API ; dépendance d'exécution |
| `idb-keyval` (npm) | 6.3.0 | Apache-2.0 | magasin clé-valeur en trente lignes ; ne laisse pas attendre la fin de transaction |
| IndexedDB natif, adaptateur `web/store.ts` | API standard | — | rien à distribuer ; la fin de transaction (`oncomplete`) est sous notre contrôle |
| `fake-indexeddb` (npm, tests seulement) | 6.2.8 | Apache-2.0 | IndexedDB en mémoire sous Node, transactions et abandons compris |

## Choix

IndexedDB natif dans l'adaptateur existant, et `fake-indexeddb` en dépendance de développement pour les tests.
L'adaptateur n'écrit qu'une valeur sous une clé : une bibliothèque n'apporterait que des promesses, alors que le
point délicat, attendre `oncomplete` avant de confirmer, demande de tenir la transaction soi-même.

## Risques

- Le substitut en mémoire peut différer d'un navigateur réel (quotas, navigation privée) : le parcours
  Playwright reste la preuve en navigateur.
- Une erreur d'ouverture de base doit dégrader le jeu en partie non sauvegardée, pas le bloquer.

## Tests de qualification

- `tests/unit/storage.test.ts` : transaction abandonnée, ancien état conservé ; reprise en plein combat.
- `tests/unit/store-web.test.ts` : adaptateur web sur le substitut IndexedDB.
