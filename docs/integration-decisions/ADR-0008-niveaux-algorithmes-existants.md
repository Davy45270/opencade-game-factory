# ADR-0008 — Pipeline de niveaux : réutiliser des outils open source, ne rien réécrire

- **Statut :** approuvée
- **Approuvée par :** David, HL-538 7-3320
- **Extension :** David, HL-525 7-3321 (« Étendre maintenant »)
- **Date :** 2026-11-22 (révision 2, après l'étude des alternatives demandée par David)
- **Ticket :** HL-538 (matrice E205, LV-16 à LV-20) ; étude jointe : `etude-niveaux-alternatives.md` (HL-538, commentaire 7-3311)

## Contexte

EXT-002 demande un pipeline `request → search → candidate scoring → reuse/derive/generate → normalize → validators →
simulated playtest → visual render → PR` (E205). Il interdit d'inventer un générateur ou un solveur quand une méthode
publiée existe.

La révision 1 respectait la lettre de cette règle, mais pas son esprit. Elle **réécrivait** des algorithmes publiés
qui existent déjà en bibliothèque : le BSP de libtcod, et un bot kart à poursuite pure alors que Dérapage a déjà son
IA. Elle validait aussi la plateforme par un code maison.

L'étude du 22/11 a recensé, pour chaque genre, les outils open source existants, avec leur licence, leur langage et
leur maintenance. Ceux qu'elle retient ont été mesurés sur Zalman, en CPU.

Publics vérifiés dans les specs :

- Opencade (Dérapage, Ferraille), Cozy Room Sort, Six de chaque et Capsule Panic : **adultes**. La qualité se juge sur
  la profondeur, la difficulté réglable et la rejouabilité.
- Pestouille : **familial**.
- Tictac : **enfant** (5 à 9 ans, OpenCadeKid).

## Décision

**Arbitrage de David (HL-538, commentaire 7-3312, 22/11) : option C, un jeu pilote d'abord.** Ferraille sert de pilote,
avec Sturgeon : 3 à 5 niveaux déterministes par graine, au chemin garanti, validés par le moteur du jeu et jouables
dans le vrai jeu sur une préversion non publique. **Pilote jugé et validé par David sur son téléphone (HL-538 7-3320, 22/11 : « je valide le nouveau fonctionnement de
Ferraille »).** Extension décidée le même jour (HL-525 7-3321, « Étendre maintenant ») : le tableau ci-dessous devient la cible
engagée, genre par genre, en commençant par Pestouille. Chaque genre remplace son code maison (BSP de `generate.py`,
`bot_kart`) quand son outil réutilisé est en place et vérifié.

| Genre (jeux) | Outil réutilisé | Licence | Rôle | Remplace |
| --- | --- | --- | --- | --- |
| Donjon et exploration (Pestouille) | [Sturgeon](https://github.com/crowdgames/sturgeon-pub), appris des cartes Tiled du jeu | MIT | génère des variantes au chemin départ→but prouvé (SAT) | — (aucun générateur de carte) |
| Donjon, découpage | [python-tcod](https://github.com/libtcod/python-tcod) `tcod.bsp` | BSD-2 | découpage BSP déterministe par graine | le BSP réécrit dans `tools/levels/generate.py` |
| Puzzle (Cozy, Six, Capsule) | [clingo](https://github.com/potassco/clingo) (ASP) | MIT | génère des variantes à solution unique et à difficulté réglable (nombre d'indices, longueur minimale) | — (aucun générateur de puzzle) |
| Puzzle, verdict | moteur du jeu, sans écran (ADR-0006) | celle du jeu | juge final : `SOLUTIONS n`, unicité si le profil l'exige | inchangé |
| Plateforme (Ferraille), labyrinthes d'arcade | Sturgeon `--reach-move platform` / `maze`, appris des niveaux du jeu | MIT | génère et prouve l'atteignabilité | le validateur maison de saut |
| Circuit (Dérapage) | **aucun générateur** ; les 30 circuits de David, avec des variantes déclarées (miroir, sens inverse) | — | dérivation seulement | — |
| Circuit, essai simulé (LV-19) | IA et `validateTrack` de Dérapage (`src/engines/derapage/ai.ts`, `track.ts`), exécutés par Node sans écran | celle du jeu | un seul pilote, celui du jeu | `bot_kart` Python (poursuite pure) |
| Format de carte | [Tiled](https://www.mapeditor.org/) JSON (déjà lu) ; formats natifs pour puzzle et circuit | format ouvert | aucun format maison nouveau | — |
| Similarité (LV-16) | score décomposé actuel, **plus** cosinus des embeddings CLIP des captures (REG-07, déjà calculés) | — / MIT (open_clip) | classement expliqué | complète le score maison |
| Capture et revue (LV-18), PR | Pillow, plomberie git | — | inchangé | — |

Règles :

- Une dépendance de génération est **optionnelle**. Absente, le pipeline s'arrête sur `no-generator` et demande un
  import ; il ne retombe jamais sur un code improvisé.
- Tout reste déterministe par graine, et chaque sortie porte la version de l'outil.
- Exécution en CPU sur Zalman, sans GPU.
- Un LLM peut au plus traduire une demande en contraintes pour Sturgeon ou clingo. Il ne produit jamais le niveau.

## Alternatives

| Outil | Pourquoi |
| --- | --- |
| [Ludii](https://github.com/Ludeme/Ludii) | licence CC BY-NC-ND 4.0 : pas de modification, pas d'usage commercial |
| Dungeon Architect | propriétaire, payant, plugin Unreal/Unity |
| [Mario AI Framework](https://github.com/amidos2006/Mario-AI-Framework) | aucune licence |
| [PCG Benchmark](https://github.com/amidos2006/pcg_benchmark) | aucune licence ; c'est un banc d'évaluation, pas un générateur (0 niveau jouable sur 800 tirages aléatoires mesurés) |
| [WaveFunctionCollapse](https://github.com/mxgmn/WaveFunctionCollapse) | sans garantie de jouabilité ; Sturgeon couvre les mêmes motifs avec garantie |
| [MarioGPT](https://github.com/shyamsn97/mario-gpt), [TOAD-GAN](https://github.com/Mawiszus/TOAD-GAN) | réentraînement sur nos jeux, faible déterminisme, GPU ; non mesurés |
| Génération de circuits (enveloppe convexe + spline) | mesurée : jouable mais sans épingle ni chicane, trop pauvre pour un public adulte |
| Circuits par diversité (MAP-Elites) | piste future, notée par l'IA du jeu, si David veut plus de 30 circuits |

## Conséquences

- On retire `bsp_dungeon` (à remplacer par `tcod.bsp`) et `bot_kart` (à remplacer par l'appel Node à l'IA de Dérapage).
- On ajoute des extras optionnels `requirements-levels.txt` : tcod, clingo, python-sat ; Sturgeon est épinglé par commit.
- Les tests de LV-19 visent l'IA du jeu ; ceux d'E207 gardent `SOLUTIONS n`.

## Retour arrière

Les commandes `pipeline`, `site`, `review`, `libre` et `adopt` sont isolées dans `tools/levels/p1.py`.
`ASSETCTL_LEVELS=off` les désactive avec le reste d'EXT-002. Retirer un extra ramène son genre à `no-generator`.
