"""Validateurs de niveaux (EXT-002 § 5) : gates communes, donjon, RPG, plateforme, circuit, puzzle (moteur du jeu).

Chaque validateur rend {status: pass|fail|inconclusive, diagnostics, metrics}. Un budget de calcul dépassé rend
`inconclusive`, jamais `pass`. Les règles de jeu restent au jeu : ces validateurs lisent les conventions déclarées
dans la carte (entités typées, couches de collision et de piste) et le profil du jeu (`--profile`), ils ne
réimplémentent pas un moteur.
"""

import re
from collections import deque
from pathlib import Path

from tools.levels.formats import semantics

DEFAULT_BUDGET = 200_000
SPAWNS = {"spawn", "start", "player"}
OBJECTIVES = {"goal", "exit", "boss"}


class Budget:
    def __init__(self, limit):
        self.limit, self.used = limit or DEFAULT_BUDGET, 0

    def spend(self):
        self.used += 1
        return self.used <= self.limit


def _diag(code, message, severity="error", **extra):
    return {"code": code, "severity": severity, "message": message, **extra}


def _cells(entity):
    return {(entity["x"] + dx, entity["y"] + dy) for dx in range(entity["w"]) for dy in range(entity["h"])}


def _split(value):
    if value in (None, ""):
        return set()
    if isinstance(value, list):
        return {str(v) for v in value}
    return {part.strip() for part in str(value).split(",") if part.strip()}


def _result(diagnostics, metrics=None, inconclusive=False):
    errors = [d for d in diagnostics if d["severity"] == "error"]
    status = "fail" if errors else "inconclusive" if inconclusive else "pass"
    return {"status": status, "diagnostics": diagnostics, "metrics": metrics or {}}


# --- Gates communes (P0) --------------------------------------------------------------------------------------

def common(record, level, known_assets=None):
    sem = semantics(level)
    diagnostics = list(level.get("diagnostics", []))
    width, height = level["width"], level["height"]
    seen = {}
    for entity in sem["entities"]:
        if entity["id"] in seen and entity["id"] not in ("None", ""):
            diagnostics.append(_diag("duplicate-entity-id", f"identifiant d'entité dupliqué : {entity['id']}"))
        seen[entity["id"]] = entity
        if not all(0 <= x < width and 0 <= y < height for x, y in _cells(entity)):
            diagnostics.append(_diag("entity-out-of-bounds", f"entité {entity['type']} {entity['id']} hors limites",
                                     entity=entity["id"]))
    for layer in level["layers"]:
        if layer["type"] == "tiles" and len(layer["data"]) != layer["width"] * layer["height"]:
            diagnostics.append(_diag("layer-size", f"couche {layer['name']} : taille incohérente"))
    # Un niveau natif de jeu (graphe de monde, plateforme de Ferraille) place son départ selon les règles du jeu.
    spawns = [e for e in sem["entities"] if e["type"] in SPAWNS]
    if record["kind"] in {"rpg", "dungeon", "platformer"} and not spawns and not {"graph", "platformer"} & set(level):
        diagnostics.append(_diag("spawn-missing", "aucun point d'apparition (spawn)"))
    for spawn in spawns:
        if _cells(spawn) & sem["solid"]:
            diagnostics.append(_diag("spawn-in-obstacle", f"apparition {spawn['id']} dans un obstacle",
                                     cell=[spawn["x"], spawn["y"]]))
    if known_assets is not None:
        for ref in sem["assets"]:
            versions = known_assets.get(ref["id"])
            if versions is None or (ref["version"] is not None and str(ref["version"]) not in versions):
                diagnostics.append(_diag("asset-missing", f"asset EXT-001 introuvable : {ref['id']}"
                                         f"{'@' + str(ref['version']) if ref['version'] is not None else ''}",
                                         asset=ref["id"]))
    return _result(diagnostics, {"entities": len(sem["entities"]), "solidCells": len(sem["solid"]),
                                 "assets": len(sem["assets"])})


