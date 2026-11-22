# Cartes et parcours

## Besoin

Valider les plans d'origine (32×24, bords fermés, spawn libre, marqueurs atteignables) et calculer collisions,
sorties et atteignabilité dans le moteur, sans navigateur.

## Candidats

| Candidat | Licence | Décision |
| --- | --- | --- |
| Schéma de carte d’origine, graphe et transitions du moteur | MIT dans le dépôt | Réutilisés pour valider les plans et arbitrer les transitions du slice. |
| Phaser, déjà présent côté rendu | MIT | Réservé au rendu. Le moteur calcule les collisions et l’atteignabilité sans navigateur. |

## Choix

Le schéma d'origine et le moteur du dépôt. La recherche sur la grille utilise une file FIFO et un ensemble de cases
déjà vues. Elle partage le format de la carte avec le moteur. Le rejeu utilise le déplacement public et vérifie la
destination après chaque recherche.

## Risques

- Les plans livrés n'ont presque pas de murs intérieurs : la recherche est peu exercée par le contenu réel.
- Une sortie conditionnelle n'est sûre que si la campagne passe par le même filtre que la carte.

## Tests de qualification

- `tests/unit/source-maps.test.ts` : contrôle de chaque plan, murs, coffres, validateur.
- `tests/unit/sorties-conditionnelles.test.ts` : sorties présentes fermées sans leur drapeau.
- `tests/unit/mvp-world.test.ts` : lieux du graphe sur les plans et liaisons entre régions.
