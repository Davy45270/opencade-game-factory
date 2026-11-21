"""Adaptateurs de formats (EXT-002 § 3) : Tiled JSON (.tmj/.json), Tiled TMX (.tmx) et tilesets .tsx, LDtk (.ldtk/.ldtkl).

Chaque adaptateur rend une forme canonique proche de Tiled — couches, gids bruts (drapeaux de retournement compris),
propriétés, tilesets, objets, décalages, orientation — et la liste `losses` de ce que la conversion n'a pas
conservé. Une conversion ne prétend jamais être sans perte : `losses` est toujours présent, même vide.
Aucun code n'est exécuté ; le XML portant DOCTYPE ou ENTITY est refusé (pas d'expansion d'entités).
"""

import base64
import gzip
import json
import math
import zlib
from pathlib import PurePosixPath
from xml.etree import ElementTree

LEVEL_EXTENSIONS = {".tmx", ".tmj", ".json", ".ldtk", ".ldtkl"}
TILESET_EXTENSIONS = {".tsx", ".tsj"}
CODE_EXTENSIONS = {".lua", ".ts", ".js", ".py"}
OTHER_EXTENSIONS = {".xml", ".blend"}
SCANNED = LEVEL_EXTENSIONS | TILESET_EXTENSIONS | CODE_EXTENSIONS | OTHER_EXTENSIONS
FLIP_MASK = 0xE0000000
TILED_KEPT = {"width", "height", "tilewidth", "tileheight", "orientation", "layers", "tilesets", "properties",
              "type", "infinite", "renderorder", "tiledversion", "version", "nextlayerid", "nextobjectid",
              "compressionlevel", "staggeraxis", "staggerindex", "hexsidelength"}
COLLISION_NAMES = {"collision", "collisions", "solid", "solids", "walls", "murs"}
TRACK_NAMES = {"track", "piste", "road", "route"}
# Types d'objets en français des cartes des jeux de David (Pestouille : « lieu », « sortie »…) → type canonique.
TYPE_ALIASES = {"lieu": "place", "sortie": "transition", "depart": "spawn", "départ": "spawn",
                "point-de-sauvegarde": "checkpoint", "cle": "key", "clé": "key", "porte": "door",
                "interrupteur": "switch", "objectif": "goal"}


class Unsupported(ValueError):
    """Format non reconnu ou non pris en charge : le fichier va au rapport d'exceptions, jamais au silence."""


def props(value):
    """Propriétés Tiled [{name,type,value}] ou LDtk {name: value} → dict nom → valeur."""
    if isinstance(value, dict):
        return dict(value)
    return {row["name"]: row.get("value") for row in value or ()}


def _decode(data, encoding, compression, count):
    if encoding in (None, "", "csv"):
        if isinstance(data, list):
            return [int(v) for v in data]
        return [int(v) for v in str(data).replace("\n", "").split(",") if v.strip()]
    if encoding != "base64":
        raise Unsupported(f"encodage de couche inconnu : {encoding}")
    raw = base64.b64decode(str(data).strip())
    if compression == "zlib":
        raw = zlib.decompress(raw)
    elif compression == "gzip":
        raw = gzip.decompress(raw)
    elif compression:
        raise Unsupported(f"compression de couche non prise en charge : {compression}")
    values = [int.from_bytes(raw[i:i + 4], "little") for i in range(0, len(raw), 4)]
    if count is not None and len(values) != count:
        raise Unsupported("couche de tuiles tronquée")
    return values


# --- Tiled JSON -----------------------------------------------------------------------------------------------

def _tiled_layer(layer, losses, path=""):
    name = path + layer.get("name", "")
    common = {"name": name, "offset": [layer.get("offsetx", 0), layer.get("offsety", 0)],
              "properties": layer.get("properties", []), "visible": layer.get("visible", True)}
    kind = layer.get("type")
    if kind == "tilelayer":
        if "chunks" in layer:
            raise Unsupported("carte infinie (chunks) non prise en charge")
        count = layer.get("width", 0) * layer.get("height", 0)
        return [{**common, "type": "tiles", "width": layer.get("width"), "height": layer.get("height"),
                 "data": _decode(layer.get("data"), layer.get("encoding"), layer.get("compression"), count)}]
    if kind == "objectgroup":
        return [{**common, "type": "objects", "objects": layer.get("objects", [])}]
    if kind == "group":
        rows = []
        for child in layer.get("layers", []):
            rows += _tiled_layer(child, losses, name + "/")
        return rows
    losses.append(f"couche {name} de type {kind} non normalisée (conservée dans l'original)")
    return []


