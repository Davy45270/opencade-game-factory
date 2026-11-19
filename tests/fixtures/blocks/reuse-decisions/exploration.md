# Exploration sur grille

| Candidat | Licence | Décision |
| --- | --- | --- |
| `moveOnMap` et `solveMap` du moteur | MIT | Réutiliser une seule règle de collision pour les pas et les itinéraires. Garder l'action de lieu pour les anciens journaux. |
| Cartes et collisions Phaser | MIT | Réutiliser sprites, tweens et atlas pour la projection. La collision et les portes restent dans le moteur pur. |

Les empreintes du décor décrivent le sol occupé par les illustrations, en cases inclusives du plan. Phaser projette ces cases sur le cadre complet du fond, qu'il affiche à l'échelle uniforme.