def transitions(record, level, others):
    """Transitions bidirectionnelles lorsque requises (`bidirectional: true`) : la cible doit pointer en retour."""
    diagnostics = []
    for entity in semantics(level)["entities"]:
        if entity["type"] != "transition" or not entity["props"].get("bidirectional"):
            continue
        target = others.get(entity["props"].get("target"))
        back = [e for e in semantics(target["content"])["entities"] if e["type"] == "transition"
                and e["props"].get("target") == record["id"]] if target else []
        if not back:
            diagnostics.append(_diag("transition-one-way", f"transition {entity['id']} sans retour depuis "
                                     f"{entity['props'].get('target')}"))
    return diagnostics


# --- Grille ---------------------------------------------------------------------------------------------------

def _neighbours(cell, width, height):
    x, y = cell
    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
        if 0 <= nx < width and 0 <= ny < height:
            yield nx, ny


def _reach(start, width, height, passable, budget):
    seen, queue = {start}, deque([start])
    while queue:
        if not budget.spend():
            return seen, False
        cell = queue.popleft()
        for nxt in _neighbours(cell, width, height):
            if nxt not in seen and passable(nxt):
                seen.add(nxt)
                queue.append(nxt)
    return seen, True


# --- Donjon : recherche d'états (case, clés, interrupteurs) ------------------------------------------------------

def dungeon(level, profile=None, budget=None):
    sem = semantics(level)
    budget = budget or Budget((profile or {}).get("budget"))
    width, height, solid = level["width"], level["height"], sem["solid"]
    spawn = next((e for e in sem["entities"] if e["type"] in SPAWNS), None)
    goals = set().union(*[_cells(e) for e in sem["entities"] if e["type"] in OBJECTIVES]) if sem["entities"] else set()
    if spawn is None or not goals:
        return _result([_diag("dungeon-incomplete", "donjon sans apparition ou sans objectif")])
    keys = {c: e["props"].get("color", "default") for e in sem["entities"] if e["type"] == "key" for c in _cells(e)}
    doors = {c: e["props"].get("color", "default") for e in sem["entities"] if e["type"] == "door" for c in _cells(e)}
    switches = {c: str(e["props"].get("switch", e["name"] or e["id"])) for e in sem["entities"] if e["type"] == "switch"
                for c in _cells(e)}
    gates = {c: _split(e["props"].get("switches")) for e in sem["entities"] if e["type"] == "gate" for c in _cells(e)}

    def passable(cell, held, on):
        if cell in solid:
            return False
        if cell in doors and doors[cell] not in held:
            return False
        if cell in gates and not gates[cell] <= on:
            return False
        return True

    diagnostics = []
    for colour in sorted(set(keys.values())):
        cells = {c for c, k in keys.items() if k == colour}
        other = set(doors.values()) - {colour}
        blocked, _ = _reach((spawn["x"], spawn["y"]), width, height,
                            lambda c: c not in solid and doors.get(c) != colour, Budget(budget.limit))
        opened, _ = _reach((spawn["x"], spawn["y"]), width, height, lambda c: c not in solid, Budget(budget.limit))
        if not cells & blocked and cells & opened:
            diagnostics.append(_diag("key-behind-own-door", f"la clé {colour} n'est accessible qu'à travers sa propre"
                                     " porte", color=colour, otherDoors=sorted(other)))
    start = ((spawn["x"], spawn["y"]), frozenset(), frozenset())
    seen, queue, found, complete = {start}, deque([(start, 0)]), None, True
    while queue:
        if not budget.spend():
            complete = False
            break
        (cell, held, on), steps = queue.popleft()
        if cell in goals:
            found = steps
            break
        for nxt in _neighbours(cell, width, height):
            if not passable(nxt, held, on):
                continue
            nheld = held | {keys[nxt]} if nxt in keys else held
            non = on ^ {switches[nxt]} if nxt in switches else on
            state = (nxt, frozenset(nheld), frozenset(non))
            if state not in seen:
                seen.add(state)
                queue.append((state, steps + 1))
    metrics = {"statesExplored": len(seen), "budget": budget.limit, "pathLength": found}
    if found is None and complete:
        diagnostics.append(_diag("dungeon-unsolvable", "objectif inatteignable depuis l'apparition (état clés/"
                                 "interrupteurs/portes exploré en entier)"))
    return _result(diagnostics, metrics, inconclusive=found is None and not complete)


