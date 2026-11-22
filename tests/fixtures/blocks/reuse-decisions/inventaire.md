# Inventaire des composants et matrice de réutilisation

| Domaine | Composant du dépôt | Réutilisé | Fiche |
|---|---|---|---|
| rendu, entrées | `web/` | Phaser 4 | [rendu-et-interface](rendu-et-interface.md) |
| hasard, empreinte | `packages/engine/src/rng.ts`, `hash.ts`, `sha256.ts` | algorithmes publiés | [rng](rng.md), [empreinte-sauvegarde](empreinte-sauvegarde.md) |
| combat, versions de règles | `packages/engine/src/combat*.ts` | — (règles propres au jeu) | [combat-versionne](combat-versionne.md) |
| progression, quêtes | `packages/engine/src/progression.ts`, `quests.ts` | — | [progression-et-quetes](progression-et-quetes.md) |
| rencontres | `packages/engine/src/simulation.ts` | — | [variantes-rencontres](variantes-rencontres.md), [simulation](simulation.md) |
| dialogues | `content/dialogues/` | — | [dialogues](dialogues.md) |
| validation du contenu | `packages/content` | Ajv | [validation-contenu](validation-contenu.md) |
| sauvegarde | `web/store.ts` | IndexedDB du navigateur | [persistance](persistance.md) |
| tests, couverture | `tests/` | Vitest, fast-check, Playwright | [outillage-qualite](outillage-qualite.md) |
| SBOM, licences, vulnérabilités | `scripts/sbom.ts`, `check-licenses.ts`, `audit.ts` | `npm audit` | [sbom-et-licences](sbom-et-licences.md) |
| secrets | `.githooks/pre-commit` | gitleaks | [secrets](secrets.md) |
| cartes, parcours | `content/maps/`, `packages/engine/src/tile-map.ts` | — | [cartes-et-parcours](cartes-et-parcours.md) |
| atlas, planches | `assets/`, `public/assets/` | Aseprite, Phaser | [atlas-des-planches](atlas-des-planches.md) |

Le jeu d'action de Pestouille vit dans un autre dépôt et ne partage aucun code avec ce RPG : pas de doublon à
fusionner. Seul l'aspect du personnage est commun.
