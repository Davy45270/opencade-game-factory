# Manifestes de projets

Le manifeste d'un projet, c'est la spec qu'il consomme et sa version. `./specctl resolve --project <p>` le calcule depuis le registre, et `./specctl lock` le fige pour une PR. Le manifeste figé vit dans le dépôt du jeu, sous `.woodpecker/usine.json` : sa CI le relit à l'étape `spec résolue` du gabarit. Ce dossier ne recopie aucun manifeste, pour éviter une deuxième source de vérité.
