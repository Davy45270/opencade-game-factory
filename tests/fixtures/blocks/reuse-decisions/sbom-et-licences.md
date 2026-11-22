# Décision de réutilisation : SBOM, licences et vulnérabilités

## Besoin

SBOM CycloneDX des dépendances d'exécution directes et transitives ; contrôle que chaque dépendance a une licence
identifiée et compatible ; rapport de vulnérabilités avec exceptions datées.

## Candidats

| Composant | Candidat | Licence | Constat |
|---|---|---|---|
| SBOM | `npm sbom` (npm 11) | Artistic-2.0 | intégré, mais oublie les dépendances des workspaces (Ajv absent) |
| SBOM | @cyclonedx/cyclonedx-npm | Apache-2.0 | complet, une dépendance de plus et un horodatage à neutraliser |
| SBOM | syft | Apache-2.0 | binaire Go hors npm, utile pour les images de conteneurs |
| SBOM | script sur `package-lock.json` | MIT (le nôtre) | 150 lignes, déterministe, workspaces compris |
| licences | license-checker | BSD-3-Clause | plus maintenu depuis 2019 |
| licences | lecture de `package-lock.json` | MIT (le nôtre) | le champ `license` y est déjà, aucune dépendance |
| vulnérabilités | `npm audit` | Artistic-2.0 | intégré, base GitHub Advisory |
| vulnérabilités | osv-scanner | Apache-2.0 | binaire à part, base OSV plus large |

## Choix

Scripts maison sur `package-lock.json` pour le SBOM et les licences : l'outil intégré est incomplet, et le
lockfile porte déjà toutes les données. `npm audit` pour les vulnérabilités, enrobé par `scripts/audit.ts` pour la
politique d'exceptions. Adaptation plutôt que fork : aucun outil n'est copié.

## Risques

Le format du lockfile change rarement (version 3 vérifiée par test). Si un écart apparaît, @cyclonedx/cyclonedx-npm
est l'alternative directe.

## Tests de qualification

`tests/unit/sbom.test.ts`, `tests/unit/licenses.test.ts`, `tests/unit/audit.test.ts`.
