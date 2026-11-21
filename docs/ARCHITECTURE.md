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
enregistre ce chemin et la preuve de publication (licence, provenance et
autorisation éventuelle). Republier la même révision exige la même preuve.
`validate` contrôle l’adresse et l’empreinte du binaire. `validate --base`
contrôle la conservation des octets et de la preuve. Une preuve historique
antérieure au magasin peut être archivée sans adresse.
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
extrémité sans voisin donne un lien nul. Les entrées portant des commits
incomparables ont deux liens nuls et `causalOrder: "incomparable"`. Plusieurs
voisins immédiats possibles donnent `causalOrder: "ambiguous"` et deux liens
nuls. Si une comparaison est indisponible pendant le recalcul, les versions
de la fiche passent à `causalOrder: "unknown"` avec des liens nuls. Les liens
inscrits sont réciproques et sans cycle.
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
des divergences. `catalog/scan-references.json` enregistre la dernière
tête importée de chaque source logique. Le scan n’accepte qu’une tête égale
ou descendante, même si un filtre fournisseur ou un miroir indisponible
réduit les copies candidates. Si la continuité ne peut être établie pour une
source sélectionnée, le scan renvoie 4 avant de modifier le catalogue. Avec
un historique antérieur à ce suivi, les têtes importées encore enregistrées
pour cette source servent de références.

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

