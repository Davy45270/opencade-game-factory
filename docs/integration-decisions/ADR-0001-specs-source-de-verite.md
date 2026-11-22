# ADR-0001 — Specs : import initial depuis la doc, puis versionnées dans l'usine

- **Statut :** approuvée
- **Date :** 2026-11-19
- **Approuvée par :** David, HL-525 7-2955

## Contexte

Trois sources concurrentes pour les specs (Drive, archives de homelab-docs, et le dépôt `opencade-spec-registry` que REG-003 voulait faire autorité), en contradiction avec AT-11 d'ARCH-001 (relecture HL-525 7-2953, point 1).

## Décision

« La doc pour l'initial, mais comme les specs vivent, les modifications doivent être suivies dans le référentiel ainsi que les solutions et building blocks. » L'import initial se fait depuis `homelab-docs/specs` ; ensuite toute évolution d'une spec, et l'enregistrement des solutions et des briques, se fait et se versionne dans l'usine (`specs/registry/`, `blocks/catalog/`). Le registre ne garde que des références (dépôt, chemin, commit, sha256) vers les documents importés.

## Alternatives

- `homelab-docs/specs` reste canonique et REG-003 n'est qu'un index fédéré (proposition de la relecture 7-2953) : écartée, les specs évoluent et leurs versions doivent être suivies avec les solutions.
- Un dépôt `opencade-spec-registry` séparé qui fait autorité (REG-003 tel qu'écrit) : écartée par l'ADR 0002 (un seul dépôt).

## Retour arrière

`specctl import --from homelab-docs` recrée les fiches depuis la doc (opération idempotente) ; il suffit de déclarer de nouveau `homelab-docs` comme `authority` dans `importOrigins` et de cesser les écritures dans `specs/registry/`.

## Références

- `scripts/sources_de_verite.py` (E009) et `specctl verify`.
