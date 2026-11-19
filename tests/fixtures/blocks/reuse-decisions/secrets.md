# Décision de réutilisation : détection de secrets

## Besoin

Refuser un secret avant le commit et en CI, sur l'historique comme sur les artefacts produits.

## Candidats

| Candidat | Licence | Constat |
|---|---|---|
| gitleaks 8.30.1 | MIT | binaire unique, règles maintenues, mode pre-commit, déjà utilisé par les autres jeux |
| trufflehog | AGPL-3.0 | vérifie les jetons en ligne (appels sortants), licence à réciprocité forte |
| detect-secrets | Apache-2.0 | Python, fichier de référence à maintenir |

## Choix

gitleaks : image Harbor v8.30.1 en CI, pour le scan comme pour la contre-épreuve (le binaire statique de l'image
est copié dans l'espace de travail) ; la CI ne télécharge rien depuis GitHub. En local, le crochet `pre-commit`
prend gitleaks dans le PATH ou dans `.tools/` (`scripts/gitleaks-install.sh`, version et SHA-256 épinglées).
Aucun appel sortant pendant le scan.

## Tests de qualification

`tests/ci/secrets.test.ts` : un jeton factice est détecté par le scan et par le crochet, un fichier propre passe.
