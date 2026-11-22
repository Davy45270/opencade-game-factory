# OpenCade Asset Registry

Registre privé des ressources de jeux autorisés. Le catalogue versionné
conserve les identifiants, la provenance, les licences et l’historique des usages.

**Naviguer dans le catalogue** : [generated/catalogue/index.md](generated/catalogue/index.md) — une page par jeu,
source, planche et licence, avec vignettes et usages (générée par `scripts/catalogue_pages.py`, contrôlée en CI).

La source est la forge (`david/opencade-asset-registry`) : les PR s’y ouvrent et
s’y fusionnent. Une copie publique, [Davy45270/opencade-game-factory](https://github.com/Davy45270/opencade-game-factory),
reçoit `main` et les tags de version par synchronisation en avance rapide ; elle
porte le workflow GitHub Actions `usine` (jobs `registre` et `briques`). L’ancien
dépôt GitHub privé `Davy45270/opencade-asset-registry` est archivé.

Python 3.11 ou supérieur est requis. Installer les dépendances avec
`python3 -m pip install -r requirements.txt`.

```sh
./assetctl validate --json
./assetctl validate --base main --json
./assetctl inspect asset-kitchen-fouet-0001 --json
python3 -m tools.cli validate
python3 -m unittest discover -s tests -t . -p 'test_*.py'
```

Remplacer l’identifiant de l’exemple par celui d’une fiche du catalogue et
`main` par la révision cible de la PR. `validate` lit l’arbre de travail et
`--base` le compare à un commit Git. `inspect` restitue une fiche d’asset ou
de planche et ses usages. Les deux commandes lisent le catalogue du dépôt
qui contient l’exécutable.

Le registre fournit `search`, `inspect`, `import-sheet`, `extract`, `register`,
`derive`, `validate`, `usage`, `publish`, `duplicates`, `scan-repos`, `sync`,
`index`, `materialize`, `check-lock`, `export-atlas`, `validate-atlas` et
`sbom`. Toutes acceptent `--json`. Les commandes de mutation acceptent `--dry-run`. Le résultat JSON
est sur stdout et le journal JSON Lines sur stderr. `--log <fichier>` redirige
le journal.

| Code | Signification |
| --- | --- |
| 0 | Succès |
| 1 | Contrôle en échec ou fiche introuvable |
| 2 | Usage, arguments invalides ou commande prévue pour un autre lot |
| 3 | Refus de sécurité (licence, périmètre, lecture seule) |
| 4 | Source indisponible : entrée/sortie, réseau, dépendance ou miroir injoignable |
| 5 | Conflit de versions (catalogue, identifiants ou base modifiés entre lecture et écriture) — table commune, voir `docs/ARCHITECTURE.md` |

## Catalogues externes, liste de souhaits, packs et recherche visuelle

- **Sources ouvertes aux agents** (collecte automatique, robots.txt contrôlé à CHAQUE appel, refus net s'il
  interdit, User-Agent générique `opencade-asset-registry`, aucune donnée personnelle) : LPC (CREDITS.csv du
  générateur, sur GitHub), itch.io (flux publics, découverte seule), sources P2 de `external/whitelist.json`
  (ajout par PR avec revue de licence et de sécurité). `./assetctl external refresh --provider lpc --query shield`,
  puis `search`, `plan-import`, `import`, `sync --incremental` (requêtes conditionnelles).
- **Kenney et OpenGameArt refusent les agents IA** (robots.txt) : décision de David (HL-538, 22/11) — « ouvertes
  uniquement en automatique et liste de souhaits à récupérer en manuel ». Un agent ajoute un souhait, sans réseau :
  `./assetctl external souhait ajouter --provider kenney --page https://kenney.nl/assets/… --license CC0-1.0
  --raison "…" --jeu <jeu>` → `external/souhaits.json`.
- **Récupération, par David seulement, depuis un terminal de Zalman** :

  ```sh
  ./regctl souhaits lister
  ./regctl souhaits recuperer <id> [<id>…]     # ou --tous ; --oui saute la confirmation ; --sans-pr
  ```

  La commande refuse de tourner hors d'un terminal interactif (ni agent, ni tâche planifiée), affiche ce qu'elle va
  faire et demande confirmation. Pour chaque souhait : lien direct s'il est noté, sinon elle demande le chemin du zip
  téléchargé dans le navigateur ; licence vérifiée DANS l'archive (sinon `licence-non-prouvee`, rien d'importé) ;
  import ; index et pages reconstruits ; branche `souhaits/…` commitée et PR ouverte (jeton : `ASSETCTL_FORGEJO_TOKEN`
  ou `FORGEJO_TOKEN` de `/run/openbao/graphify.env`, jamais affiché).
- **Packs versionnés** (REG-09) : `./assetctl pack build <nom> --version 1.0.0 --asset <id>…|--game <jeu>` (version
  immuable) ; `./assetctl pack export <nom> --version 1.0.0 --target public --dest <dossier>` refuse tout le pack si
  une licence n'est pas vérifiée, et écrit `THIRD_PARTY_ASSETS.md`, `provenance.json`, `LICENSES/` et `pack.lock.json`.
- **Recherche visuelle CLIP** (REG-07) : index dérivé `generated/visual/` calculé sur l'A770 de **tank01**
  (`./assetctl visual embed --device xpu`, dépendances `requirements-visual.txt`) ; `./assetctl visual search --text
  "a cat"` ou `--image f.png`, résultats expliqués (cosinus, phash, verdict). Jamais de GPU sur Zalman (refus) ;
  contrôle CPU en CI : `scripts/visuel-controle.py`.

## Niveaux (EXT-002, `assetctl level`)

- `level search --similar-to <id>` : niveaux les plus proches, score décomposé (genre, dimensions, entités, structure).
- `level libre --id <source>` : import de niveaux de jeux libres listés dans `external/niveaux-libres.json` (commit
  figé, revue par PR) ; la licence des cartes se prouve par le fichier cité, au même commit.
- `level review <id> --out <dossier>` : capture PNG et rapport de revue non bloquant.
- `level simulate <id> --agent kart-bot --profile <kart.json>` : bot de pilotage (bicyclette, poursuite pure, rayon de
  braquage `circuit.kart.turningRadius`).
- `level site --out generated/niveaux [--check]` : catalogue web statique, contrôlé en CI.
- `level pipeline --request <demande.json> --seed N` : request → … → branche de PR (ADR-0008).
- `level adopt <id> --version X.Y.Z --repo <jeu> --game <jeu>` : met à jour `level.lock.json` du jeu sur une branche.

[Architecture](docs/ARCHITECTURE.md) · [Contribution](docs/CONTRIBUTING.md) ·
[Règles agents](docs/AGENTS.md) · [Migration](docs/MIGRATION.md)
