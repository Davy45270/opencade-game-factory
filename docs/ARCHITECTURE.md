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

Chaque version livrée par `publish` conserve ses octets dans le dépôt privé,
sous `published/sha256/<sha256><ext>`. Le premier export d’un SHA-256 fixe le
nom employé par les exports suivants de ces mêmes octets. L’entrée de version
enregistre ce chemin et la preuve de publication. Les fichiers du magasin
sont ajoutés sans remplacement et `validate --base` contrôle leur conservation.
Ajouter les fiches et binaires publiés au même commit du registre.

Les instantanés JSON de `generated/` et `build/registry.sqlite` sont des produits
dérivés. `catalog/` et `published/` sont des sources versionnées. L’index utilise SQLite
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

Une clé d’identité représente un fichier (`file:sha256:<hex>`), une planche
(`sheet:sha256:<hex>`), une région
(`region:<sheetId>:<x>,<y>,<w>,<h>`), un symbole
(`code:<repo>:<chemin>#<symbole>`) ou une dérivation
(`derived:<parentId>:<entree-sha256>`). La clé de la première révision du
parent utilise l’empreinte de la recette. Les révisions suivantes intègrent
aussi le numéro et le SHA-256 du parent. Les SHA-256 des clés sont en hexadécimal
minuscule et les coordonnées ont une écriture décimale canonique. Une fiche de
planche et une fiche de fichier héritée de l’inventaire peuvent donc pointer vers
le même contenu avec deux identités distinctes.

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

## Versions des assets et de leurs variantes

Une variante ou dérivation garde sa propre fiche et son lien à l’asset parent.
Chaque fiche porte `version`, le numéro courant, et `sha256`, son empreinte.
`versions` contient les empreintes par numéro croissant, avec les liens
`previousVersion` et `nextVersion`. Les deux extrémités ont un lien nul.
Les numéros sont immuables une fois inscrits. Les liens `causalPrevious`
et `causalNext` désignent les voisins immédiats qui ressortent de l’ascendance
des commits Git, et peuvent remonter ou descendre dans les numéros. Une
extrémité ou une relation dont les objets Git sont indisponibles donne un lien
nul. Les entrées portant des commits incomparables ont deux liens nuls et
`causalOrder: "incomparable"`. Plusieurs voisins immédiats possibles donnent
`causalOrder: "ambiguous"` et deux liens nuls.
Une fiche L1–L3 se lit comme une version 1 implicite. Le scan suivant inscrit
cette version dans le catalogue, avec un résultat identique au scan suivant
sur les mêmes commits. `validate` contrôle les liens, l’empreinte courante et les
numéros cités par les emplacements et les usages. `validate --base` vérifie
aussi la conservation des versions déjà enregistrées.

Le numéro de version est local à la fiche. La clé de `ids.json` reste celle
de l’allocation initiale et l’historique des empreintes vit dans la fiche.
Le registre d’IDs conserve une clé d’allocation immuable par ID. Une fiche
d’atlas héritée peut recevoir un alias d’identité en ajoutant une clé
`alias:atlas:…`, en conservant sa clé de région initiale.
Le scan reconnaît une lignée par source logique et chemin, ou par un
`assetId` déjà associé à cette source et déclaré par le lock du commit pour le
chemin et le SHA-256 observés. Un déplacement de contenu identique dans la
même source conserve l’ID et le numéro. Les copies d’une même source
restent soumises à la sélection de la branche par défaut et au signalement
des divergences.

Les contenus identiques se regroupent par empreinte dans le rapport de
doublons. Deux sources logiques peuvent faire évoluer ces contenus
indépendamment. Quand la clé `file:sha256:<hex>` est déjà prise, l’allocateur
peut employer `file:source:<sha256-du-nom-de-source>:<sha256-du-contenu>`.
Pour une fiche héritée déjà partagée entre sources logiques, le premier nom
de source par ordre lexical conserve la lignée en cas de changement et un
contenu divergent d’une autre source ouvre sa propre lignée. Les usages
antérieurs restent associés aux fiches qui les ont enregistrés. Si deux
chemins d’une même source partagent un ID et que l’un diverge, ce chemin ouvre
sa propre lignée et les références historiques conservent leur couple ID–version.

L’identité d’un sprite d’atlas associe la source logique, le chemin du fichier
d’atlas et le nom du cadre. La planche, son SHA-256 et les coordonnées sont
des preuves dans l’entrée de version. Une retouche hors de la découpe ajoute
une preuve pour le même contenu. Une retouche de la découpe crée une version
sous le même ID.

