# Contribuer

Toute mutation du registre passe par une PR avec revue et CI obligatoires.
Sur L1, fournir les résultats des contrôles locaux dans la PR en attendant
les pipelines Woodpecker.

1. Lire les [règles agents](AGENTS.md) et respecter la liste des dépôts autorisés.
2. Pour modifier le catalogue, utiliser les schémas et l’écriture de
   `tools/core/catalog.py`. Garder les identifiants et leurs clés d’identité.
3. Rejouer les tests ciblés, puis la suite complète et la validation Git.

   ```sh
   python3 -m unittest tests.unit.test_oracles
   python3 -m unittest discover -s tests -t . -p 'test_*.py'
   ./assetctl validate --base main --json
   ```

4. Examiner `git status --short`. Ajouter les fichiers par leur nom, puis
   contrôler `git diff --cached`. Ne jamais utiliser `git add -A` ou `git add .`.
5. Ouvrir une PR avec des commits courts en français et les preuves pertinentes
   pour la revue. Conserver les sources et secrets privés.