def parse_tiled_json(raw, read=None, name="map"):
    data = json.loads(raw)
    if data.get("type") not in (None, "map") or "layers" not in data:
        raise Unsupported("JSON sans structure de carte Tiled")
    if data.get("infinite"):
        raise Unsupported("carte Tiled infinie non prise en charge")
    losses = [f"champ Tiled {key} non conservé" for key in sorted(set(data) - TILED_KEPT)]
    layers = []
    for layer in data["layers"]:
        layers += _tiled_layer(layer, losses)
    tilesets, diagnostics = [], []
    for row in data.get("tilesets", []):
        tilesets.append(_tileset_ref(row.get("firstgid"), row.get("source"), row, read, diagnostics))
    return [_canonical("tiled-json", name, data["width"], data["height"], data["tilewidth"], data["tileheight"],
                       data.get("orientation", "orthogonal"), data.get("properties", []), tilesets, layers,
                       losses, diagnostics)]


def _tileset_ref(firstgid, source, inline, read, diagnostics):
    row = {"firstgid": firstgid, "source": source, "external": bool(source)}
    if not source:
        row.update(name=inline.get("name"), properties=inline.get("properties", []), resolved=True,
                   image=inline.get("image"))
        return row
    content = read(source) if read else None
    if content is None:
        diagnostics.append({"code": "tileset-missing", "severity": "error",
                            "message": f"tileset externe introuvable : {source}"})
        row.update(resolved=False, properties=[])
        return row
    tileset = parse_tileset(content, source)
    row.update(resolved=True, name=tileset["name"], properties=tileset["properties"], image=tileset.get("image"))
    return row


def parse_tileset(raw, source="tileset"):
    if PurePosixPath(source).suffix == ".tsj":
        data = json.loads(raw)
        return {"name": data.get("name"), "properties": data.get("properties", []), "image": data.get("image")}
    root = _xml(raw)
    if root.tag != "tileset":
        raise Unsupported("fichier .tsx sans <tileset>")
    image = root.find("image")
    return {"name": root.get("name"), "properties": _xml_props(root), "image": image.get("source") if image is not None
            else None}


# --- Tiled TMX -------------------------------------------------------------------------------------------------

def _xml(raw):
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise Unsupported("XML avec DOCTYPE ou ENTITY refusé")
    try:
        return ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise Unsupported(f"XML illisible : {exc}") from None


def _number(value, default=0):
    if value is None:
        return default
    number = float(value)
    return int(number) if number.is_integer() else number


def _xml_props(node):
    block = node.find("properties")
    rows = []
    for prop in block.findall("property") if block is not None else ():
        kind = prop.get("type", "string")
        value = prop.get("value", prop.text or "")
        if kind in ("int", "object"):
            value = int(value)
        elif kind == "float":
            value = float(value)
        elif kind == "bool":
            value = value == "true"
        rows.append({"name": prop.get("name"), "type": kind, "value": value})
    return rows


def _tmx_layers(node, losses, prefix=""):
    layers = []
    for child in node:
        name = prefix + child.get("name", "")
        common = {"name": name, "offset": [_number(child.get("offsetx")), _number(child.get("offsety"))],
                  "properties": _xml_props(child), "visible": child.get("visible", "1") != "0"}
        if child.tag == "layer":
            data = child.find("data")
            if data.find("chunk") is not None:
                raise Unsupported("carte infinie (chunks) non prise en charge")
            count = int(child.get("width")) * int(child.get("height"))
            if data.get("encoding") is None and data.find("tile") is not None:
                values = [int(tile.get("gid", 0)) for tile in data.findall("tile")]
            else:
                values = _decode(data.text or "", data.get("encoding"), data.get("compression"), count)
            layers.append({**common, "type": "tiles", "width": int(child.get("width")),
                           "height": int(child.get("height")), "data": values})
        elif child.tag == "objectgroup":
            objects = []
            for obj in child.findall("object"):
                row = {"id": int(obj.get("id", 0)), "name": obj.get("name", ""),
                       "type": obj.get("type", obj.get("class", "")), "x": _number(obj.get("x")),
                       "y": _number(obj.get("y")), "width": _number(obj.get("width")),
                       "height": _number(obj.get("height")), "rotation": _number(obj.get("rotation")),
                       "properties": _xml_props(obj)}
                if obj.get("gid"):
                    row["gid"] = int(obj.get("gid"))
                objects.append(row)
            layers.append({**common, "type": "objects", "objects": objects})
        elif child.tag == "group":
            layers += _tmx_layers(child, losses, name + "/")
        elif child.tag in ("imagelayer",):
            losses.append(f"couche image {name} non normalisée (conservée dans l'original)")
    return layers


