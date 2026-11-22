# Agents — module specs

- Pour lire ou écrire le registre, passer uniquement par `./specctl`. Ne jamais éditer une fiche à la main : le journal et `ids.json` ne seraient pas tenus.
- Après toute écriture, lancer `./specctl index`. Les tests ciblés se lancent avec `python3 -m unittest discover -s specs/tests/<catégorie> -t .`.
- Une nouvelle spec de jeu va dans `registry/games/`. Pour une spec de plateforme, ajouter d'abord son projet à `fiche.PLATEFORME`.
- Avant de déplacer un chemin, mesurer qui le cite : CI, scripts, doc de homelab-docs (HL-525 7-3308).
