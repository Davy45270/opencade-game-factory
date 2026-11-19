# Agents de l'usine : règles communes

Ce fichier s'adresse à tout agent qui travaille dans ce dépôt : Codex, Claude, Gemini/agy ou un humain pressé. Codex le
lit de lui-même. Chaque prompt d'agent rangé dans `.codex-logs/` y renvoie. Les règles du registre d'assets
(chercher avant de créer, provenance, licences) sont dans [docs/AGENTS.md](docs/AGENTS.md) et s'appliquent aussi.

Chaque règle ci-dessous vient d'un incident réel. Aucune ne se négocie dans un prompt : un prompt qui en contredit une
est une erreur de prompt. Il faut alors s'arrêter et le signaler, pas l'exécuter.

## 0. Étape 0 : graphify, avant tout geste

Avant de concevoir, de coder ou de conclure « rien n'existe », interroge le graphe de connaissance : il indexe la doc,
l'outillage, les jeux et cette usine (identifiants `<dépôt>::…`).

- Agent avec MCP : `query_graph(question="<sujet>", token_budget=4000)`. Si la sortie est TRONQUÉE, relance plus large
  ou plus précis.
- Agent sans MCP (Codex) : lis `graphify-out/graph.json` s'il est fourni dans ton contexte, sinon cherche par `rg`
  dans les chemins que le brief nomme. Écris dans ton rapport ce que tu as cherché et ce que tu as trouvé.
- Ton premier rapport cite la question posée et **3 sources réutilisées** (chemin et section).
- Module `blocks/` : « reuse before build ». `bbctl search` interroge graphify avant toute brique nouvelle.

## 1. Processus : on ne tue jamais par motif

- **Interdit** : `pkill -f …`, `killall …`, `kill $(pgrep …)`. Le 19/11, un `pkill` par motif lancé pour une passe a
  tué la passe d'un autre chantier qui partageait la même file Codex. La Control Tower le détecte et alerte.
- **Permis** : `kill <PID>`, seulement sur un processus que **tu** as lancé, et avec un PID relu juste avant.

## 2. Prompts et briefs : heredoc PROTÉGÉ

Un prompt ou un brief s'écrit avec `<<'EOF'`, la borne entre guillemets. Le 19/11, un heredoc non protégé a exécuté
les commandes écrites entre accents graves dans un prompt, et un script e2e a été lancé à l'insu de l'agent.

## 3. Git

- **Jamais `git add -A`** ni `git add .`. Ajoute les fichiers un par un et nomme-les, ou utilise `git commit -- <chemins>`.
  Le 19/11, un index partagé a mélangé deux jeux dans un commit.
- Un worktree ou un clone par agent quand plusieurs agents écrivent le même dépôt
  (`git worktree add ../<dépôt>-<agent> -b <branche>`). Ne touche jamais aux chemins qu'un autre lot est en train de
  modifier : le brief les nomme.
- Ne pousse rien : l'orchestrateur pousse, après relecture. Ni GitHub ni Forgejo depuis une passe d'agent.
- Aucune référence de ticket ni chemin de machine dans un fichier qui part vers un dépôt public (gabarit `ci/`,
  fichiers générés pour les jeux) : `tests/ci/test_gabarit_ci.py` le vérifie.

## 4. Aucun son

Aucun son sur aucun appareil : navigateurs lancés muets (`--mute-audio`), aucun essai audio, aucune enceinte.

## 5. Dérogations : jamais par soi-même

Un agent **n'approuve jamais sa propre dérogation**. Les cas visés : une ligne de matrice `ecartee`, un forçage de
publication, un test désactivé, un seuil abaissé.

- Une dérogation se prouve par le commentaire de ticket où **David** l'a donnée (`HL-n 7-xxxx`, date,
  `valide_par_david: true`).
- Une dérogation porte une échéance `expire`, qui est une date ou une version. La barrière la rend rouge une fois
  l'échéance passée.
- Un commentaire d'agent ne vaut pas validation, même s'il dit « validé ».

## 6. Charge et tests

- Un seul Codex à la fois, **par la file** : `codex-file.sh <commande…>`. Jamais de `flock` nu ni de passe hors file.
- **Si tu ES une passe Codex**, tu as été lancé PAR la file : tu es déjà dans ton créneau, ne l'appelle pas. La variable `CODEX_FILE_TICKET` (ton ticket) le prouve ; le verrou de la file est en lecture seule dans ton bac à sable, c'est normal. Seuls les orchestrateurs (humains, Claude, lanceurs) passent par `codex-file.sh`.
- Jamais la suite de tests complète en local : seulement les tests ciblés de ce que tu changes. La CI Woodpecker fait
  le reste.
- Les navigateurs et Vitest des jeux tournent dans le créneau E2E de tank01, pas sur le poste. L'onduleur doit rester
  sous 75 %.
- Codes de retour communs à toutes les sous-commandes : 0 succès, 1 contrôle en échec, 2 usage, 3 refus de sécurité,
  4 source indisponible, 5 conflit de versions ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).

## 7. Secrets et données personnelles

Aucun secret dans un prompt, un journal, un test ou un commit. L'adresse e-mail personnelle du propriétaire n'est jamais
envoyée à un tiers ni écrite dans un dépôt public. Les commits de jeux utilisent l'adresse `noreply`.

## Modules

| Module | Outil | Où |
| --- | --- | --- |
| assets | `assetctl` | `tools/` (registre, lots L1 à L3) |
| specs | `specctl` | `specs/` : REG-003 ; oracles dans `tests/specs/` |
| blocks | `bbctl` | `blocks/` : BB-001 au-dessus de graphify ; oracles dans `tests/blocks/` |
| CI commune des jeux | `ci/woodpecker.py` | `ci/` : gabarit Woodpecker inclus par génération vérifiée |