def parse_tmx(raw, read=None, name="map"):
    root = _xml(raw)
    if root.tag != "map":
        raise Unsupported("TMX sans élément <map>")
    if root.get("infinite") == "1":
        raise Unsupported("carte Tiled infinie non prise en charge")
    losses, diagnostics = [], []
    layers = _tmx_layers(root, losses)
    tilesets = []
    for node in root.findall("tileset"):
        tilesets.append(_tileset_ref(int(node.get("firstgid")), node.get("source"),
                                     {"name": node.get("name"), "properties": _xml_props(node),
                                      "image": (node.find("image").get("source") if node.find("image") is not None
                                                else None)}, read, diagnostics))
    if root.find("editorsettings") is not None:
        losses.append("editorsettings TMX non conservés")
    return [_canonical("tiled-tmx", name, int(root.get("width")), int(root.get("height")), int(root.get("tilewidth")),
                       int(root.get("tileheight")), root.get("orientation", "orthogonal"), _xml_props(root), tilesets,
                       layers, losses, diagnostics)]


# --- LDtk ------------------------------------------------------------------------------------------------------

def _ldtk_level(level, project, read, losses, diagnostics):
    layers_raw = level.get("layerInstances")
    if layers_raw is None and level.get("externalRelPath"):
        content = read(level["externalRelPath"]) if read else None
        if content is None:
            diagnostics.append({"code": "external-level-missing", "severity": "error",
                                "message": f"niveau LDtk externe introuvable : {level['externalRelPath']}"})
            layers_raw = []
        else:
            layers_raw = json.loads(content).get("layerInstances") or []
    grid = project.get("defaultGridSize", 16)
    layers = []
    for layer in reversed(layers_raw or []):  # LDtk liste du haut vers le bas ; Tiled du bas vers le haut
        grid = layer.get("__gridSize", grid)
        common = {"name": layer["__identifier"], "offset": [layer.get("__pxTotalOffsetX", 0),
                                                           layer.get("__pxTotalOffsetY", 0)],
                  "properties": [], "visible": layer.get("visible", True)}
        kind = layer["__type"]
        if kind == "IntGrid":
            layers.append({**common, "type": "tiles", "width": layer["__cWid"], "height": layer["__cHei"],
                           "data": list(layer.get("intGridCsv", []))})
            if layer.get("autoLayerTiles"):
                losses.append(f"tuiles automatiques de {layer['__identifier']} non normalisées (règles LDtk)")
        elif kind == "Entities":
            objects = []
            for entity in layer.get("entityInstances", []):
                fields = {f["__identifier"]: f.get("__value") for f in entity.get("fieldInstances", [])}
                objects.append({"id": entity.get("iid"), "name": entity["__identifier"],
                                "type": entity["__identifier"].lower(), "x": entity["px"][0], "y": entity["px"][1],
                                "width": entity.get("width", grid), "height": entity.get("height", grid),
                                "rotation": 0, "properties": [{"name": k, "type": "ldtk", "value": v}
                                                               for k, v in sorted(fields.items())]})
            layers.append({**common, "type": "objects", "objects": objects})
        else:
            losses.append(f"couche LDtk {layer['__identifier']} ({kind}) : tuiles non converties en gids")
    width, height = math.ceil(level["pxWid"] / grid), math.ceil(level["pxHei"] / grid)
    fields = [{"name": f["__identifier"], "type": "ldtk", "value": f.get("__value")}
              for f in level.get("fieldInstances", [])]
    canonical = _canonical("ldtk", level["identifier"], width, height, grid, grid, "orthogonal", fields,
                           [{"firstgid": None, "source": t.get("relPath"), "name": t.get("identifier"),
                             "external": bool(t.get("relPath")), "resolved": True, "properties": []}
                            for t in project.get("defs", {}).get("tilesets", [])], layers, losses, diagnostics)
    canonical["world"] = {"worldX": level.get("worldX"), "worldY": level.get("worldY"),
                          "layout": project.get("worldLayout"), "neighbours": level.get("__neighbours", [])}
    canonical["extensions"] = {"ldtk": {"defs": project.get("defs", {}), "iid": level.get("iid"),
                                        "externalRelPath": level.get("externalRelPath")}}
    return canonical


