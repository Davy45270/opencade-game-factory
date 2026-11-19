"""Empreintes visuelles et propositions de rapprochement."""

from collections import defaultdict

import numpy as np
from PIL import Image

N = 32
MAX_DISTANCE = 8
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
    return {"phash": phash, "dhash": dhash}


def _bands(phash):
    # With at most eight different bits, one of nine disjoint bands must match.
    for band in range(MAX_DISTANCE + 1):
        bits = 8 if band == MAX_DISTANCE else 7
        yield band, (phash >> (7 * band)) & ((1 << bits) - 1)


def _similar(images):
    index = defaultdict(list)
    for order, (b, sha_b, ratio_b, phash_b, dhash_b) in enumerate(images):
        candidates = set()
        for band in _bands(phash_b):
            candidates.update(index[band])
            index[band].append(order)
        for candidate in sorted(candidates):
            a, sha_a, ratio_a, phash_a, dhash_a = images[candidate]
            if sha_a == sha_b or max(ratio_a, ratio_b) > 1.1 * min(ratio_a, ratio_b):
                continue
            distance = (phash_a ^ phash_b).bit_count()
            if distance <= MAX_DISTANCE:
                yield {"a": a, "b": b, "phashDistance": distance,
                       "dhashDistance": (dhash_a ^ dhash_b).bit_count(), "status": "needs-review"}


def duplicates(assets):
    locations = defaultdict(list)
    images = []
    for asset in sorted(assets, key=lambda a: a["id"]):
        if asset["family"]["type"] != "code-generated":
            locations[asset["sha256"]].extend(asset["files"]["locations"])
        if "perceptual" in asset:
            geometry = asset["dimensions"]
            hashes = asset["perceptual"]
            images.append((asset["id"], asset["sha256"], geometry["width"] / geometry["height"],
                           int(hashes["phash"], 16), int(hashes["dhash"], 16)))
    exact = [{"sha256": sha, "locations": paths}
             for sha, paths in sorted(locations.items()) if len(paths) > 1]
    return {"exact": exact, "similar": sorted(_similar(images), key=lambda pair: (pair["a"], pair["b"]))}