# --- RPG : point fixe des capacités, quêtes et lieux obligatoires ------------------------------------------------

def _rpg_fixpoint(level, sem, start, inventory, budget):
    """Point fixe : atteindre, accomplir ce qui est permis, élargir l'inventaire, recommencer. Rend aussi, par tour,
    l'ensemble atteint et le tour d'obtention de chaque gain (pour l'inventaire disponible à un point de sauvegarde)."""
    width, height, solid = level["width"], level["height"], sem["solid"]
    barriers = {c: _split(e["props"].get("requires")) for e in sem["entities"] if e["type"] in {"barrier", "door"}
                for c in _cells(e)}
    givers = [e for e in sem["entities"] if e["type"] in {"quest", "item", "npc"}]
    inventory, done, gained_at, reaches = set(inventory), set(), {}, []
    complete = True
    while True:
        reach, ok = _reach(start, width, height, lambda c: c not in solid and barriers.get(c, set()) <= inventory,
                           budget)
        complete = complete and ok
        reaches.append(reach)
        gained = set()
        for entity in givers:
            key = str(entity["props"].get("quest") or entity["id"])
            if key in done or not _cells(entity) & reach or not _split(entity["props"].get("requires")) <= inventory:
                continue
            done.add(key)
            gained |= _split(entity["props"].get("gives")) | {key}
        for item in gained - inventory:
            gained_at[item] = len(reaches) - 1
        inventory |= gained
        if not gained or not complete:
            return {"reach": reach, "inventory": inventory, "done": done, "gainedAt": gained_at, "reaches": reaches,
                    "complete": complete}


def _graph_fixpoint(graph, start, inventory, budget):
    """Point fixe sur un graphe de lieux : parcourir les liaisons dont la porte d'arrivée est ouverte, recevoir les
    drapeaux des lieux atteints, recommencer. Rend l'ensemble atteint, l'inventaire et le tour d'obtention."""
    neighbours = {n: set() for n in graph["nodes"]}
    for a, b in graph["edges"]:
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
    requires = {}
    for gate in graph["gates"]:
        requires.setdefault(gate["target"], set()).add(gate["requires"])
    inventory, gained_at, reaches, complete = set(inventory), {}, [], True
    while True:
        reach, queue = {start}, deque([start])
        while queue:
            if not budget.spend():
                complete = False
                break
            for nxt in sorted(neighbours.get(queue.popleft(), ())):
                if nxt not in reach and requires.get(nxt, set()) <= inventory:
                    reach.add(nxt)
                    queue.append(nxt)
        reaches.append(reach)
        gained = {graph["grants"][n] for n in reach if n in graph["grants"]} - inventory
        for flag in gained:
            gained_at[flag] = len(reaches) - 1
        inventory |= gained
        if not gained or not complete:
            return {"reach": reach, "inventory": inventory, "gainedAt": gained_at, "reaches": reaches,
                    "complete": complete}


