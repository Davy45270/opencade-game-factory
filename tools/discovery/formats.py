"""Reconnaissance des formats par extension et structure du contenu."""

import io
import re
import struct
import wave
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from PIL import Image

from tools.core.catalog import InvalidJSON, parse_json

RASTER = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP", "gif": "GIF"}
AUDIO = frozenset("ogg mp3 wav m4a flac opus".split())
FONTS = {"ttf": b"\x00\x01\x00\x00", "otf": b"OTTO", "woff": b"wOFF", "woff2": b"wOF2"}
SHADERS = {"glsl": None, "vert": "vertex", "frag": "fragment", "wgsl": None}
CONDITIONAL = frozenset(("json", "ts", "js"))
SUPPORTED = frozenset(RASTER) | AUDIO | FONTS.keys() | SHADERS.keys() | CONDITIONAL | {
    "svg", "ase", "aseprite", "tmj", "tmx", "tsj", "tsx",
}
UNCOVERED = frozenset("psd xcf kra blend fla swf mid mod xm".split())
DRAW = re.compile(r"""\bgenerateTexture\s*\(|\bthis\s*\.\s*add\s*\.\s*graphics\s*\(|\bgetContext\s*\(\s*['"]2d['"]\s*\)|<svg\b""")
SYMBOL = re.compile(r"""\bgenerateTexture\s*\(\s*(?P<quote>['"])(?P<key>(?:\\.|(?! (?P=quote) )[^\\\r\n])+)(?P=quote)\s*(?=[,)])""", re.X)


@dataclass
class Format:
    family: dict
    dimensions: dict | None = None
    alpha: bool | None = None
    image: Image.Image | None = None
    symbols: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


class Unreadable(ValueError):
    pass


def extension(path):
    return PurePosixPath(path).suffix.lower().lstrip(".")


def dimensions(width, height):
    return {"width": width, "height": height}


def _raster(data, kind):
    if kind == "png":
        with Image.open(io.BytesIO(data), formats=["PNG"]) as probe:
            probe.verify()
    with Image.open(io.BytesIO(data), formats=[RASTER[kind]]) as image:
        mode = image.mode
        count = getattr(image, "n_frames", 1)
        durations = []
        alpha = False
        first = None
        for index in range(count):
            image.seek(index)
            rgba = image.convert("RGBA")
            alpha |= rgba.getchannel("A").getextrema()[0] < 255
            durations.append(image.info.get("duration"))
            if index == 0:
                first = rgba
        # Pillow obtains WebP frame timing when decoding pixels.
        if count > 1 and kind in {"gif", "webp"}:
            total = sum(durations) if all(isinstance(d, (float, int)) and d > 0 for d in durations) else 0
            family = {"type": "animation", "animation": {"frameCount": count,
                      "fps": count * 1000 / total if total else None, "mode": mode}}
        else:
            family = {"type": "image", "image": {"mode": mode}}
        return Format(family, dimensions(*first.size), alpha, first)


def _svg(data):
    root = ET.fromstring(data)
    if root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
        raise Unreadable("invalid-svg-root")
    attributes = {key: root.get(key) or None for key in ("width", "height", "viewBox")}
    sizes = [re.fullmatch(r"\s*([1-9]\d*)(?:px)?\s*", attributes[key] or "") for key in ("width", "height")]
    size = dimensions(*(int(match[1]) for match in sizes)) if all(sizes) else None
    return Format({"type": "svg", "svg": attributes}, size)


def _aseprite(data):
    length, magic, count, width, height = struct.unpack_from("<I4H", data)
    if len(data) < 128 or length != len(data) or magic != 0xA5E0 or not all((count, width, height)):
        raise Unreadable("invalid-aseprite-header")
    return Format({"type": "animation", "animation": {"frameCount": count, "fps": None}},
                  dimensions(width, height))


def _tile_size(value):
    if value is None or value == 0:
        return None
    if isinstance(value, str):
        value = int(value)
    if type(value) is not int or value < 1:
        raise Unreadable("invalid-tile-metadata")
    return value


