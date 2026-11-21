"""Découpes déterministes et comparaison avec les cadres d’atlas."""

import io
import math

import numpy as np
from PIL import Image, ImageChops

COORDINATES = "xywh"
THRESHOLD = 0.02
MAX_RACCORD_COVERAGE = 0.75
MIN_PIXELS_OUTSIDE_RACCORDS = 1024


class RaccordCoverageError(ValueError):
    pass


def named_box(box):
    if (not isinstance(box, (list, tuple)) or len(box) != 4
            or any(type(x) is not int for x in box)):
        return None
    w, h, x, y = box
    if min(x, y) < 0 or min(w, h) < 1:
        return None
    return dict(x=x, y=y, w=w, h=h)


def in_image(box, image):
    return box["x"] + box["w"] <= image.width and box["y"] + box["h"] <= image.height


def crop(image, box, margin=0):
    x, y, w, h = (box[key] for key in COORDINATES)
    return image.crop((max(0, x - margin), max(0, y - margin),
                       min(image.width, x + w + margin), min(image.height, y + h + margin)))


def normalize(image, box, margin, size=None, anchor=None):
    return _normalize_crop(crop(image, box, margin), size, anchor)


def _normalize_crop(source, size, anchor):
    source = source.convert("RGBA")
    alpha = source.getchannel("A").point([0 if i < 0.04 * 255 else i for i in range(256)])
    source.putalpha(alpha)
    trimmed = source.getbbox()
    if alpha.getextrema() == (255, 255):
        rgb = source.convert("RGB")
        trimmed = ImageChops.difference(rgb, Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))).getbbox()
    if trimmed:
        source = source.crop(trimmed)
    if not size:
        return source
    width, height = size
    factor = min(width / source.width, height / source.height)
    scaled = source.resize((max(1, round(source.width * factor)), max(1, round(source.height * factor))),
                           Image.Resampling.LANCZOS)
    layer = Image.new("RGBA", size)
    y = height - scaled.height
    layer.paste(scaled, ((width - scaled.width) // 2, y if anchor == "bas" else y // 2))
    return layer


def flatten(image):
    background = Image.new("RGBA", image.size, (127, 127, 127, 255))
    background.alpha_composite(image.convert("RGBA"))
    return np.asarray(background.convert("RGB"), dtype=np.float64) / 255


def frame_size(value):
    if isinstance(value, str) and "x" in value.lower():
        pieces = value.lower().split("x")
        value = [int(v) for v in pieces] if all(v.isascii() and v.isdecimal() and len(v) <= 4 for v in pieces) else []
    if type(value) is int:
        value = [value, value]
    if not isinstance(value, list) or len(value) != 2 or any(type(v) is not int or not 0 < v <= 8192 for v in value):
        return None
    return tuple(value)


def _fraction(options, key, default):
    value = options.get(key, default)
    return value if type(value) in (int, float) and 0 <= value <= 1 else default


def _masked_edits(delta, box, margin, options):
    edits = options["effacements"]
    if not isinstance(edits, list):
        return False
    height, width, _ = delta.shape
    sx, sy = width / (box["w"] + 2 * margin), height / (box["h"] + 2 * margin)
    discarded = np.zeros((height, width), dtype=bool)
    for edit in edits:
        zone = named_box(edit.get("zone")) if isinstance(edit, dict) else None
        feather = edit.get("plume", 0) if zone else -1
        if not zone or type(feather) is not int or feather < 0:
            return False
        x0 = (zone["x"] - feather - box["x"] + margin) * sx
        y0 = (zone["y"] - feather - box["y"] + margin) * sy
        x1 = x0 + (zone["w"] + 2 * feather) * sx
        y1 = y0 + (zone["h"] + 2 * feather) * sy
        left, right = max(0, int(x0)), min(width, math.ceil(x1) + 1)
        top, bottom = max(0, int(y0)), min(height, math.ceil(y1) + 1)
        if left < right and top < bottom:
            discarded[top:bottom, left:right] = True
    if discarded.mean() > _fraction(options, "masque_max", 0.25):
        return False
    delta[discarded] = 0
    return True


def replay_raccords(reference, raccords):
    result = reference.copy()
    for band, target in raccords:
        # The game takes every band from the original crop and pastes it opaque.
        patch = crop(reference, band).resize((target["w"], target["h"]), Image.Resampling.LANCZOS)
        result.paste(patch.convert("RGB"), (target["x"], target["y"]))
    return result


def measure(image, box, margin, frame, anchor=None, *, options=None, raccords=None, normalizer=None):
    region = named_box(box)
    if not region or not in_image(region, image):
        return None
    options = options or {}
    if "taille" in options and frame_size(options["taille"]) != frame.size:
        return None
    if raccords is not None:
        source = crop(image, region, margin)
        if any(not in_image(box, source) for pair in raccords for box in pair):
            raise ValueError("Raccord hors de la découpe.")
        covered = np.zeros((source.height, source.width), dtype=bool)
        for _, target in raccords:
            x, y, w, h = (target[key] for key in COORDINATES)
            covered[y:y + h, x:x + w] = True
        covered_pixels = np.count_nonzero(covered)
        if covered_pixels >= MAX_RACCORD_COVERAGE * covered.size:
            raise RaccordCoverageError("raccord-target-coverage-exceeded")
        if covered.size - covered_pixels < MIN_PIXELS_OUTSIDE_RACCORDS:
            raise RaccordCoverageError("raccord-outside-pixels-below-minimum")
        image = replay_raccords(source, raccords)
        region = dict(x=0, y=0, w=image.width, h=image.height)
        margin = 0
    expected = (normalizer or normalize)(image, region, margin, frame.size, anchor)
    frame = frame.convert("RGBA")
    if not expected.getbbox() or not frame.getbbox():
        return None
    if raccords is None and options.get("detoure"):
        opaque = np.asarray(frame.getchannel("A")) >= 128
        if not opaque.any() or opaque.mean() < _fraction(options, "couverture_min", 0.05):
            return None
        delta = flatten(expected)[opaque] - np.asarray(frame.convert("RGB"))[opaque] / 255
    else:
        delta = flatten(expected) - flatten(frame)
        if raccords is None and options.get("effacements") and not _masked_edits(delta, region, margin, options):
            return None
    return float(np.sqrt(np.mean(delta ** 2)))


def canonical_png(image):
    pixels = image.convert("RGBA")
    pixels.info.clear()
    stream = io.BytesIO()
    pixels.save(stream, "PNG", optimize=False)
    return stream.getvalue()


def components(image):
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] < 255:
        mask = np.asarray(alpha) >= 11
    else:
        rgb = image.convert("RGB")
        corners = {rgb.getpixel(point) for point in ((0, 0), (rgb.width - 1, 0),
                   (0, rgb.height - 1), (rgb.width - 1, rgb.height - 1))}
        if len(corners) != 1:
            return []
        background = Image.new("RGB", rgb.size, corners.pop())
        mask = np.any(np.asarray(ImageChops.difference(rgb, background)) != 0, axis=2)
        if mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any():
            return []
    # Join contiguous horizontal runs. This keeps contiguous opaque areas cheap.
    parents, bounds, previous = [], [], []

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for y, row in enumerate(mask):
        edges = np.flatnonzero(np.diff(np.pad(row, 1)))
        current = []
        start = 0
        for left, right in zip(edges[::2], edges[1::2]):
            left, right = int(left), int(right)
            i = len(parents)
            parents.append(i)
            bounds.append((left, y, right, y + 1))
            current.append((left, right, i))
            while start < len(previous) and previous[start][1] <= left:
                start += 1
            j = start
            while j < len(previous) and previous[j][0] < right:
                a, b = root(i), root(previous[j][2])
                if a != b:
                    x0, y0, x1, y1 = bounds[a]
                    xx0, yy0, xx1, yy1 = bounds[b]
                    parents[a] = b
                    bounds[b] = min(x0, xx0), min(y0, yy0), max(x1, xx1), max(y1, yy1)
                j += 1
        previous = current
    return [dict(x=x, y=y, w=x1-x, h=y1-y, status="candidate")
            for i, (x, y, x1, y1) in enumerate(bounds) if parents[i] == i]
