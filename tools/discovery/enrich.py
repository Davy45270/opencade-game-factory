"""Inférences révisables à partir des noms et des chemins."""

import re
import unicodedata
from pathlib import PurePosixPath

ORIENTATIONS = {
    "three-quarter": "3-4 trois-quarts three-quarter", "isometric": "iso isometric isometrique",
    "front": "face front avant", "back": "dos back", "left": "gauche left",
    "right": "droite right", "top": "dessus top", "bottom": "dessous bottom",
}
STATES = {
    "clean": "propre clean", "dirty": "sale dirty", "broken": "casse broken",
    "open": "ouvert open", "closed": "ferme closed", "idle": "idle",
    "walk": "walk marche", "run": "run course", "jump": "jump saut", "hit": "hit choc",
}
CATEGORIES = {
    "characters": "personnages characters", "kitchen": "cuisine kitchen",
    "ui": "ui hud bouton boutons button buttons icone icones icon icons",
    "environments": "decor fond fonds background backgrounds horizon environments",
    "audio": "audio music musique sfx son", "fonts": "font fonts police",
}
SUBCATEGORIES = {
    "utensils": "ustensile ustensiles utensil utensils", "icons": "icone icones icon icons",
    "buttons": "bouton boutons button buttons", "backgrounds": "decor fond background horizon",
    "music": "musique music", "sfx": "sfx",
}
STYLES = {"pixel-art": "pixel-art pixelart", "cartoon-vector": "cartoon-vector",
          "cartoon": "cartoon", "low-poly": "low-poly", "watercolor": "watercolor aquarelle"}
DIRECTIONS = {"N": "N", "NE": "NE", "E": "E", "SE": "SE", "S": "S",
              "SW": "SW", "W": "W", "NW": "NW", "O": "W", "SO": "SW", "NO": "NW"}


def trace(method, confidence, *evidence):
    return {"method": method, "confidence": confidence, "evidence": list(evidence)}


def tokens(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return re.findall(r"[A-Za-z0-9]+(?:-(?:4|quarts|quarter|art|vector|poly)\b)?", value)


def enrich(asset, path, universe=None):
    words = tokens(f"{PurePosixPath(path).with_suffix('')}/{asset['name']}")
    normalized = {word.lower() for word in words}
    inference = asset["inference"]

    def set_field(key, value, word, method="path-tokens", confidence=0.75):
        previous = inference.get(key)
        if previous and previous["method"] in {"proven", "provenance-file"}:
            return
        asset[key] = value
        inference[key] = trace(method, confidence, f"{path} · {word}")

    for field, values in (("orientation", ORIENTATIONS), ("state", STATES),
                          ("category", CATEGORIES), ("subcategory", SUBCATEGORIES), ("visualStyle", STYLES)):
        for value, synonyms in values.items():
            found = next((word for word in synonyms.split() if word in normalized), None)
            if found:
                set_field(field, value, found)
                break
    direction = next((word for word in reversed(words) if word.upper() in DIRECTIONS
                      and (len(word) > 1 or word.isupper())), None)
    if direction:
        set_field("orientation", "isometric", direction)
        set_field("facing", DIRECTIONS[direction.upper()], direction)
    elif asset["orientation"] in {"left", "right"}:
        set_field("facing", asset["orientation"], asset["orientation"])
    elif asset["orientation"] in {"three-quarter", "isometric"}:
        for facing in ("left", "right"):
            found = next((word for word in ORIENTATIONS[facing].split() if word in normalized), None)
            if found:
                set_field("facing", facing, found)
                break
    parts = PurePosixPath(path).parts
    for folder in ("universes", "univers", "worlds"):
        if folder in parts[:-2]:
            universe = parts[parts.index(folder) + 1]
            break
    if universe and (universe.casefold() in {part.casefold() for part in parts[:-1]}
                     or universe.casefold() in normalized):
        set_field("originUniverse", universe, universe)
    tags = sorted({asset[key] for key in ("state", "subcategory", "visualStyle")
                   if asset.get(key) not in (None, "unknown")})
    if tags:
        set_field("tags", tags, ", ".join(tags))
    if asset.get("description", "").startswith("Ressource ") or "description" not in inference:
        name = " ".join(tokens(asset["name"])) or asset["name"]
        name = name[:1].upper() + name[1:]
        family = asset["family"]["type"]
        dimensions = asset["dimensions"]
        size = f" {dimensions['width']}×{dimensions['height']}" if dimensions else ""
        set_field("description", f"{name} — {family}{size}", asset["name"], "heuristic", 0.2)