def _tiled(attributes, is_map, layers=0):
    geometry = {"tileWidth": _tile_size(attributes.get("tilewidth")),
                "tileHeight": _tile_size(attributes.get("tileheight"))}
    version = attributes.get("tiledversion")
    metadata = {"tiledVersion": version} if isinstance(version, str) and version.strip() else {}
    if is_map:
        return Format({"type": "tilemap", "tilemap": {**geometry, "layerCount": layers}}, metadata=metadata)
    if None in geometry.values():
        raise Unreadable("missing-tileset-dimensions")
    return Format({"type": "tileset", "tileset": {**geometry,
                  "tileCount": _tile_size(attributes.get("tilecount"))}}, metadata=metadata)


def _tiled_xml(data, kind):
    root = ET.fromstring(data)
    if root.tag != {"tmx": "map", "tsx": "tileset"}[kind]:
        raise Unreadable("invalid-tiled-root")
    count = sum(node.tag in {"layer", "objectgroup", "imagelayer", "group"} for node in root.iter())
    return _tiled(root.attrib, kind == "tmx", count)


def _atlas(frames, image):
    entries = frames.items() if isinstance(frames, dict) else ((frame["filename"], frame) for frame in frames)
    result = []
    for name, item in entries:
        coords = {key: item["frame"][key] for key in ("x", "y", "w", "h")}
        if (not isinstance(name, str) or not name.strip() or
                any(type(value) is not int or value < (key in {"w", "h"}) for key, value in coords.items())):
            raise Unreadable("invalid-atlas-frame")
        result.append({"name": name, **coords})
    if not result:
        raise Unreadable("empty-atlas")
    return Format({"type": "atlas", "frames": result}, metadata={"atlasImage": image})


def _json(data, kind):
    try:
        obj = parse_json(data)
    except InvalidJSON:
        if kind != "json" or (b'"frames"' in data and b'"image"' in data) or b'"tiledversion"' in data:
            raise Unreadable("invalid-json") from None
        return None
    if not isinstance(obj, dict):
        if kind != "json":
            raise Unreadable("invalid-tiled-json")
        return None
    if kind != "json" or "tiledversion" in obj:
        is_map = kind == "tmj" or (kind == "json" and obj.get("type") != "tileset")
        if is_map:
            layers = obj.get("layers")
            if not isinstance(layers, list) or "tiledversion" not in obj:
                raise Unreadable("invalid-tilemap")
            count = 0
            pending = list(layers)
            while pending:
                layer = pending.pop()
                count += 1
                if isinstance(layer, dict) and isinstance(layer.get("layers"), list):
                    pending.extend(layer["layers"])
            return _tiled(obj, True, count)
        return _tiled(obj, False)
    meta = obj.get("meta")
    if "frames" in obj and isinstance(meta, dict) and "image" in meta:
        frames, image = obj["frames"], meta["image"]
        if not isinstance(frames, (list, dict)) or not isinstance(image, str) or not image.strip():
            raise Unreadable("invalid-atlas")
        return _atlas(frames, image)
    return None


def _audio(data, kind):
    duration = channels = rate = None
    if kind == "wav":
        with wave.open(io.BytesIO(data), "rb") as audio:
            rate, channels = audio.getframerate(), audio.getnchannels()
            frames = audio.getnframes()
            if len(audio.readframes(frames)) != frames * channels * audio.getsampwidth():
                raise Unreadable("truncated-wav")
            duration = frames / rate
    elif kind in {"ogg", "opus"}:
        if not data.startswith(b"OggS\0") or len(data) < 27:
            raise Unreadable("invalid-ogg-header")
        start = 27 + data[26]
        header = data[start:]
        if header.startswith(b"OpusHead") and len(header) >= 19:
            channels = header[9] or None
            rate = 48000
        elif header.startswith(b"\x01vorbis") and len(header) >= 16:
            channels = header[11] or None
            rate = int.from_bytes(header[12:16], "little") or None
        elif kind == "opus":
            raise Unreadable("missing-opus-header")
    elif kind == "mp3":
        if not ((len(data) >= 10 and data.startswith(b"ID3")) or
                (len(data) >= 4 and data[0] == 255 and data[1] & 0xE0 == 0xE0)):
            raise Unreadable("invalid-mp3-header")
    elif kind == "m4a" and (len(data) < 16 or data[4:8] != b"ftyp"):
        raise Unreadable("invalid-m4a-header")
    elif kind == "flac" and (len(data) < 8 or not data.startswith(b"fLaC")):
        raise Unreadable("invalid-flac-header")
    elif kind == "flac" and data[4] & 127 == 0 and len(data) >= 42:
        value = int.from_bytes(data[18:26], "big")
        rate = value >> 44 or None
        channels = ((value >> 41) & 7) + 1 if rate else None
        samples = value & ((1 << 36) - 1)
        duration = samples / rate if rate and samples else None
    return Format({"type": "audio", "audio": {"durationSec": duration, "channels": channels, "sampleRate": rate}})