def parse_ldtk(raw, read=None, name="world"):
    project = json.loads(raw)
    if "levels" not in project and "layerInstances" in project:
        project = {"levels": [project], "defs": {}, "defaultGridSize": 16}
    if "levels" not in project:
        raise Unsupported("JSON sans structure LDtk")
    results = []
    for level in project["levels"]:
        losses, diagnostics = [], []
        results.append(_ldtk_level(level, project, read, losses, diagnostics))
    return results


def _canonical(fmt, name, width, height, tile_width, tile_height, orientation, properties, tilesets, layers, losses,
               diagnostics):
    return {"format": fmt, "name": name, "width": width, "height": height, "tileWidth": tile_width,
            "tileHeight": tile_height, "orientation": orientation, "properties": properties, "tilesets": tilesets,
            "layers": layers, "losses": losses, "diagnostics": diagnostics}


def parse(path, raw, read=None):
    """Rend la liste des niveaux d'un fichier ; Unsupported si le format n'est pas un niveau reconnu."""
    suffix = PurePosixPath(path).suffix.lower()
    stem = PurePosixPath(path).stem
    if suffix == ".tmx":
        return parse_tmx(raw, read, stem)
    if suffix in (".ldtk", ".ldtkl"):
        return parse_ldtk(raw, read, stem)
    if suffix in (".tmj", ".json"):
        try:
            data = json.loads(raw)
        except ValueError:
            raise Unsupported("JSON illisible") from None
        if isinstance(data, dict) and ("jsonVersion" in data or "levels" in data and "defs" in data):
            return parse_ldtk(raw, read, stem)
        if isinstance(data, dict) and "tilewidth" in data and "layers" in data:
            return parse_tiled_json(raw, read, stem)
        if isinstance(data, dict) and isinstance(data.get("terrain"), list) and "spawn" in data:
            return parse_ascii_grid(data, stem)
        if isinstance(data, dict) and isinstance(data.get("regions"), dict) and "transitions" in data:
            return parse_world_graph(data, read, stem)
        if isinstance(data, dict) and {"rules", "objects", "scoring"} <= set(data):
            return parse_game_puzzle(data, stem)
        raise Unsupported("JSON qui n'est ni une carte Tiled, ni un projet LDtk, ni un plan en grille, ni un graphe de monde")
    raise Unsupported(f"format {suffix or '—'} non pris en charge")


# --- Plans en grille ASCII (Pestouille) et graphes de monde ------------------------------------------------------

GRID_WALLS = {"#"}


