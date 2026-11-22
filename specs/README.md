# Registre des specs (REG-003)

Le module suit l'arborescence de REG-003 § 3 (ARCH-001 E109). Contrôle : `specs/tests/contracts/test_e109_organisation.py`.

| Dossier | Contenu |
|---|---|
| `registry/games/`, `registry/platform/` | une fiche `SPEC-*.json` par spec. Les specs de jeu vont dans `games/`. Celles de l'usine, du registre d'assets et de la Control Tower vont dans `platform/` (`fiche.PLATEFORME`). |
| `registry/shared/`, `registry/decisions/` | prévus par la spec, vides pour l'instant |
| `registry/ids.json`, `registry/journal.jsonl`, `registry/drive-a-importer.json` | le registre d'identifiants (ajout seul), le journal d'audit et les documents Drive inscrits. Ils sont publiés dans le même lot atomique que les fiches. |
| `manifests/projects/` | les manifestes de projets ; voir le README du dossier |
| `schemas/` | les schémas `specification`, `requirement`, `dependency`, `implementation` et `decision`. La fiche référence les quatre autres par `$id`. |
| `tools/specctl/` | le code de `specctl`. Le point d'entrée reste `./specctl`, à la racine de l'usine. |
| `migrations/drive/`, `migrations/github/` | les imports de sources ; voir les README |
| `generated/{search-index,dependency-graph,coverage}/` | les index que régénère `./specctl index`. La CI refuse un index périmé. |
| `tests/{contracts,import,integration,acceptance}/` | les oracles, joués par `.woodpecker/specs.yml` |

Les workflows `validate`, `resolve`, `impact` et `export` sont des étapes Woodpecker (`.woodpecker/specs.yml`).