Les emplacements et usages issus d’un scan indiquent `assetVersion`. Un tag
observé sur un ancien contenu au même chemin référence sa version sur la
même fiche. Au premier import, les versions trouvées sur d’anciens tags
précèdent celle de la branche par défaut. Un tag découvert plus tard peut
ajouter une entrée historique en fin de liste, avec son commit et sa date.
La fiche garde alors son numéro courant et les numéros déjà utilisés dans
les locks. Une version publiée remplacée conserve la preuve de publication
dans son entrée, avec le chemin du binaire enregistré lorsqu’il existe.

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


## Recherche et livraison

`assetctl index` reconstruit les instantanés du catalogue, l’index des usages,
l’index de recherche et la base FTS5. Le résultat contient
`catalogFingerprint`, l’empreinte des JSON de `catalog/`, et `fingerprint`,
l’empreinte des fichiers produits sous `generated/`. Les rapports de scan
conservent leurs propres entrées. `search` reconstruit la base SQLite si
l’empreinte du catalogue change. Les filtres sont exacts. `--used-by` retient
les usages actifs et chaque résultat restitue aussi les usages historiques.
`--similar-to` classe les résultats par distance de Hamming du pHash.

`search --receipt chemin.json` enregistre l’empreinte, la requête, ses filtres
et tous les IDs correspondants, y compris ceux masqués par `--limit`.
`register` exige ce reçu, daté des sept derniers jours, et un
`--reject ID:raison` pour chaque candidat. Le reçu correspond au catalogue
courant. Un catalogue plus récent est admissible si les deux instantanés
sont vérifiables dans des commits Git de la même lignée.

`derive --recipe chemin.json` prend un objet avec les transformations
`crop` (`{x,y,w,h}`), `mirror` (`true`, `false`, `horizontal` ou
`vertical`), `resize` (`[largeur,hauteur]`) et `tint` (couleur
`#RRGGBB`). Il les applique dans cet ordre et emploie le SHA-256 des octets
de la recette et la révision courante du parent pour allouer l’ID. La
provenance inscrit `parentId`, `parentVersion` et `parentSha256`. Une preuve de licence autorisant
l’adaptation permet d’hériter de la licence.

`usage add` écrit le lock à la racine du jeu et matérialise l’asset au
chemin demandé, sous `assets/` par défaut. Une fiche sans version explicite
a pour `assetVersion` la chaîne `"1"`. Pour une fiche versionnée, le lock
enregistre le numéro courant sous forme de chaîne. Pour créer un lock
vérifiable, commiter la révision de l’asset dans le registre avant
`usage add`. `check-lock` vérifie le couple numéro–empreinte dans le catalogue
et dans le commit `registryCommit`, puis le SHA-256 du fichier relatif au
dossier du lock. Un couple historique valide émet l’avertissement
`non-current-version`. `inspect --json` restitue l’historique.
L’index de recherche et `search` rendent le numéro et l’empreinte courants.
Les fichiers proviennent du registre
ou des objets Git des miroirs. Les découpes d’atlas importées sont
reconstruites depuis leur cadre et leur planche. Dans chaque cas, le
SHA-256 est contrôlé avant écriture. Une cible privée est déclarée dans
`catalog/sources.json` ou indiquée explicitement par `--private-target`.
La preuve `P14-assets-lock` s’obtient avec `check-lock`. Son option
`--public` applique la garde à la version verrouillée, y compris sa preuve
de publication archivée lorsqu’elle est historique. Un écart de commit,
de version ou de fichier renvoie le code 1. Un refus de licence renvoie le code 3.

`materialize <id> --version <n> --to <dossier>` livre le nom formé de l’ID
et de l’extension de cette révision. Il accepte aussi un chemin de fichier
explicite. Les révisions publiées sont lisibles après purge des miroirs.
Une révision dont les octets sont indisponibles renvoie le code 4.

`sync` compare les branches par défaut et les cartes nom–commit des tags
aux références enregistrées. Les changements de tags déclenchent une analyse
même à tête inchangée. Pour un même nom de tag, parmi les copies retenues
pour l’import, le commit descendant de tous les autres l’emporte. Si les
commits divergent, la priorité est GitHub, Forgejo, puis local. Le rapport de
migration consigne chaque candidat dans `divergentTags`. Le scan lit les
arbres et les blobs des copies à importer et
conserve les usages des copies inchangées. Il part de `main` ou du dernier
commit de la même branche `sync/…` si celle-ci descend de `main`. Le scan se
fait dans un clone temporaire et la branche de synchronisation se met à
jour localement après succès. Les divergences et les suppressions sont
signalées dans les rapports. `scannedCopies` compte les copies dont le
contenu a été analysé.

`export-atlas --out atlases/nom` produit `nom.png` et `nom.json` au
format Phaser JSON Hash. `validate-atlas` contrôle les références, les
dimensions, les limites et la transparence. `sbom --out
generated/sbom.cdx.json` décrit les dépendances directes épinglées dans
`requirements.txt`. Le manifeste des licences d’assets reste dans
`generated/licenses.json`.