def parse_ascii_grid(data, name):
    """Plan en grille ASCII : `terrain` (lignes, `#` = mur), `spawn`, `exits[]` (cible, drapeaux requis), `entities[]`.
    Le genre vient du nom du fichier (`dungeon.json` → donjon, sinon RPG). Les décors ajoutés au chargement par le
    jeu (empreintes bloquantes) ne sont pas dans le plan : c'est une perte déclarée."""
    size = int(data.get("tileSize", 16))
    rows = data["terrain"]
    width, height = int(data.get("width", len(rows[0]) if rows else 0)), int(data.get("height", len(rows)))
    cells = [1 if (rows[y][x] if y < len(rows) and x < len(rows[y]) else "#") in GRID_WALLS else 0
             for y in range(height) for x in range(width)]
    objects, number = [], 0

    def obj(kind, at, name_, properties):
        nonlocal number
        number += 1
        objects.append({"id": number, "name": name_, "type": kind, "x": at["x"] * size, "y": at["y"] * size,
                        "width": size, "height": size,
                        "properties": [{"name": k, "type": "string", "value": v} for k, v in properties.items()]})
    obj("spawn", data["spawn"], "spawn", {})
    for entity in data.get("entities", []):
        extra = {"definitionId": entity["definitionId"]} if entity.get("definitionId") else {}
        obj(entity.get("kind", "entity"), entity["at"], entity.get("id", ""), extra)
    for exit_ in data.get("exits", []):
        extra = {"target": exit_.get("targetMapId", ""), "targetSpawn": exit_.get("targetSpawn", "")}
        if exit_.get("requiredFlags"):
            extra["requires"] = ",".join(exit_["requiredFlags"])
        obj("transition", exit_["at"], exit_.get("id", ""), extra)
    kind = "dungeon" if name == "dungeon" or str(data.get("id", "")).endswith("_dungeon") else "rpg"
    layers = [{"name": "collision", "offset": [0, 0], "properties": [], "visible": True, "type": "tiles",
               "width": width, "height": height, "data": cells},
              {"name": "entities", "offset": [0, 0], "properties": [], "visible": True, "type": "objects",
               "objects": objects}]
    losses = ["décors posés par le jeu au chargement (empreintes bloquantes) absents du plan"]
    losses += [f"champ {key} non conservé" for key in sorted(set(data) - {"id", "regionId", "width", "height",
                                                                         "tileSize", "terrain", "spawn", "exits",
                                                                         "entities"})]
    return [_canonical("ascii-grid", str(data.get("id", name)), width, height, size, size, "orthogonal",
                       [{"name": "kind", "type": "string", "value": kind},
                        {"name": "region", "type": "string", "value": data.get("regionId", "")}],
                       [], layers, losses, [])]


def parse_world_graph(data, read, name):
    """Graphe de monde : `regions` {région: [lieux]}, `transitions` [[a, b]] (praticables dans les deux sens),
    `gates` [{target, requires}], `checkpoints` ; une région sans transition interne se parcourt librement. Son complément de progression (`start`, `grants` {lieu: drapeau},
    portes supplémentaires) vit, par convention du jeu, dans le fichier voisin nommé d'après son `id`."""
    nodes = sorted(f"{region}.{place}" for region, places in data["regions"].items() for place in places)
    gates, grants, start = list(data.get("gates", [])), dict(data.get("grants", {})), data.get("start")
    losses, diagnostics = [], []
    overlay_name = f"{data.get('id')}.json" if data.get("id") else None
    overlay = read(overlay_name) if read and overlay_name and overlay_name != f"{name}.json" else None
    if overlay is not None:
        extra = json.loads(overlay)
        gates += extra.get("gates", [])
        grants.update(extra.get("grants", {}))
        start = extra.get("start", start)
    edges = {tuple(sorted(edge)) for edge in data["transitions"]}
    for region, places in data["regions"].items():
        # Règle du jeu (pestouille-rpg, packages/world) : une région sans transition interne se parcourt librement ;
        # une région qui en a ne suit que ses transitions.
        if not any(a.startswith(f"{region}.") and b.startswith(f"{region}.") for a, b in data["transitions"]):
            edges |= {tuple(sorted((f"{region}.{a}", f"{region}.{b}"))) for a in places for b in places if a < b}
    graph = {"nodes": nodes, "edges": [list(edge) for edge in sorted(edges)],
             "gates": sorted(({"target": g["target"], "requires": g["requires"]} for g in gates),
                             key=lambda g: (g["target"], g["requires"])),
             "grants": dict(sorted(grants.items())), "start": start, "checkpoints": sorted(data.get("checkpoints", [])),
             "bosses": [n for n in nodes if n.rsplit(".", 1)[-1] == "boss"], "overlay": overlay_name if overlay else None}
    for node in [e for edge in graph["edges"] for e in edge] + [g["target"] for g in graph["gates"]] + \
            list(grants) + graph["checkpoints"] + ([start] if start else []):
        if node not in nodes:
            diagnostics.append({"code": "graph-unknown-place", "severity": "error",
                                "message": f"lieu inconnu du graphe : {node}"})
    # Un graphe n'a pas de grille : sa géométrie compte ses lieux (largeur) sur une ligne, pour le contrat du schéma.
    level = _canonical("world-graph", str(data.get("id", name)), len(nodes), 1, 1, 1, "graph",
                       [{"name": "kind", "type": "string", "value": "rpg"}], [], [], losses, diagnostics)
    level["graph"] = graph
    return [level]


