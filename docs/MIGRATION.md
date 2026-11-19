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

## Commandes de découverte

```sh
./assetctl scan-repos --provider local --only six-de-chaque --dry-run --json
./assetctl scan-repos --provider local --only six-de-chaque --json
./assetctl scan-repos --verify --provider local --only six-de-chaque --json
```

Démarrer les scans réels depuis un environnement autorisé. Les copies locales sont
lues par le transport Git `file://`. Les miroirs nus vivent dans
`~/.cache/opencade-asset-registry/mirrors` ou sous `--cache`. Un fichier passé
à `--sources` sélectionne des entrées de la liste canonique. Les jetons optionnels
`ASSETCTL_GITHUB_TOKEN` et `ASSETCTL_FORGEJO_TOKEN` restent dans l’environnement.

Le scan lit la branche par défaut et les commits pointés par les tags. `--job`
accepte le contrat §6 sans `inputs` et permet de choisir le fournisseur et le
périmètre des monorepos et releases. Les autres étapes du contrat décrivent le
pipeline complet. Les détections et rapports disponibles correspondent au lot
en cours. Les identités des fichiers reposent sur le SHA-256. Un module de dessin
emploie l'identité de son symbole ou du module entier lorsque la clé est dynamique.

`--verify` parcourt les commits précédemment recensés et consulte la tête du
dépôt distant. `--no-fetch` limite le scan et le contrôle aux miroirs locaux.
`--dry-run` rend les compteurs ou le résultat du contrôle sur stdout. S’il faut
un miroir pour ce mode, le cache temporaire est supprimé en fin de commande.
Les rapports et propositions de similitude sont produits sous `generated/`.

## Usages, planches et licences

Le graphe d’usage est calculé sur les blobs Git. Chaque usage conserve le
fournisseur de la copie, le commit, le chemin et la ligne de la référence. Un
tag est associé si le code et les fichiers de l’asset correspondent aux mêmes
blobs. Un cadre d’atlas chargé par son JSON dépend à la fois de la déclaration et
de la texture. Un scan ultérieur signale le retrait des assets utilisés dans
`generated/reports/removed-in-use.json` et conserve leurs usages historiques.
`assetctl index` reconstruit `usage-index.json` et les manifestes de licences
depuis le catalogue.

La résolution couvre les littéraux, les appels Phaser et les motifs Vite sur
l’arbre Git. Elle tient compte de `public/` et du paquet du module. Les
expressions dynamiques reconnues figurent dans `dynamic-refs.json`. Les alias de
build personnalisés et la propagation de valeurs entre modules restent hors
périmètre. Dans la couverture, `examined` compte les fichiers examinés sans
asset, notamment les modules sans dessin. Un JSX en `.tsx` ou `.jsx` peut
fournir des usages et du dessin par code. Un `.tsx` dont le document commence
par un élément Tiled `tileset` reste une ressource Tiled.

Pour une provenance de découpe, le SHA-256 fait foi. Sans empreinte dans la
table, le chemin relatif ou un nom de planche non ambigu doit permettre de
retrouver le blob. Un cadre est associé par ID (`sprite-<id>` ou `<id>`) et par
nom d’atlas lorsqu’il est fourni. Les associations ambiguës et les planches
indisponibles figurent dans `scan-limits`. Une planche connue par sa seule
empreinte a des dimensions inconnues et aucun emplacement. La vérification
compare le cadre recadré au résultat normalisé en Pillow. Les écarts de
rééchantillonnage avec ImageMagick peuvent affecter les mesures proches du
seuil. Les retouches masquées et les éléments déclarés comme dérivés conservent
cette provenance.

`generated/licenses.json` et `licenses.md` contiennent la décision d’export par
ressource. La licence d’un dépôt s’applique aux modules de dessin identifiés,
sous réserve de reconnaissance du texte de licence. Une planche entière est
réservée, y compris si elle figure aussi au catalogue comme fichier image. Les
licences explicites reconnues et les découpes qui satisfont HL-538 conservent
la référence au document Git.

L’enrichissement utilise les jetons du chemin, du nom et les entrées du
catalogue `jeux-assets` appariées par un préfixe de SHA-256 non ambigu. La
méthode `ai` est disponible dans le schéma. Aucune description par IA n’est
produite à ce stade.

## Extraction headless

```sh
./assetctl import-sheet planche.png --decoupe table.json --dry-run --json
./assetctl import-sheet planche.png --json
./assetctl extract sheet-exemple-0001 --candidates --json
./assetctl extract sheet-exemple-0001 --regions table.json --out sprites/ui --json
```

Une table locale décrit des éléments identifiés et leurs boîtes `[w,h,x,y]`.
Les sorties du mode candidat sont des propositions et restent hors catalogue.
Sur une planche d’un dépôt, `extract` lit le blob dans le miroir autorisé avec
le même `--cache` que le scan, si celui-ci utilise un cache personnalisé.
Une extraction explicite enregistre le fichier et sa région dans le catalogue
de travail. Avant intégration, un nouvel asset local reste soumis au reçu de
recherche exigé par `validate --base`. Une table locale seule laisse la licence
inconnue.

Pour une planche Aseprite, `ASEPRITE` permet de choisir le binaire batch. Le
registre essaie ensuite le binaire local prévu, puis LibreSprite si les
options précédentes sont indisponibles. Une dépendance absente donne le code 4. Les images
matricielles passent directement par Pillow.
