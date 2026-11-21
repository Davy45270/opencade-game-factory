# Règles impératives du registre

1. SEARCH BEFORE CREATE ; REUSE BEFORE REINVENT.
2. Scanner l'existant avant tout nouvel asset ; ne jamais réimplémenter sans justification une fonction déjà disponible dans les outils ou bibliothèques libres.
3. Toute nouvelle ressource reçoit ID, description, origine, orientation, état, provenance et usages.
4. Aucune licence, origine, coordonnée ou compatibilité inventée.
5. Ne jamais écraser un asset publié ; versionner les variantes et dérivations.
6. Headless first ; aucune manipulation graphique humaine requise pour le pipeline nominal.
7. Ne pas modifier les jeux pendant l'inventaire initial.
8. Toute mutation passe par PR et CI ; ne pas contourner les tests.
9. Ne pas exposer les assets privés ni les secrets dans les dépôts publics.
10. Mettre à jour l'index des usages après tout ajout, modification ou suppression de référence dans un jeu.

## Rechercher et décider

1. Rechercher par description, tags et métadonnées. Affiner par similarité visuelle
   quand le fichier de référence et l’outil sont disponibles.
2. Inspecter les candidats, leurs usages et leur provenance. Vérifier orientation,
   état, style, format, qualité et licence pour le jeu cible.
3. Réutiliser l’ID existant si le candidat convient. Si une adaptation suffit, créer
   une dérivation avec `provenance.derivedFrom` et une clé fondée sur le SHA-256 de
   la recette. Conserver l’asset parent.
4. Pour une création, joindre `creation.searchReceipt` avec la requête et les
   candidats rejetés, chacun identifié et accompagné d’une raison. Un tableau vide
   indique une recherche sans candidat. Un import initial autorisé joint
   `creation.importJob`.
5. Exécuter `assetctl validate --base <ref-git> --json` avant la PR. Une fiche se
   consulte avec `assetctl inspect <id> --json` ; `assetctl search <texte> --receipt
   recu.json` produit le reçu exigé par `register`.

## Bibliothèques externes (EXT-001)

**OBLIGATOIRE :** Search internal → Search external → Reuse → Import → Derive → Create.

1. `assetctl search` d'abord ; puis `assetctl external search --query … --format json`. Une recherche
   externe `unavailable` ne prouve pas qu'aucun asset n'existe : ne pas créer sur cette seule base.
2. `assetctl external decide --query …` compare et rend `reuse`, `derive`, `import`, `create` ou `block`,
   avec la justification, les candidats consultés et la raison de chaque rejet. Recopier cette décision
   dans le rapport de tâche et dans la PR.
3. Ne jamais présumer la licence d'un pack : « gratuit » n'est pas CC0. Seul le texte de licence lu dans
   l'archive vérifie la licence annoncée ; sinon `unknown`, et la publication est bloquée.
4. Importer par `external plan-import` puis `external import --plan` : archive inspectée (chemins
   traversants, liens, exécutables, bombes ZIP refusés et mis en quarantaine), empreintes contrôlées,
   import transactionnel et idempotent.
5. Le module reste indépendant, désactivable (`ASSETCTL_EXTERNAL=off`) et entièrement headless.
6. Un asset externe peut remplacer un élément de planche si le style colle (arbitrage de David, HL-538
   7-2949) ; la preuve est un côte à côte avec la planche, joint au ticket du jeu.
