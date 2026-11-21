"""Empreintes visuelles et propositions de rapprochement."""

from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from tools.asset_versions import version_number

N = 32
MAX_DISTANCE = 8
# Règle de statut d'une paire similaire (HL-538, P0-08 : jamais de fusion automatique) : écart moyen par pixel,
# images composées sur gris moyen et réduites à 64 × 64 par moyenne d'aire (numpy pur, identique d'une machine à
# l'autre). Plafond du bruit mesuré sur 400 rééchantillonnages (±10 %) d'une même image du registre : 6,73 / 255.
# Au-dessus : « distinct », deux dessins différents. En dessous : même image à la précision du rééchantillonnage ;
# la paire reste « needs-review » tant qu'elle n'est pas liée en variante (`linked-variant`).
PIXEL_SIZE = 64
PIXEL_NOISE = 6.8
_DCT = np.cos(np.pi / N * np.arange(N)[:, None] * (np.arange(N) + 0.5))
_DCT[0] /= np.sqrt(2)
_DCT *= np.sqrt(2 / N)


def _hex(bits):
    return np.packbits(bits).tobytes().hex()


def fingerprints(image):
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (128, 128, 128, 255))
    gray = Image.alpha_composite(background, rgba).convert("L")
    square = np.asarray(gray.resize((N, N), Image.Resampling.LANCZOS), dtype=float)
    low = (_DCT @ square @ _DCT.T)[:8, :8].flatten()
    # Eliminate round-off around zero for constant images and exact symmetries.
    low = np.round(low, 8)
    phash = _hex(low > np.median(low[1:]))
    strip = np.asarray(gray.resize((9, 8), Image.Resampling.LANCZOS))
    dhash = _hex(strip[:, 1:] > strip[:, :-1])
    result = {"phash": phash, "dhash": dhash}
    red, green, blue, alpha = rgba.getextrema()
    if alpha == (255, 255) and all(low == high for low, high in (red, green, blue)):
        result["flatColor"] = f"{red[0]:02x}{green[0]:02x}{blue[0]:02x}"
    return result


def _bands(phash):
    # With at most eight different bits, one of nine disjoint bands must match.
    for band in range(MAX_DISTANCE + 1):
        bits = 8 if band == MAX_DISTANCE else 7
        yield band, (phash >> (7 * band)) & ((1 << bits) - 1)


def _similar(images):
    index = defaultdict(list)
    for order, (b, sha_b, ratio_b, phash_b, dhash_b, color_b) in enumerate(images):
        candidates = set()
        for band in _bands(phash_b):
            candidates.update(index[band])
            index[band].append(order)
        for candidate in sorted(candidates):
            a, sha_a, ratio_a, phash_a, dhash_a, color_a = images[candidate]
            if sha_a == sha_b or max(ratio_a, ratio_b) > 1.1 * min(ratio_a, ratio_b):
                continue
            if color_a and color_b and color_a != color_b:
                continue
            distance = (phash_a ^ phash_b).bit_count()
            if distance <= MAX_DISTANCE:
                yield {"a": a, "b": b, "phashDistance": distance,
                       "dhashDistance": (dhash_a ^ dhash_b).bit_count(), "status": "needs-review"}


def _weights(length, size):
    """Poids de recouvrement exact (aire) entre `length` pixels source et `size` cases cible."""
    edges = np.arange(size + 1) * (length / size)
    starts, ends = np.arange(length), np.arange(1, length + 1)
    overlap = np.clip(np.minimum(ends[None, :], edges[1:, None]) - np.maximum(starts[None, :], edges[:-1, None]), 0, None)
    return overlap / (length / size)


def _box(array, size):
    """Réduction par moyenne d'aire en numpy pur : même résultat d'une machine à l'autre (le rééchantillonnage de
    Pillow varie selon sa version et rendait generated/duplicates.json dépendant de l'environnement)."""
    rows, cols = _weights(array.shape[0], size), _weights(array.shape[1], size)
    data = array.astype(np.float64)
    return np.stack([rows @ data[..., c] @ cols.T for c in range(data.shape[2])], axis=-1)


def _pixels(root, asset):
    local = asset.get("files", {}).get("registry")
    if not root or not local:
        return None
    try:
        image = Image.open(Path(root) / local)
        image.load()
    except (OSError, ValueError):
        return None
    rgba = np.asarray(image.convert("RGBA"), dtype=np.int64)
    alpha = rgba[..., 3:4]
    flat = (rgba[..., :3] * alpha + 128 * (255 - alpha)) / 255
    return _box(flat, PIXEL_SIZE)


def rule(pair, assets_by_id, root, cache):
    """Statue une paire : déjà liée comme variante → `linked-variant` ; sinon par la mesure de pixels quand les deux
    binaires du registre sont lisibles. Règle du registre : un quasi-doublon devient une variante liée (champ
    `variants`), jamais une suppression ni une fusion."""
    if pair["b"] in assets_by_id[pair["a"]].get("variants", ()) or \
            pair["a"] in assets_by_id[pair["b"]].get("variants", ()):
        return {**pair, "status": "linked-variant"}
    for key in (pair["a"], pair["b"]):
        if key not in cache:
            cache[key] = _pixels(root, assets_by_id[key])
    a, b = cache[pair["a"]], cache[pair["b"]]
    if a is None or b is None:
        return pair
    distance = round(float(np.abs(a - b).mean()), 2)
    return {**pair, "pixelDistance": distance, "status": "distinct" if distance > PIXEL_NOISE else "needs-review"}


def duplicates(assets, root=None):
    locations = defaultdict(list)
    images = []
    identities = defaultdict(list)
    for asset in sorted(assets, key=lambda a: a["id"]):
        family = asset["family"]
        kind = family["type"] if isinstance(family, dict) else family
        digest = asset["sha256"].lower()
        if kind != "code-generated":
            identities[digest].append(asset["id"])
            locations[digest].extend(loc for loc in asset["files"]["locations"]
                                     if loc.get("assetVersion", 1) == version_number(asset))
        if "perceptual" in asset and (geometry := asset.get("dimensions")):
            hashes = asset["perceptual"]
            images.append((asset["id"], digest, geometry["width"] / geometry["height"],
                           int(hashes["phash"], 16), int(hashes["dhash"], 16), hashes.get("flatColor")))
    exact = [{"sha256": sha, "locations": paths, "ids": identities[sha]}
             for sha, paths in sorted(locations.items()) if len(paths) > 1 or len(identities[sha]) > 1]
    by_id, cache = {asset["id"]: asset for asset in assets}, {}
    similar = [rule(pair, by_id, root, cache) for pair in sorted(_similar(images), key=lambda p: (p["a"], p["b"]))]
    return {"exact": exact, "similar": similar}
