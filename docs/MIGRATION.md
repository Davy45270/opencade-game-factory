# Migration initiale

Avant la migration, confirmer les dépôts autorisés et leurs accès en lecture, les jeux
qui publieront leur manifeste et la politique d’export vers les jeux publics. Reporter
l’inventaire si le périmètre autorisé reste indéterminé. Inscrire chaque dépôt dans
`catalog/sources.json` et préparer un job conforme à `schemas/import-job.schema.json`.

## Découverte et contrôle

1. Obtenir la liste des organisations, dépôts et monorepos autorisés ; ne jamais parcourir des dépôts hors périmètre.
2. Scanner les branches par défaut, les releases demandées, les répertoires de jeux et les manifests de build ; distinguer jeu, bibliothèque partagée et contenu généré.
3. Détecter PNG, JPEG, WebP, GIF, SVG, Aseprite, atlas JSON, tilemaps Tiled, fichiers audio, polices, shaders et assets déclarés en TypeScript/Canvas/Phaser.
4. Analyser statiquement les références de ressources dans le code et les configurations ; journaliser les références dynamiques non résolues.
5. Dédupliquer par hash sans effacer les références distinctes ; proposer des regroupements de variantes par similarité.
6. Extraire les spritesheets à partir de leurs métadonnées si elles existent ; en leur absence, proposer des régions candidates et conserver le statut `needs-review`.
7. Enrichir descriptions, orientations et états par analyse automatisée ; garder une confiance et la preuve de l'inférence.
8. Vérifier provenance/licence ; `unknown` interdit toute redistribution publique tant que non résolu.
9. Importer de manière idempotente dans le registre, construire index et rapport de migration.
10. Effectuer un second scan de contrôle pour confirmer l'absence de ressources oubliées parmi les formats pris en charge.

Pour chaque dépôt, noter les commits et tags inspectés. Ventiler le rapport entre
ressources importées, exceptions et références dynamiques non résolues. Comparer
les empreintes des sources avant et après l’inventaire. Rejouer avec les mêmes
commits et vérifier la stabilité des identifiants. Réserver les données spécifiques
au registre aux dossiers `sources/`, `sprites/`, `atlases/` et `thumbnails/`.

L1 fournit les contrats et l’autorisation initialement vide. L’exécution de la
migration dépend des outils de découverte et d’indexation des lots suivants.