def _sfnt_names(data):
    count, = struct.unpack_from(">H", data, 4)
    if len(data) < 12 + count * 16:
        raise Unreadable("truncated-font-directory")
    names = {}
    for index in range(count):
        tag, _, offset, length = struct.unpack_from(">4sIII", data, 12 + index * 16)
        if tag != b"name":
            continue
        table = data[offset:offset + length]
        _, count, start = struct.unpack_from(">HHH", table)
        if len(table) != length or not 6 + count * 12 <= start <= length:
            raise Unreadable("invalid-font-name-table")
        for n in range(count):
            platform, _, language, key, size, position = struct.unpack_from(">6H", table, 6 + n * 12)
            if platform not in {0, 1, 3} or key not in {1, 2, 16, 17}:
                continue
            raw = table[start + position:start + position + size]
            if len(raw) != size:
                raise Unreadable("truncated-font-name")
            text = raw.decode("mac_roman" if platform == 1 else "utf-16-be").strip()
            if text and (key not in names or language == 1033):
                names[key] = text
        break
    return names


def _font(data, kind):
    if len(data) < 12 or not data.startswith(FONTS[kind]):
        raise Unreadable("invalid-font-header")
    names = _sfnt_names(data) if kind in {"ttf", "otf"} else {}
    return Format({"type": "font", "font": {"family": names.get(16, names.get(1)),
                   "style": names.get(17, names.get(2))}})


def inspect(path, data):
    """Retourne les mesures du format, ou None pour un JSON/module ordinaire."""
    kind = extension(path)
    try:
        if kind in RASTER:
            return _raster(data, kind)
        if kind == "svg":
            return _svg(data)
        if kind in {"ase", "aseprite"}:
            return _aseprite(data)
        if kind in {"tmx", "tsx"}:
            return _tiled_xml(data, kind)
        if kind in {"json", "tmj", "tsj"}:
            return _json(data, kind)
        if kind in AUDIO:
            return _audio(data, kind)
        if kind in FONTS:
            return _font(data, kind)
        if kind in SHADERS:
            text = data.decode("utf-8-sig")
            if not text.strip() or "\0" in text:
                raise Unreadable("invalid-shader-source")
            return Format({"type": "shader", "shader": {"language": "WGSL" if kind == "wgsl" else "GLSL",
                           "stage": SHADERS[kind]}})
        if kind in {"ts", "js"}:
            text = data.decode("utf-8-sig")
            if DRAW.search(text):
                symbols = tuple(dict.fromkeys(match["key"] for match in SYMBOL.finditer(text)))
                return Format({"type": "code-generated"}, symbols=symbols)
        return None
    except Unreadable:
        raise
    except (OSError, SyntaxError, ValueError, KeyError, IndexError, TypeError, struct.error,
            ET.ParseError, wave.Error, EOFError, Image.DecompressionBombError, OverflowError) as exc:
        raise Unreadable(f"unreadable-{kind}") from exc


def is_generated_code(path, data):
    return extension(path) in {"ts", "js"} and bool(DRAW.search(data.decode("utf-8-sig", errors="replace")))