Les paires « similaires » (pHash à 8 bits ou moins) sont statuées par une mesure, jamais fusionnées : écart moyen
par pixel des deux binaires du registre, composés sur gris moyen et réduits à 64 × 64 par moyenne d'aire en numpy
pur (`dedup.rule`), pour que `generated/duplicates.json` soit le même sur toute machine. Le plafond du bruit,
6,8 / 255, vient de 400 rééchantillonnages à ±10 % d'une même image (maximum mesuré 6,73). Au-dessus, la paire est
`distinct`. En dessous, c'est la même image à la précision du rééchantillonnage : un tel quasi-doublon devient une
variante liée (chacun nomme l'autre dans `variants`), jamais une suppression d'un dessin, et la paire est alors
`linked-variant` ; tant qu'il n'est pas lié, il reste `needs-review`. Sans binaire lisible, la paire reste
`needs-review` sans distance.

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
`licenseEvidence`. La seule référence hors liste admise est
`LicenseRef-David-Prive-Tous-Droits-Reserves` (texte dans `LICENSES/`, décision HL-538 7-3162) :
licence privée de David, non dérivable. Elle passe vers un jeu dont toutes les copies sont privées.
Vers une destination publique, une règle centrale unique (`GAME_GRANT`, décision de David du 2026-11-21,
HL-538 : « autorise pour tous mes jeux sans exceptions ») l’admet à travers tout dépôt de rôle `game` de
`catalog/sources.json` — le registre n’inventorie que les dépôts de David — pour ce que ce jeu emploie
(`usage add`, `materialize`, `check-lock --public`). Un dépôt public qui n’est pas un jeu de David est refusé ;
`publish --target public` n’a pas de jeu et la refuse toujours ; une planche source reste refusée.
Test : `test_l10_licence_privee`. Un export public exigera une licence vérifiée et une
autorisation. Un identifiant SPDX dans une déclaration de découpe ne peut
attribuer de licence qu’après vérification de la découpe. Une région reliée
à un asset doit correspondre à sa planche, à ses
coordonnées et à son indicateur de vérification. Les usages retirés conservent
leurs références et les tags de releases. L’inspection d’une planche restitue
les usages des assets qui en proviennent.

Pour une découpe dont la provenance déclare `source_retouche`, le scan lit le
fichier `*.retouches.json` dans le même commit Git que la déclaration. Il étire
chaque bande de la découpe initiale, puis la colle sur sa cible dans l’ordre
déclaré. Il normalise ensuite la découpe et compare les pixels au cadre
d’atlas avec le seuil RMSE de 0,02. La provenance reste `derived`. Une recette
illisible ou une géométrie invalide rend la comparaison indisponible et
produit une entrée `declared-retouch-unreadable` dans `scan-limits`. Une recette
valide sans raccord produit `declared-retouch-without-raccords`. La mesure
exige une couverture strictement inférieure à 75 % et au moins 1 024 pixels
hors raccord dans la découpe avec sa marge effective. Chaque pixel de l’union
des cibles compte une seule fois. Un refus laisse la RMSE absente et inscrit
`raccord-target-coverage-exceeded` ou `raccord-outside-pixels-below-minimum` dans
`scan-limits`.

Arbitrage du coordinateur du 19 novembre 2026 (HL-538) « plafond à 75 %
exclusif et plancher de 1 024 px hors raccord. C'est le plancher absolu qui
porte la preuve. » Sur les 14 entrées à raccords mesurées dans capsule-panic,
12 couvrent de 0,146 à 0,398 de la découpe, et les deux autres 0,530 et 0,697.
Le minimum hors raccord est de 3 605 pixels et la médiane de 4 840 pixels.
Les masques de silhouette décrits dans `transformations` sont hors périmètre.

Une recette déclarant `outils.magick` au format `N.N.N` ou `N.N.N-N` utilise ImageMagick
pour le recadrage avec marge, la mise à zéro de l’alpha sous 4 %, le rognage,
le redimensionnement et le placement dans le cadre selon l’ancre. La preuve
RMSE indique `tool: "magick"` et la version retournée par `magick -version`.
L’absence de l’outil, une majeure différente ou un échec de la commande
rendent la mesure indisponible et sont consignés dans `scan-limits`.
Sans version déclarée, la normalisation utilise Pillow.

Une source de `catalog/sources.json` peut déclarer
`"pathAliases": [{"from": "public/assets/*.png", "to": "assets/export/*.png"}]`.
Chaque motif est relatif à la racine Git et contient un seul `*` dans le nom
de fichier. Le scan applique la table aux références d’atlas `meta.image`
et `atlas` de la provenance après échec de la résolution directe. La même
portion du nom remplace l’astérisque dans le chemin cible. Un résultat unique
dans le même arbre Git est requis. Le scan consigne le chemin cité et le
chemin résolu, avec le dépôt, le commit et le fichier déclarant la référence,
dans `generated/reports/path-aliases.json` et son équivalent Markdown.

### Images générées par code

Dans `catalog/sources.json`, une source peut déclarer
`"generatedResources": [{"path": "public/icons/icon-*.png", "generator": "scripts/icons.js", "mentions": ["public/icons/icon-"]}]`.
Les chemins sont relatifs à la racine Git. Le chemin de sortie peut être
littéral ou contenir un astérisque dans le nom de fichier, comme pour
`pathAliases`. Pour une image raster prise en charge ou un SVG, le scan lit
le générateur au commit importé et vérifie chaque fragment par correspondance
littérale dans ses octets.

L’image conserve sa famille de format. Sa provenance `code-generated`
contient `generator.path`, `generator.commit` et `generator.sha256`, et les
champs communs de planche et région valent `null`. La famille `code-generated`
désigne un module de dessin ou un symbole de ce module inventorié comme code.
La déclaration sépare l’identité de la sortie de celle des autres chemins
de mêmes octets pour que chacun conserve ses propres droits.

La licence du dépôt est lue dans `LICENSE` ou dans `package.json` à la racine
du même commit. Le registre reconnaît les textes MIT, Apache-2.0, ISC et
BSD-3-Clause, ainsi que les identifiants SPDX admis par le schéma sous la
forme `SPDX-License-Identifier` ou dans la propriété `license` du manifeste.
La preuve cite `LICENSE` quand ce fichier établit la licence et
`package.json` quand le manifeste seul l’établit. Une divergence entre les
deux fichiers, une licence indéterminée, un générateur indisponible, un
fragment absent ou des déclarations incompatibles laissent la licence à
`unknown`. Le rapport `scan-limits` cite chaque sortie concernée et son motif.
Les révisions déjà publiées conservent leur preuve de publication.

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
de versions. Un module ne crée pas son propre code ; un cas nouveau s’ajoute ici.

**Seule exception : `assetctl level` (EXT-002, `levelctl`)**, dont la spec fixe ses propres codes (06_CLI_AGENTS) et
qui les rend tels quels (`tools/levels.LevelExit`). Correspondance vers la table commune, pour un appelant qui
enchaîne plusieurs modules :

| Code `level` (spec EXT-002) | Signification | Code commun équivalent |
| --- | --- | --- |
| `0` | Succès | 0 |
| `2` | Entrée invalide : arguments, version non semver, ID ou version déjà pris avec un autre contenu, archive dangereuse | 2 (usage) ; 5 pour une version ou un ID déjà pris ; 3 pour une archive dangereuse |
| `3` | Référence absente : niveau inconnu, asset EXT-001 introuvable | 1 |
| `4` | Validation échouée (structure, solvabilité, simulation, couverture de `discover`) | 1 |
| `5` | Droits ou licence bloquants | 3 |
| `6` | Simulation ou validation indéterminée (`inconclusive`, budget épuisé) : jamais un succès | 1 |
| `7` | Erreur d’infrastructure : git, source illisible, module désactivé (`ASSETCTL_LEVELS=off`) | 4 |

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
`detour` (`{"tolerance": 0…255}` : le fond uni relié au bord devient
transparent ; la couleur des quatre coins fait foi, et des coins discordants
font refuser la recette au lieu de deviner un fond), `crop` (`{x,y,w,h}`), `mirror` (`true`, `false`, `horizontal` ou
`vertical`), `resize` (`[largeur,hauteur]`) et `tint` (couleur
`#RRGGBB`). Il les applique dans cet ordre et emploie le SHA-256 des octets
de la recette et la révision courante du parent pour allouer l’ID. La
provenance inscrit `parentId`, `parentVersion` et `parentSha256`. Une preuve de licence autorisant
l’adaptation permet d’hériter de la licence.

Une preuve de licence héritée suit la chaîne des révisions parentes citées
par ID, numéro et SHA-256. Chaque parent doit encore porter la même licence,
avec une preuve et une autorisation d’export admissibles. Pour un lock
public, toute la chaîne est lue au `registryCommit` attesté. Pour
`materialize` et `publish`, le contrôle utilise le catalogue de travail.

Les chemins fournis à la CLI sont relatifs au répertoire courant de
l’appelant. Dans `usage add`, `--path` désigne le chemin inscrit dans le lock
et reste relatif à la racine du jeu désigné par `--repo-dir`. Les destinations
restent soumises au périmètre de chaque commande.

`usage add` écrit le lock à la racine du jeu et matérialise l’asset au
chemin demandé, sous `assets/` par défaut. Une fiche sans version explicite
a pour `assetVersion` la chaîne `"1"`. Pour une fiche versionnée, le lock
enregistre le numéro courant sous forme de chaîne. `usage add` refuse avec
le code 3 si `catalog/` a des changements non commités ou si HEAD ne contient
pas les versions et empreintes du lock à écrire. Avant toute écriture,
`usage add` vérifie les octets de chaque fichier référencé par le lock
résultant et, pour une cible publique, les droits de chaque révision dans HEAD.
`check-lock` vérifie le
couple numéro–empreinte dans le catalogue et dans le commit `registryCommit`,
puis le SHA-256 du fichier relatif au
dossier du lock. Un couple historique valide émet l’avertissement
`non-current-version`. `inspect --json` restitue l’historique.
L’index de recherche et `search` rendent le numéro et l’empreinte courants.
Les fichiers proviennent du registre
ou des objets Git des miroirs. Les découpes d’atlas importées sont
reconstruites depuis leur cadre et leur planche. Dans chaque cas, le
SHA-256 est contrôlé avant écriture. Une cible privée est déclarée dans
`catalog/sources.json` ou indiquée explicitement par `--private-target`.
La preuve `P14-assets-lock` s’obtient avec `check-lock`. Son option
`--public` applique la garde aux droits et aux planches du commit
`registryCommit`. Pour une version historique à ce commit, la garde utilise
la preuve de publication archivée. Un écart de commit,
de version ou de fichier renvoie le code 1. Un refus de licence renvoie le code 3.

`materialize <id> --version <n> --to <dossier>` livre le nom formé de l’ID
et de l’extension de cette révision. Il accepte aussi un chemin de fichier
explicite. Les révisions publiées sont lisibles après purge des miroirs.
Une révision dont les octets sont indisponibles renvoie le code 4.

`sync` compare les branches par défaut, les cartes nom–commit des tags et
les tables `pathAliases` et `generatedResources` effectives aux références
enregistrées. Un changement de tags ou de table déclenche une analyse même à
tête inchangée. Une référence enregistrée sans la table des alias est relue
une fois. Pour un même
nom de tag, parmi les copies retenues pour l’import, le commit descendant de
tous les autres l’emporte. Si les
commits divergent, la priorité est GitHub, Forgejo, puis local. Le rapport de
migration consigne chaque candidat dans `divergentTags`. Le scan lit les
arbres et les blobs des copies à importer et
conserve les usages des copies inchangées. Il part de `main` ou du dernier
commit de la même branche `sync/…` si celle-ci descend de `main`. Le scan se
fait dans un clone temporaire et la branche de synchronisation se met à
jour localement après succès. Les divergences et les suppressions sont
signalées dans les rapports. `scannedCopies` compte les copies dont le
contenu a été analysé.

`sync --open-pr --forge-repo propriétaire/dépôt` pousse ensuite la branche
`sync/…` (jamais `main`, jamais en force) et ouvre la PR vers `main` avec
`generated/reports/sync-pr.md` pour description. Rejouée, elle retrouve la
PR déjà ouverte au lieu d’en créer une autre. Le jeton vient de
`ASSETCTL_FORGEJO_TOKEN` ; absent, rien n’est poussé et la commande rend 4.
`--forge-url` et `--pr-remote` désignent une autre forge ou un autre dépôt.

`export-atlas --out atlases/nom` produit `nom.png` et `nom.json` au
format Phaser JSON Hash. `validate-atlas` contrôle les références, les
dimensions, les limites et la transparence. `sbom --out
generated/sbom.cdx.json` décrit les dépendances directes épinglées dans
`requirements.txt`. Le manifeste des licences d’assets reste dans
`generated/licenses.json`.

## Bibliothèques externes (EXT-001)

Le paquet `tools/external/` porte le module de la spec EXT-001 (la spec le nomme
`packages/external-discovery/` et l'écrit en TypeScript ; le registre est en Python). Interfaces :
`ProviderAdapter` et `ExternalIndex` (`adapters.py`), `LicenseEvaluator` (`licenses.py`),
`DownloadManager` (`download.py`), `ImportPlanner` et `ImportExecutor` (`importer.py`),
`ImportDecision` (`decision.py`). Rien hors de `assetctl external` ne l'importe :
`ASSETCTL_EXTERNAL=off` le désactive (code 2) sans toucher la recherche ni les imports internes.

Un fournisseur se lit par son index de packs, `external/<fournisseur>/index.json`, ou le chemin ou
l'URL de `ASSETCTL_EXTERNAL_INDEX_<FOURNISSEUR>`. Kenney est le seul fournisseur P0 actif. Une URL
d'index qui porte un identifiant ou un jeton est refusée. Les téléchargements sont en HTTPS (ou
`file://`), bornés en taille et en durée, repris trois fois, au plus une requête par seconde et par hôte.

`plan-import` télécharge l'archive, l'inspecte, lit son texte de licence, cherche d'abord dans le
registre interne et écrit le plan (`schemas/external-import.schema.json`) avec la décision. `--dry-run`
n'écrit ni quarantaine ni fiche ; le plan n'est écrit que si `--out` est donné. `import --plan` est
la seconde étape, différée et rejouable : il exige la même archive à l'octet et le même verdict de
licence, puis écrit en une transaction les binaires adressés par SHA-256
(`sources/external/sha256/`), l'archive d'origine (`sources/external/archives/`), le texte de
licence (`sources/external/licenses/`), les fiches et leurs identités
`external:<fournisseur>:<pack>:<version>:<sha256>`. Un même fichier venu de deux packs donne deux
fiches (deux provenances) pour un seul binaire. Relancé, l'import ne crée rien.

`external sync --from <nouvel index>` signale les packs nouveaux, mis à jour et retirés ; un
changement de licence ou un retrait à la source s'ajoute à `provenance.external.licenseHistory` ou
`sourceStatus`, sans changer la licence ni les versions déjà importées. `external audit-licenses`
rend 1 si une fiche externe déclare une licence que son pack n'a pas prouvée. Chaque export public
(`publish --target public`) écrit `THIRD_PARTY_ASSETS.md` et `provenance.json`.


## Niveaux et mondes (EXT-002)

Le paquet `tools/levels/` porte le module de la spec EXT-002 ; `assetctl level …` tient lieu de `levelctl` (dépôt
unique de l'usine, HL-525 7-2955). Les fiches vivent dans `catalog/levels/` (schéma `schemas/level.schema.json`,
repris du contrat de la spec et complété par la provenance, le contenu normalisé, `losses`, `observations` et
`versions`), les originaux dans `originals/sha256/`, les versions publiées dans `published/levels/<id>/<version>.json`.
`ASSETCTL_LEVELS=off` désactive le module sans toucher au registre d'assets.

- `discover --scope repos.json` lit les dépôts (ou leurs sous-jeux, `games: {préfixe: jeu}`) sans les écrire :
  empreintes avant et après (`sourcesUnchanged`), formats `.tmx .tsx .tmj .json .ldtk .ldtkl .lua .ts .js .py .xml
  .blend`, références de niveaux par AST (Python) ou motifs (autres), générateurs avec leurs paramètres, constructions
  dynamiques signalées `unresolved`, doublons de structure proposés et jamais fusionnés ; tout fichier détecté est
  inventorié, en exception (avec motif) ou ignoré (avec motif) : `coverage.ratio` vaut 1.
- `import --source local --repo <clone> [--ref <sha>]` ou `--source archive --archive <zip>` : clé d'idempotence
  `{provider, repo, commit, path, contentSha256}` ; un même fichier à un nouveau commit garde son ID et ajoute une
  observation. La licence n'est `verified` que si le texte de licence lu dans la source confirme l'identifiant
  déclaré (même évaluateur qu'EXT-001) ; sinon `unknown`, et `publish` rend 5. Une archive dangereuse va en
  quarantaine. Les sources distantes passent par un clone local (`scan-repos` tient le miroir).
- Formats : Tiled JSON et TMX (couches, gids bruts avec drapeaux de retournement, propriétés, objets, décalages,
  tilesets externes `.tsx`), LDtk (IntGrid, entités et leurs champs, `defs`, disposition du monde, niveaux externes
  `.ldtkl`). Chaque conversion rend `losses[]`, même vide ; `to_tiled_json` fait l'aller-retour.
- Conventions lues dans la carte : couche de tuiles `collision` (ou propriété `collision: true`), couche `track`
  pour un circuit, entités typées (`spawn`, `goal`, `boss`, `key`/`door` + `color`, `switch` + `gate` avec
  `switches`, `quest`/`item`/`barrier` avec `requires`/`gives`, `checkpoint` + `order`, `moving-platform` + `toX`/`toY`,
  `hazard`, `transition` + `target`/`bidirectional`), propriété d'asset `assetId`/`assetVersion` sur un tileset ou
  une entité.
- `validate` : gates communes (bornes, IDs, apparition hors obstacle, assets EXT-001 résolus, transitions
  bidirectionnelles), puis le validateur du genre : donjon (recherche d'états case/clés/interrupteurs, clé derrière
  sa propre porte), RPG (point fixe capacités et quêtes, lieux obligatoires, chemin point de sauvegarde → boss),
  plateforme (simulation à pas fixe avec les paramètres du profil `platformer`, marge de contrôle ; une plateforme
  mobile offre chaque position de sa trajectoire, le joueur pouvant l'attendre), circuit (boucle fermée, ordre des
  points de contrôle, largeur minimale du profil de kart, longueur de tour mesurée). Un budget dépassé rend
  `inconclusive` (code 6), jamais `pass`. Le genre `puzzle` attend le moteur de son jeu.
- `generate --genre dungeon --seed N` : découpage BSP avec un PRNG mulberry32 sérialisable, sans horloge ; seed +
  version + contraintes donnent la même sortie à l'octet. **ADR** : l'algorithme BSP est l'algorithme standard de
  ROT.js et libtcod ; ces bibliothèques sont en JavaScript et en C, le registre est en Python : il est repris tel
  quel plutôt qu'appelé, et un autre genre n'aura de générateur qu'en réutilisant une bibliothèque existante.
- `derive --constraints '{"transforms": ["mirror"]}'` crée une variante liée (`derivedFrom`, `transformations`).
- `publish --version x.y.z` : licence vérifiée, validation `pass`, version immuable (un autre contenu sous la même
  version rend 2) ; rend l'entrée `{id, version, sha256, transform}` d'un `level.lock.json`.
- `usages <id> --scope repos.json` lit les `level.lock.json` des jeux : index inverse jeu/version et historique
  par commit.