def parse_game_puzzle(data, name):
    """Niveau de puzzle propre à un jeu (Cozy Room Sort : `rules`, `objects`, `scoring`, `meta.solution`) : gardé tel
    quel dans `puzzle`, car ses règles appartiennent au jeu (EXT-002) ; seul le moteur du jeu le valide."""
    objects = data.get("objects") or []
    level = _canonical("game-puzzle", str(data.get("id", name)), max(1, len(objects)), 1, 1, 1, "puzzle",
                       [{"name": "kind", "type": "string", "value": "puzzle"}], [], [], [], [])
    level["puzzle"] = data
    return [level]


def to_tiled_json(level):
    """Export Tiled JSON (EXT-002 LV-04) : aller-retour des couches, gids, drapeaux, propriétés, objets, tilesets."""
    layers = []
    for index, layer in enumerate(level["layers"], start=1):
        row = {"id": index, "name": layer["name"], "offsetx": layer["offset"][0], "offsety": layer["offset"][1],
               "opacity": 1, "visible": layer.get("visible", True), "x": 0, "y": 0}
        if layer["properties"]:
            row["properties"] = layer["properties"]
        if layer["type"] == "tiles":
            row.update(type="tilelayer", width=layer["width"], height=layer["height"], data=layer["data"])
        else:
            row.update(type="objectgroup", draworder="topdown", objects=layer["objects"])
        layers.append(row)
    tilesets = [{"firstgid": t["firstgid"], "source": t["source"]} if t.get("external") else
                {k: v for k, v in (("firstgid", t["firstgid"]), ("name", t.get("name")), ("image", t.get("image")),
                                   ("properties", t.get("properties"))) if v not in (None, [])}
                for t in level["tilesets"]]
    out = {"type": "map", "orientation": level["orientation"], "width": level["width"], "height": level["height"],
           "tilewidth": level["tileWidth"], "tileheight": level["tileHeight"], "infinite": False, "layers": layers,
           "tilesets": tilesets, "renderorder": "right-down"}
    if level["properties"]:
        out["properties"] = level["properties"]
    return out


# --- Sémantique ------------------------------------------------------------------------------------------------

def semantics(level):
    """Cellules pleines, piste, entités (en cases) et références d'assets d'un niveau canonique."""
    tw, th = level["tileWidth"], level["tileHeight"]
    solid, track = set(), set()
    for layer in level["layers"]:
        if layer["type"] != "tiles":
            continue
        name = layer["name"].rsplit("/", 1)[-1].lower()
        flags = props(layer["properties"])
        target = solid if name in COLLISION_NAMES or flags.get("collision") is True else \
            track if name in TRACK_NAMES or flags.get("track") is True else None
        if target is None:
            continue
        for index, gid in enumerate(layer["data"]):
            if gid & ~FLIP_MASK:
                target.add((index % layer["width"], index // layer["width"]))
    entities = []
    for layer in level["layers"]:
        if layer["type"] != "objects":
            continue
        for obj in layer["objects"]:
            kind = (obj.get("type") or obj.get("class") or obj.get("name") or "").lower()
            kind = TYPE_ALIASES.get(kind, kind)
            x = int((obj.get("x", 0) + layer["offset"][0]) // tw)
            y = int((obj.get("y", 0) + layer["offset"][1]) // th)
            entities.append({"id": str(obj.get("id")), "name": obj.get("name", ""), "type": kind, "x": x, "y": y,
                             "w": max(1, math.ceil((obj.get("width") or tw) / tw)),
                             "h": max(1, math.ceil((obj.get("height") or th) / th)),
                             "props": props(obj.get("properties"))})
    assets = []
    for source in [t.get("properties", []) for t in level["tilesets"]] + [e["props"] for e in entities]:
        values = props(source)
        if values.get("assetId"):
            assets.append({"id": values["assetId"], "version": values.get("assetVersion")})
    unique = {(a["id"], a["version"]): a for a in assets}
    return {"solid": solid, "track": track, "entities": entities,
            "assets": [unique[k] for k in sorted(unique, key=lambda k: (k[0], str(k[1])))]}
