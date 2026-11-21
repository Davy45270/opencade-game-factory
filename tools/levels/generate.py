"""Génération et dérivation déterministes (EXT-002 § 4).

PRNG explicite et sérialisable (mulberry32), ordre canonique des itérations, aucune lecture de l'horloge :
snapshot + seed + version de l'algorithme + contraintes = même sortie normalisée, à l'octet.
Le découpage BSP de donjon suit l'algorithme standard (celui de ROT.js et libtcod) ; le registre étant en Python,
il est repris ici plutôt qu'appelé — décision écrite dans docs/ARCHITECTURE.md § Niveaux (ADR).
"""

import copy

from tools.levels.formats import FLIP_MASK

BSP_VERSION = "1.0.0"
FLIP_HORIZONTAL = 0x80000000


class Mulberry32:
    """PRNG 32 bits dont l'état tient dans un entier (sérialisable dans le rapport de génération)."""

    def __init__(self, seed):
        self.state = int(seed) & 0xFFFFFFFF

    def next(self):
        self.state = (self.state + 0x6D2B79F5) & 0xFFFFFFFF
        t = self.state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    def between(self, low, high):
        return low + int(self.next() * (high - low + 1))


def _split(rng, box, minimum, depth, leaves):
    x, y, w, h = box
    if depth == 0 or (w < 2 * minimum and h < 2 * minimum):
        leaves.append(box)
        return
    horizontal = h > w if abs(w - h) > 2 else rng.next() < 0.5
    if horizontal and h >= 2 * minimum:
        cut = rng.between(minimum, h - minimum)
        _split(rng, (x, y, w, cut), minimum, depth - 1, leaves)
        _split(rng, (x, y + cut, w, h - cut), minimum, depth - 1, leaves)
    elif w >= 2 * minimum:
        cut = rng.between(minimum, w - minimum)
        _split(rng, (x, y, cut, h), minimum, depth - 1, leaves)
        _split(rng, (x + cut, y, w - cut, h), minimum, depth - 1, leaves)
    else:
        leaves.append(box)


def bsp_dungeon(constraints, seed):
    width, height = int(constraints.get("width", 32)), int(constraints.get("height", 24))
    minimum, depth = int(constraints.get("minRoom", 6)), int(constraints.get("depth", 4))
    rng = Mulberry32(seed)
    leaves = []
    _split(rng, (1, 1, width - 2, height - 2), minimum, depth, leaves)
    floor, rooms = set(), []
    for x, y, w, h in leaves:
        rw, rh = rng.between(3, max(3, w - 2)), rng.between(3, max(3, h - 2))
        rx, ry = x + rng.between(0, max(0, w - rw - 1)), y + rng.between(0, max(0, h - rh - 1))
        rooms.append((rx, ry, rw, rh))
        floor |= {(cx, cy) for cx in range(rx, rx + rw) for cy in range(ry, ry + rh)}
    centres = [(rx + rw // 2, ry + rh // 2) for rx, ry, rw, rh in rooms]
    for (ax, ay), (bx, by) in zip(centres, centres[1:]):
        for cx in range(min(ax, bx), max(ax, bx) + 1):
            floor.add((cx, ay))
        for cy in range(min(ay, by), max(ay, by) + 1):
            floor.add((bx, cy))
    data = [0 if (x, y) in floor else 1 for y in range(height) for x in range(width)]
    tile = int(constraints.get("tileSize", 16))
    objects = [{"id": 1, "name": "spawn", "type": "spawn", "x": centres[0][0] * tile, "y": centres[0][1] * tile,
                "width": tile, "height": tile, "rotation": 0, "properties": []},
               {"id": 2, "name": "goal", "type": "goal", "x": centres[-1][0] * tile, "y": centres[-1][1] * tile,
                "width": tile, "height": tile, "rotation": 0, "properties": []}]
    level = {"format": "generated", "name": constraints.get("name", f"bsp-{seed}"), "width": width, "height": height,
             "tileWidth": tile, "tileHeight": tile, "orientation": "orthogonal", "properties": [],
             "tilesets": [], "losses": [], "diagnostics": [],
             "layers": [{"name": "collision", "type": "tiles", "width": width, "height": height, "data": data,
                         "offset": [0, 0], "properties": [], "visible": True},
                        {"name": "entities", "type": "objects", "objects": objects, "offset": [0, 0],
                         "properties": [], "visible": True}]}
    return level, {"seed": int(seed), "algorithm": "bsp", "algorithmVersion": BSP_VERSION,
                   "rngState": rng.state, "rooms": len(rooms)}


GENERATORS = {"dungeon": bsp_dungeon}


def mirror(level):
    """Miroir horizontal : colonnes inversées, drapeau de retournement horizontal basculé, objets reflétés."""
    out = copy.deepcopy(level)
    width = out["width"]
    for layer in out["layers"]:
        if layer["type"] == "tiles":
            rows = [layer["data"][i:i + layer["width"]] for i in range(0, len(layer["data"]), layer["width"])]
            layer["data"] = [gid ^ FLIP_HORIZONTAL if gid & ~FLIP_MASK else gid for row in rows for gid in reversed(row)]
        else:
            for obj in layer["objects"]:
                obj["x"] = width * out["tileWidth"] - obj.get("x", 0) - (obj.get("width") or out["tileWidth"])
    return out


TRANSFORMS = {"mirror": mirror}
