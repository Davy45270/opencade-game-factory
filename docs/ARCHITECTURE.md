# Architecture

## Catalogue et stockage

`catalog/` est la source de vérité. Il contient une fiche JSON par asset, planche
ou univers dans `assets/`, `sheets/` ou `universes/`, ainsi que les fichiers
`sources.json` et `ids.json`. Le module `tools/core/catalog.py` écrit en UTF-8,
avec une indentation de deux espaces, les clés triées et un LF final. Le nouveau
fichier est écrit dans le même répertoire avant remplacement atomique.

`sources.json` décrit le périmètre autorisé. Chaque entrée de `sources` associe
un nom canonique, un rôle et des jeux à ses copies GitHub, Forgejo ou locales.
Chaque copie porte une adresse et une visibilité. Les localisations du fichier
importé gardent le fournisseur, le commit, le chemin relatif et l’état de
l’emplacement. `catalog/scan-references.json` conserve les commits contrôlés
par `scan-repos --verify`.

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
conforme au contrat initial-discovery. `creation.importJob` pointe vers un
document de `catalog/import-jobs/` dont le nom est calculé sur les entrées Git.
Le validateur accepte aussi les contrats embarqués des fiches L1. Les rejets
documentent l’ID et la raison. Une recherche sans
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
| 4 | Source indisponible : erreur d’entrée/sortie, réseau, dépendance ou miroir injoignable |
| 5 | Conflit de versions : catalogue, registre d’identifiants ou base modifiés entre la lecture et l’écriture |

Cette table est **commune à toutes les sous-commandes** et aux CLI à venir de l’usine (`specctl`, niveaux, briques),
alignée sur celle de `specctl` (REG-003) : 0 succès, 1 contrôle, 2 usage, 3 refus, 4 source indisponible, 5 conflit
de versions. Un module ne crée pas son propre code ; un cas nouveau s’ajoute ici. Les codes de la spec EXT-002
(`levelctl` : 3 référence absente, 4 validation échouée, 5 droits, 6 simulation indéterminée, 7 infrastructure) se
rangent dans cette table : référence absente et validation échouée → 1, droits → 3, infrastructure → 4 ; une
simulation indéterminée (`inconclusive`) n’est jamais un succès et rend 1, avec `status: inconclusive` dans le JSON.

Le journal JSON Lines est écrit sur stderr par défaut. `--log <fichier>`
ajoute les événements à un fichier extérieur au catalogue. Le résultat
`--json` est écrit sur stdout.

## Modules à venir : le dépôt unique de l’usine

Décision de David (HL-525 7-2955) : ce dépôt devient le dépôt unique de l’usine, avec un module par domaine, la même
CLI et la même CI Woodpecker :

| Module | Spec | État |
| --- | --- | --- |
| `assets` | OpenCade Asset Registry v1.0, EXT-001 | P0 en cours (code actuel de `tools/`) |
| `levels` | EXT-002 Level & World | après EXT-001 ; validateurs puzzle, puis RPG et donjon |
| `specs/` | REG-003 Specification Registry | à venir (analyse des écarts, HL-525 7-2957) |
| `blocks/` | BB-001 Building Blocks | à venir |

Règles qui le permettent dès maintenant : `tools/core/` reste générique (catalogue, identifiants, journal, codes de
retour communs) ; ce qui est propre aux assets vit dans les autres paquets de `tools/` ; rien n’est renommé avant la
décision de renommage, prise après le lot L3.

