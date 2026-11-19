# Architecture

## Catalogue et stockage

`catalog/` est la source de vérité. Il contient une fiche JSON par asset, planche
ou univers dans `assets/`, `sheets/` ou `universes/`, ainsi que les fichiers
`sources.json` et `ids.json`. Le module `tools/core/catalog.py` écrit en UTF-8,
avec une indentation de deux espaces, les clés triées et un LF final. Le nouveau
fichier est écrit dans le même répertoire avant remplacement atomique.

`sources.json` est un tableau d’entrées avec le fournisseur (`github`, `forgejo`
ou `local`), le nom canonique `repo`, le rôle, les `games` et l’adresse `url`
ou le `path` local. Ce tableau définit le périmètre que L2 pourra lire. Les
localisations d’un fichier et les références de code décrivent un dépôt, un
commit et un chemin relatif à ce dépôt.

Les binaires des jeux restent dans les jeux. Le catalogue garde l’empreinte
SHA-256 et les emplacements d’origine. Le registre versionne ses propres
dérivations, extraits et planches sources, et limite ses vignettes à 96 px. Git
LFS reste une option pour les futures sources volumineuses. Le stockage par
référence aux dépôts évite de l’exiger en L1.

Les JSON de `generated/` et `build/registry.sqlite` sont des produits dérivés
reconstructibles à partir du catalogue seul (AT-12, L3). L’index utilise SQLite
FTS5 via la bibliothèque standard. L’architecture fonctionne sans service ni
base serveur.

## Outils

Python 3.11 ou supérieur fournit Git via subprocess, SQLite et les fondations
pour un outil headless testable avec `unittest`. Pillow et numpy serviront aux
traitements d’images. jsonschema applique Draft 2020-12. Les références entre
schémas sont résolues depuis les ressources embarquées.

`tools/cli` expose la CLI et `tools/core` contient les mécanismes partagés.
`tools/validate` vérifie les fiches, leurs relations et leur évolution.
`tools/discovery`, `tools/extract`, `tools/index` et `tools/publish` réservent
les points d’extension.

David a validé le 2026-11-19 l’usage de Woodpecker pour la CI. Les futurs
pipelines `scan.yml`, `validate.yml`, `build-index.yml` et `release.yml`
seront dans `.woodpecker/`.

## Identifiants immuables

Une clé d’identité représente un fichier (`file:sha256:<hex>`), une région
(`region:<sheetId>:<x>,<y>,<w>,<h>`), un symbole
(`code:<repo>:<chemin>#<symbole>`) ou une dérivation
(`derived:<parentId>:<recette-sha256>`). Les SHA-256 des clés sont en hexadécimal
minuscule et les coordonnées ont une écriture décimale canonique.

`IdRegistry.allouer` retrouve une clé existante avant de considérer le nom et la
catégorie. Une nouvelle clé reçoit `asset-<category>-<slug>-<NNNN>` ou
`sheet-<slug>-<NNNN>` avec la catégorie réservée `sheet`. La catégorie de l’ID
est un segment ASCII minuscule alphanumérique commençant par une lettre. Le slug
ASCII dérivé du nom fait au plus 32 caractères. Le compteur avance par préfixe
depuis 0001, jusqu’à 9999. Garder la fiche d’un asset retiré en `deprecated`
et conserver son entrée dans `ids.json`. L’allocation en mémoire laisse la
persistance au processus qui possède l’écriture du catalogue.

Avec `--base`, le validateur lit le registre et les chemins de fiches du
commit Git demandé. Il contrôle l’ajout seul et la conservation des fiches.
Chaque nouvel asset doit joindre un reçu de recherche ou, pour les types
`repo-file`, `original-sheet-cut` et `code-generated`, un job d’import
conforme au contrat initial-discovery. Les deux contrats sont embarqués dans
`creation`. Les rejets documentent l’ID et la raison. Une recherche sans
candidat a un tableau de rejets vide.

## Provenance, inférence et références

Pour chaque champ interprétable, une valeur connue porte une trace
`inference.<champ>` qui lie la valeur à sa preuve ou à sa méthode d’inférence.
Pour une valeur prouvée, utiliser `method: proven`, une confiance de 1 et
des éléments de preuve précis. Pour les inférences, conserver la méthode
(`path-tokens`, `catalogue-import`, `provenance-file`, `heuristic` ou `ai`),
une confiance entre 0 et 1 et les éléments qui permettent de revoir l’inférence.
La provenance globale décrit la ressource. Une trace par champ établit le lien
avec la valeur. Les valeurs inconnues sont explicites (`unknown` ou `null`
selon le champ). Un tableau de tags vide ne contient aucune assertion.

Une licence connue utilise un identifiant de la liste SPDX v3.27.0 et
`licenseEvidence`. Un export public exigera une licence vérifiée et une
autorisation. Une région reliée à un asset doit correspondre à sa planche, à ses
coordonnées et à son indicateur de vérification. Les usages retirés conservent
leurs références et les tags de releases. L’inspection d’une planche restitue
les usages des assets qui en proviennent.

## Codes de retour

| Code | Signification |
| --- | --- |
| 0 | Succès |
| 1 | Contrôle en échec ou fiche introuvable |
| 2 | Usage, arguments invalides ou commande prévue pour un autre lot |
| 3 | Refus de sécurité (licence, périmètre, lecture seule) |
| 4 | Erreur d’entrée/sortie ou dépendance indisponible |

Le journal JSON Lines est écrit sur stderr par défaut. `--log <fichier>`
ajoute les événements à un fichier extérieur au catalogue. Le résultat
`--json` est écrit sur stdout.