def rpg_graph(level, profile=None, budget=None):
    """RPG décrit par un graphe de monde : lieux obligatoires (points de sauvegarde, boss) atteignables, chaque porte
    ouvrable par un drapeau effectivement obtenu, et aucun point de sauvegarde d'où le boss deviendrait inatteignable."""
    graph = level["graph"]
    budget = budget or Budget((profile or {}).get("budget"))
    if not graph.get("start"):
        return _result([_diag("spawn-missing", "graphe de monde sans lieu de départ (start)")])
    state = _graph_fixpoint(graph, graph["start"], set(), budget)
    reach, inventory = state["reach"], state["inventory"]
    diagnostics = []
    for gate in graph["gates"]:
        if gate["requires"] not in inventory:
            origin = "jamais attribué" if gate["requires"] not in graph["grants"].values() else "attribué hors d'atteinte"
            diagnostics.append(_diag("quest-unreachable", f"porte {gate['target']} : drapeau {gate['requires']} "
                                     f"{origin}", gate=gate["target"], flag=gate["requires"]))
    mandatory = set(graph["checkpoints"] + graph["bosses"])
    for node in graph["nodes"]:
        if node not in reach:
            diagnostics.append(_diag("place-unreachable", f"lieu {'obligatoire ' if node in mandatory else ''}{node} "
                                     "inatteignable", severity="error" if node in mandatory else "warning",
                                     place=node))
    for checkpoint in (c for c in graph["checkpoints"] if c in reach):
        first = next(i for i, r in enumerate(state["reaches"]) if checkpoint in r)
        held = {flag for flag, when in state["gainedAt"].items() if when <= first}
        sub = _graph_fixpoint(graph, checkpoint, held, budget)
        for boss in graph["bosses"]:
            if boss in reach and boss not in sub["reach"] and sub["complete"]:
                diagnostics.append(_diag("softlock", f"depuis le point de sauvegarde {checkpoint}, le boss {boss} "
                                         "n'est plus atteignable"))
    return _result(diagnostics, {"placesReached": len(reach), "places": len(graph["nodes"]),
                                 "flags": sorted(inventory), "budget": budget.limit},
                   inconclusive=not state["complete"])


def rpg(level, profile=None, budget=None):
    if "graph" in level:
        return rpg_graph(level, profile, budget)
    sem = semantics(level)
    budget = budget or Budget((profile or {}).get("budget"))
    spawn = next((e for e in sem["entities"] if e["type"] in SPAWNS), None)
    if spawn is None:
        return _result([_diag("spawn-missing", "aucun point d'apparition")])
    state = _rpg_fixpoint(level, sem, (spawn["x"], spawn["y"]), set(), budget)
    reach, inventory, done = state["reach"], state["inventory"], state["done"]
    diagnostics = []
    for entity in sem["entities"]:
        key = str(entity["props"].get("quest") or entity["id"])
        if entity["type"] == "quest" and key not in done:
            missing = sorted(_split(entity["props"].get("requires")) - inventory)
            where = "hors d'atteinte" if not _cells(entity) & reach else f"prérequis manquants : {', '.join(missing)}"
            diagnostics.append(_diag("quest-unreachable", f"quête {key} inaccessible ({where})", quest=key))
        required = entity["type"] in {"boss", "checkpoint", "place", "transition"} or \
            entity["props"].get("required") is True
        if required and not _cells(entity) & reach:
            diagnostics.append(_diag("place-unreachable", f"lieu obligatoire {entity['type']} {entity['id']} "
                                     "inatteignable", entity=entity["id"]))
    bosses = [e for e in sem["entities"] if e["type"] == "boss" and _cells(e) & reach]
    for checkpoint in (e for e in sem["entities"] if e["type"] == "checkpoint" and _cells(e) & reach):
        first = next(i for i, r in enumerate(state["reaches"]) if _cells(checkpoint) & r)
        held = {item for item, when in state["gainedAt"].items() if when < first}
        sub = _rpg_fixpoint(level, sem, (checkpoint["x"], checkpoint["y"]), held, budget)
        for boss in bosses:
            if not _cells(boss) & sub["reach"] and sub["complete"]:
                diagnostics.append(_diag("softlock", f"depuis le point de sauvegarde {checkpoint['id']}, le boss "
                                         f"{boss['id']} n'est plus atteignable"))
    return _result(diagnostics, {"questsDone": sorted(done), "reachableCells": len(reach), "budget": budget.limit},
                   inconclusive=not state["complete"])


# --- Plateforme : simulation à pas fixe --------------------------------------------------------------------------

PLATFORM_DEFAULTS = {"runSpeed": 6.0, "jumpVelocity": 12.0, "gravity": 30.0, "dt": 1 / 60, "maxAirTime": 3.0,
                     "speeds": 7, "margin": 0.0}


def _standable(sem, width, height, platforms):
    solid = sem["solid"]
    cells = {(x, y) for x in range(width) for y in range(height - 1) if (x, y) not in solid and (x, y + 1) in solid}
    return cells | {c for c in platforms if c not in solid}


