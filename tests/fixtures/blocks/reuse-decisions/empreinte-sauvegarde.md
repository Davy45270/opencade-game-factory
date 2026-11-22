# Décision de réutilisation : empreinte de sauvegarde

## Besoin

Sceller une sauvegarde par un condensat SHA-256 calculé de façon synchrone par le moteur, sur un texte UTF8, et
garder l'empreinte FNV-1a des journaux de rejeu existants.

## Candidats

| Candidat | Version | Licence | Constat |
|---|---|---|---|
| `@noble/hashes` (npm) | 2.4.0 | MIT | implémentation auditée et synchrone ; dépendance d'exécution pour une seule fonction |
| `js-sha256` (npm) | 1.1.0 | MIT | synchrone et petit ; dépendance d'exécution, maintenance espacée |
| Web Crypto `crypto.subtle.digest` | API standard | — | rien à distribuer, mais asynchrone : incompatible avec l'interface synchrone du moteur |
| Implémentation du dépôt `packages/engine/src/sha256.ts` | — | MIT | une cinquantaine de lignes, vérifiée contre `node:crypto` |

## Choix

L'implémentation du dépôt. Le moteur est synchrone de bout en bout ; Web Crypto l'obligerait à devenir asynchrone.
Entre une dépendance d'exécution et cinquante lignes vérifiées contre l'implémentation de Node, la seconde coûte
moins (SBOM, audit, mises à jour). L'empreinte n'est pas une protection contre un adversaire : elle détecte une
sauvegarde abîmée ou modifiée à la main.

## Risques

- Un défaut sur un cas limite (message multibloc, caractères hors ASCII) altérerait toutes les sauvegardes : les
  tests comparent donc à `node:crypto` sur ces cas.
- Les performances suffisent pour une sauvegarde de quelques kilo-octets, pas pour de gros volumes.

## Tests de qualification

- `tests/unit/save.test.ts` : condensat SHA-256 comparé à `node:crypto`, sauvegarde scellée et relue.
- `tests/unit/rng.test.ts` : empreinte d'état FNV-1a indépendante de l'ordre des clés.
