# OpenCade Asset Registry

Registre privé des ressources de jeux autorisés. Le catalogue versionné
conserve les identifiants, la provenance, les licences et l’historique des usages.

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

Le lot L1 fournit `validate` et `inspect`. Les autres commandes répondent
avec `not-implemented` et leur lot prévu. L2 couvre `import-sheet`, `extract`,
`duplicates` et `scan-repos`. L3 couvre `search`, `register`, `derive`,
`usage`, `publish`, `sync` et `index rebuild`. Toutes acceptent
`--json`. Les commandes de mutation acceptent `--dry-run`. Le résultat JSON
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

[Architecture](docs/ARCHITECTURE.md) · [Contribution](docs/CONTRIBUTING.md) ·
[Règles agents](docs/AGENTS.md) · [Migration](docs/MIGRATION.md)