def _platform_cells(sem):
    """Plateformes mobiles : chaque position de la trajectoire (pas d'une case) est une position où le joueur peut
    se poser, en attendant la plateforme au besoin ; la période fixe seulement le délai, jamais l'accessibilité."""
    cells = set()
    for entity in sem["entities"]:
        if entity["type"] not in {"moving-platform", "movingplatform", "platform"}:
            continue
        x0, y0 = entity["x"], entity["y"]
        x1, y1 = int(entity["props"].get("toX", x0)), int(entity["props"].get("toY", y0))
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(steps + 1):
            px, py = round(x0 + (x1 - x0) * i / steps), round(y0 + (y1 - y0) * i / steps)
            for dx in range(entity["w"]):
                cells.add((px + dx, py - 1))
    return cells


def _jump(start, vx, vy0, params, solid, landing, stands, hazards, width, height):
    """Trajectoire à pas fixe des pieds du joueur depuis le bas de la case `start` ; rend la case d'atterrissage."""
    x, y = start[0] + 0.5, start[1] + 0.999
    vy, t = -vy0, 0.0
    dt, gravity = params["dt"], params["gravity"]
    while t < params["maxAirTime"]:
        vy += gravity * dt
        nx = x + vx * dt
        side = (int(nx), int(y - 0.001))
        if not 0 <= nx < width or side in solid:
            vx, nx = 0.0, x
        ny = y + vy * dt
        if ny - 0.001 < 0:
            vy, ny = 0.0, y
        cell = (int(nx), int(ny - 0.001))
        if cell[1] >= height:
            return None
        if cell in solid:
            if vy > 0:
                above = (cell[0], cell[1] - 1)
                return above if above in landing else None
            vy, ny = 0.0, y
            cell = (int(nx), int(ny - 0.001))
        elif cell in hazards:
            return None
        elif vy > 0 and cell in stands and int(y - 0.001) < cell[1]:
            return cell
        x, y, t = nx, ny, t + dt
    return None


def platformer(level, profile=None, budget=None):
    if "platformer" in level:
        return game_engine(level, profile, "platformer")
    sem = semantics(level)
    params = {**PLATFORM_DEFAULTS, **((profile or {}).get("platformer") or {})}
    margin = 1 - float(params.get("margin", 0))
    budget = budget or Budget((profile or {}).get("budget"))
    width, height, solid = level["width"], level["height"], sem["solid"]
    hazards = set().union(set(), *[_cells(e) for e in sem["entities"] if e["type"] in {"hazard", "spike", "danger"}])
    platforms = _platform_cells(sem)
    landing = _standable(sem, width, height, platforms)
    spawn = next((e for e in sem["entities"] if e["type"] in SPAWNS), None)
    goals = [e for e in sem["entities"] if e["type"] in OBJECTIVES]
    if spawn is None or not goals:
        return _result([_diag("platformer-incomplete", "plateforme sans apparition ou sans objectif")])
    speeds = [params["runSpeed"] * margin * (i / (params["speeds"] - 1) * 2 - 1) for i in range(params["speeds"])]
    edges = {}

    def moves(cell):
        if cell in edges:
            return edges[cell]
        out = set()
        for dx in (-1, 1):
            side = (cell[0] + dx, cell[1])
            if 0 <= side[0] < width and side not in solid and side not in hazards:
                if side in landing:
                    out.add(side)
                else:
                    fall = _jump(side, 0.0, 0.0, params, solid, landing, platforms, hazards, width, height)
                    if fall:
                        out.add(fall)
        for vx in speeds:
            target = _jump(cell, vx, params["jumpVelocity"] * margin, params, solid, landing, platforms, hazards,
                           width, height)
            if target and target != cell:
                out.add(target)
        edges[cell] = out
        return out

    start = (spawn["x"], spawn["y"])
    seen, queue, complete = {start}, deque([start]), True
    while queue:
        if not budget.spend():
            complete = False
            break
        cell = queue.popleft()
        for nxt in moves(cell):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    diagnostics = []
    for goal in goals:
        if not _cells(goal) & seen and complete:
            diagnostics.append(_diag("jump-out-of-range", f"objectif {goal['id']} hors de portée de saut (vitesse "
                                     f"{params['runSpeed']}, impulsion {params['jumpVelocity']}, marge "
                                     f"{params.get('margin', 0)})", goal=goal["id"]))
    for checkpoint in (e for e in sem["entities"] if e["type"] == "checkpoint"):
        if not _cells(checkpoint) & seen and complete:
            diagnostics.append(_diag("checkpoint-unreachable", f"point de contrôle {checkpoint['id']} inatteignable"))
    return _result(diagnostics, {"reachableStands": len(seen), "movingPlatformCells": len(platforms),
                                 "params": params}, inconclusive=not complete)


