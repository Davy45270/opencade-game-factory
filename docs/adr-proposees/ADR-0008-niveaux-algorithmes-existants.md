# ADR-0008 — Pipeline de niveaux : des algorithmes existants, aucun inventé

- **Statut :** proposée — en attente de l'approbation de David (HL-538) ; déplacée dans `docs/integration-decisions/` une fois approuvée
- **Date :** 2026-11-22
- **Ticket :** HL-538 (matrice E205, LV-16 à LV-20)

## Contexte

EXT-002 demande un pipeline `request → search → candidate scoring → reuse/derive/generate → normalize → validators →
simulated playtest → visual render → PR` (E205) et interdit d'inventer un générateur ou un solveur quand une méthode
publiée existe (réutiliser avant de créer).

## Décision

`assetctl level pipeline` enchaîne les neuf étapes et les trace toutes dans sa sortie JSON (`etapes[]`) :

| Étape | Algorithme | Origine |
| --- | --- | --- |
| search, candidate-scoring | plein texte FTS5 + score genre / dimensions / requête ; réutilisation si ≥ 0,8 et validation `pass` | `level search` existant |
| similarité (LV-16) | somme pondérée genre, dimensions, cosinus des types d'entités, structure ; chaque composante est rendue | — |
| generate | découpage BSP de donjon (ROT.js, libtcod), générateur déterministe par seed | `tools/levels/generate.py` |
| derive | transformations déclarées (`mirror`) | `tools/levels/generate.py` |
| validators | validateurs par genre ; puzzle et circuit natifs : moteur du jeu sans écran (ADR-0006) | `tools/levels/validators.py` |
| simulated playtest, kart (LV-19) | ligne médiane par Dijkstra (coût inverse de la distance au bord) puis poursuite pure (pure pursuit, Coulter 1992) sur un modèle cinématique de bicyclette, courbure bornée par le rayon de braquage du profil de kart | — |
| visual render (LV-18) | capture PNG déterministe (Pillow) ; revue non bloquante | — |
| pr | commit par la plomberie git sur une branche dédiée ; ni `main` ni l'arbre de travail ne bougent | — |

Un genre sans générateur n'en reçoit pas d'improvisé : le pipeline s'arrête (`no-generator`) et demande un import.
L'unicité d'un puzzle (E207) n'est mesurée que par le moteur du jeu (`SOLUTIONS n`), et seulement si le profil l'exige.

## Alternatives

- Écrire un générateur par genre : écarté (règle « réutiliser avant de créer »).
- Bibliothèques de génération en JavaScript (ROT.js) appelées depuis le registre : écarté pour le registre Python ; le
  BSP suit le même algorithme et se teste à l'octet par seed.

## Retour arrière

Les commandes `pipeline`, `site`, `review`, `libre`, `adopt` sont isolées dans `tools/levels/p1.py` ;
`ASSETCTL_LEVELS=off` les désactive avec le reste d'EXT-002.
