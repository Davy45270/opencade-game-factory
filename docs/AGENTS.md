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