# --- Circuit ----------------------------------------------------------------------------------------------------

def circuit(level, profile=None, budget=None):
    """Boucle fermée, points de contrôle dans l'ordre (`order`), largeur minimale du profil de kart, sans sortie de
    piste ; la longueur du tour est mesurée sur le chemin trouvé, jamais inventée."""
    if "circuit" in level:
        return game_engine(level, profile, "circuit")
    sem = semantics(level)
    params = (profile or {}).get("circuit") or {}
    radius = max(0, (int(params.get("minWidth", 1)) - 1) // 2)
    budget = budget or Budget((profile or {}).get("budget"))
    width, height, track = level["width"], level["height"], sem["track"]
    drivable = {c for c in track if all((c[0] + dx, c[1] + dy) in track for dx in range(-radius, radius + 1)
                                        for dy in range(-radius, radius + 1))}
    start = set().union(set(), *[_cells(e) for e in sem["entities"] if e["type"] in {"start", "finish"}])
    groups = {}
    for entity in sem["entities"]:
        if entity["type"] == "checkpoint":
            groups.setdefault(int(entity["props"].get("order", 0)), set()).update(_cells(entity))
    if not start or not track:
        return _result([_diag("circuit-incomplete", "circuit sans ligne de départ ou sans couche de piste")])
    stops = [("départ", start), *((f"point {order}", groups[order]) for order in sorted(groups)), ("arrivée", start)]
    diagnostics = [_diag("checkpoint-off-track", f"{name} hors piste ou piste trop étroite (largeur minimale "
                         f"{params.get('minWidth', 1)})") for name, cells in stops[:-1] if not cells & drivable]
    if diagnostics:
        return _result(diagnostics)
    around = {n for c in start for n in _neighbours(c, width, height) if n in drivable and n not in start}
    first = next(iter(sorted(around)), None)
    side, _ = _reach(first, width, height, lambda c: c in drivable and c not in start, Budget(budget.limit)) \
        if first else (set(), True)
    if not around or not around <= side:
        return _result([_diag("circuit-interrupted", "la piste ne forme pas une boucle : interrompue entre le départ "
                              "et l'arrivée")])
    total, complete = 0, True
    for (name_a, a), (name_b, b) in zip(stops, stops[1:]):
        other = set().union(set(), *[cells for _, cells in stops if cells is not a and cells is not b])
        path = _distance(a & drivable, b & drivable, lambda c: c in drivable and c not in other, width, height,
                         budget)
        if path is None and budget.used > budget.limit:
            complete = False
            break
        if path is None:
            loose = _distance(a & drivable, b & drivable, lambda c: c in drivable, width, height,
                              Budget(budget.limit))
            code = "circuit-interrupted" if loose is None else "checkpoints-out-of-order"
            diagnostics.append(_diag(code, f"de {name_a} à {name_b} : " + (
                "piste interrompue" if loose is None else "la piste passe d'abord par un autre point de contrôle")))
            continue
        total += path
    metrics = {"lapCells": total if not diagnostics else None, "minWidth": params.get("minWidth", 1),
               "kart": params.get("kart")}
    if not diagnostics and params.get("speedTilesPerSecond"):
        metrics["indicativeLapSeconds"] = round(total / float(params["speedTilesPerSecond"]), 2)
    return _result(diagnostics, metrics, inconclusive=not complete)


def _distance(sources, targets, passable, width, height, budget):
    if not sources or not targets:
        return None
    seen = {c: 0 for c in sources}
    queue = deque(sources)
    while queue:
        if not budget.spend():
            return None
        cell = queue.popleft()
        if cell in targets and seen[cell] > 0:
            return seen[cell]
        for nxt in _neighbours(cell, width, height):
            if nxt in targets and nxt not in seen:
                return seen[cell] + 1
            if nxt not in seen and passable(nxt):
                seen[nxt] = seen[cell] + 1
                queue.append(nxt)
    return None






# --- Puzzle : le moteur du jeu, sans écran ------------------------------------------------------------------------

def puzzle(level, profile=None, budget=None):
    """Les règles d'un puzzle appartiennent au jeu (arbitrage 7-2949) : on n'en réimplémente rien."""
    return game_engine(level, profile, "puzzle")


def game_engine(level, profile, key):
    """Niveau natif d'un jeu (`level[key]`, gardé tel quel) : le profil du jeu déclare sa commande de validation sans
    écran (`engine.command`, lancée dans `engine.cwd`), qui importe le moteur du jeu ; elle reçoit le niveau en
    fichier et répond par ligne `OK <id> …` ou `ÉCHEC <id> : motif`. Sans elle : `inconclusive`, jamais `pass`."""
    import json
    import subprocess
    import tempfile

    engine = (profile or {}).get("engine")
    if not engine or key not in level:
        return {"status": "inconclusive", "diagnostics": [_diag(
            "no-validator", f"{key} : le profil du jeu doit déclarer engine.command (moteur du jeu sans écran)",
            severity="warning")], "metrics": {}}
    native = level[key]
    name = re.sub(r"[^\w.-]+", "-", str(native.get("id") or native.get("name") or level["name"]))[:80]
    with tempfile.TemporaryDirectory(prefix="level-engine-") as folder:
        path = Path(folder) / f"{name}.json"
        path.write_text(json.dumps(native, ensure_ascii=False))
        try:
            run = subprocess.run([*engine["command"], str(path)], cwd=engine.get("cwd"), capture_output=True,
                                 text=True, timeout=engine.get("timeout", 120))
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "inconclusive", "diagnostics": [_diag("engine-unavailable", f"moteur du jeu : {exc}")],
                    "metrics": {}}
    lines = [line for line in run.stdout.splitlines() if line.startswith(("OK ", "ÉCHEC "))]
    metrics = {"engine": " ".join(engine["command"]), "exitCode": run.returncode, "verdict": lines[-1] if lines else None}
    if run.returncode == 0 and lines and lines[-1].startswith("OK "):
        return _result([], metrics)
    if lines and lines[-1].startswith("ÉCHEC "):
        return _result([_diag(f"{key}-rejected-by-engine", lines[-1].split(" : ", 1)[-1])], metrics)
    return _result([_diag("engine-unreadable", f"réponse du moteur illisible (code {run.returncode})",
                          severity="warning")], metrics, inconclusive=True)


def validate(record, profile=None, known_assets=None, others=None):
    """Gates communes puis validateur du genre ; `puzzle` n'a pas encore de validateur (il importera le moteur du jeu)."""
    level = record["content"]
    report = {"common": common(record, level, known_assets)}
    if others is not None:
        report["common"]["diagnostics"] += transitions(record, level, others)
        report["common"] = _result(report["common"]["diagnostics"], report["common"]["metrics"])
    specific = VALIDATORS.get(record["kind"])
    if specific:
        report[record["kind"]] = specific(level, profile)
    else:
        report[record["kind"]] = {"status": "inconclusive", "diagnostics": [_diag(
            "no-validator", f"aucun validateur pour le genre {record['kind']} : il importera le moteur du jeu",
            severity="warning")], "metrics": {}}
    statuses = [part["status"] for part in report.values()]
    status = "fail" if "fail" in statuses else "inconclusive" if "inconclusive" in statuses else "pass"
    return {"status": status, "checks": report,
            "diagnostics": [d for part in report.values() for d in part["diagnostics"]]}


VALIDATORS = {"dungeon": dungeon, "rpg": rpg, "platformer": platformer, "circuit": circuit, "puzzle": puzzle}
