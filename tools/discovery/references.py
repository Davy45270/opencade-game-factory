"""Références littérales des blobs, sans évaluation de code."""

import fnmatch
import posixpath
import re
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from functools import lru_cache
from urllib.parse import unquote

from tools.core.catalog import InvalidJSON, parse_json, write_json
from tools.discovery import formats
from tools.discovery.enrich import tokens, trace

LITERAL = r"""(?:'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`)"""
LEXER = re.compile(r"(?P<literal>" + LITERAL + r")|(?P<comment>/\*[\s\S]*?\*/|(?<!:)//[^\n]*|<!--[\s\S]*?-->)")
LOADERS = {
    "image": None, "spritesheet": "sprite", "atlas": "atlas", "multiatlas": "atlas",
    "audio": None, "svg": None, "bitmapFont": "font", "tilemapTiledJSON": "tilemap", "json": None,
}
CALL = re.compile(r"\b(?:(?P<loader>this\s*\.\s*load\s*\.\s*(?:"
                  + "|".join(LOADERS) + r"))|(?P<glob>import\.meta\.glob)|(?P<url>new\s+URL))\s*\(")
SCENE = re.compile(r"\b(?:(?P<super>super)\s*\(\s*(?:\{\s*key\s*:\s*)?"
                   r"|(?P<add>scene\s*\.\s*add)\s*\(\s*)(?P<quote>['\"])")
MARKUP_URL = re.compile(r"\burl\(\s*(?P<css>[^\s)'\"]+)\s*\)|\b(?:src|href)\s*=\s*(?P<html>[^\s>'`\"]+)", re.I)
NAMED_IMPORT = re.compile(r"\bimport\s+(\w+)\s+from\s*$")
ROLES = {"atlas": "atlas", "font": "font", "tilemap": "tilemap", "tileset": "tilemap",
         "shader": "shader", "style": "style"}
PATH_ROLES = {"background": {"background", "fond", "horizon", "decor"},
              "icon": {"icon", "icons", "icone"}, "ui": {"ui", "hud", "button", "bouton"},
              "music": {"music", "musique", "bgm"}}


@dataclass(frozen=True)
class Reference:
    value: str
    line: int
    method: str
    name: str | None = None
    loader: str | None = None


def roots(path, tree):
    package = posixpath.dirname(path)
    while package and posixpath.join(package, "package.json") not in tree:
        package = posixpath.dirname(package)
    parts = path.split("/")
    if not package and len(parts) > 2 and parts[0] == "packages":
        package = "/".join(parts[:2])
    return package


def candidates(path, value, tree, *, glob=False):
    value = unquote(value if glob else re.split(r"[?#]", value, maxsplit=1)[0])
    if not value or "\\" in value or re.match(r"^(?:[\w+.-]+:|//)", value):
        return []
    package = roots(path, tree)
    locations = [posixpath.join(package, "public"), package]
    if package:
        locations.extend(["public", ""])
    if not value.startswith("/"):
        locations.insert(0, posixpath.dirname(path))
    result = (posixpath.normpath(posixpath.join(folder, value.lstrip("/"))) for folder in locations)
    return list(dict.fromkeys(p for p in result if p not in {".", ".."} and not p.startswith("../")))


def glob_match(path, pattern):
    parts, patterns = path.split("/"), pattern.split("/")

    @lru_cache(maxsize=None)
    def match(i, j):
        if j == len(patterns):
            return i == len(parts)
        if patterns[j] == "**":
            return match(i, j + 1) or (i < len(parts) and match(i + 1, j))
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], patterns[j]) and match(i + 1, j + 1)

    return match(0, 0)


def resolve(path, reference, tree, indexed):
    glob = reference.method == "import.meta.glob"
    for option in candidates(path, reference.value, tree, glob=glob):
        if glob:
            hits = [file for file in indexed if glob_match(file, option)]
            if hits:
                return sorted(hits)
        elif option in indexed:
            return [option]
    return []


def resolve_path_alias(candidates, aliases, available):
    """Retourne les chemins cités et résolus pour une correspondance unique."""
    matches = {}
    for cited in candidates:
        for source, target in aliases:
            prefix, suffix = source.split("*")
            match = re.fullmatch(re.escape(prefix) + r"([^/\\\x00-\x1f]*)" + re.escape(suffix), cited)
            if match:
                resolved = target.replace("*", match[1])
                if PurePosixPath(resolved).name not in {"", ".", ".."} and resolved in available:
                    matches.setdefault(resolved, cited)
    if len(matches) == 1:
        resolved, cited = next(iter(matches.items()))
        return cited, resolved
    return None


def _literal(value):
    if re.fullmatch(LITERAL, value) and not (value.startswith("`") and "${" in value):
        return re.sub(r"""\\(['"`/\\])""", r"\1", value[1:-1])
    return None


def _args(source, start, tokens_by_start):
    """Retourne les plages d’arguments de premier niveau."""
    stack = []
    args = []
    left = right = start
    while right < len(source):
        if right in tokens_by_start:
            right = tokens_by_start[right].end()
            continue
        char = source[right]
        if char in "([{":
            stack.append(char)
        elif char in ")]}":
            if not stack:
                return [*args, (left, right)] if char == ")" else []
            stack.pop()
        elif char == "," and not stack:
            args.append((left, right))
            left = right + 1
        right += 1
    return []


def analyse(path, source):
    kind = formats.extension(path)
    lexer_tokens = [m for m in LEXER.finditer(source)
                    if m["literal"] or (kind not in {"json", "webmanifest"})]
    masked_parts, uncommented_parts = [], []
    offset = 0
    for match in lexer_tokens:
        prefix = source[offset:match.start()]
        blank = re.sub(r"[^\n]+", lambda part: " " * len(part[0]), match[0])
        masked_parts.extend((prefix, match[0][0] + blank[1:] if match["literal"] else blank))
        uncommented_parts.extend((prefix, match[0] if match["literal"] else blank))
        offset = match.end()
    masked = "".join((*masked_parts, source[offset:]))
    uncommented = "".join((*uncommented_parts, source[offset:]))
    tokens_by_start = {m.start(): m for m in lexer_tokens}
    newlines = [m.start() for m in re.finditer("\n", source)]

    def line(offset):
        return 1 + bisect_right(newlines, offset)

    scene, scene_method = path, "module-path"
    for match in SCENE.finditer(masked):
        literal = tokens_by_start.get(match.end() - 1)
        if literal and (value := _literal(literal[0])) and value.strip():
            scene, scene_method = value, "phaser-super" if match["super"] else "phaser-scene-add"
            break

    found, dynamic, handled = [], set(), []

    def log(start, end):
        excerpt = " ".join(source[start:end].split())[:200]
        if excerpt:
            dynamic.add((line(start), excerpt))

    if kind in formats.CODE or kind == "html":
        for call in CALL.finditer(masked):
            args = _args(source, call.end(), tokens_by_start)
            if not args:
                continue
            if call["url"] and (len(args) != 2 or re.sub(r"\s+", "", uncommented[slice(*args[1])]) != "import.meta.url"):
                continue
            handled.append((call.start(), args[-1][1]))
            loader = call["loader"].rsplit(".", 1)[-1].strip() if call["loader"] else None
            method = f"phaser.load.{loader}" if loader else "import.meta.glob" if call["glob"] else "new URL"
            key = _literal(uncommented[slice(*args[0])].strip()) if loader else None
            if loader and key is None:
                log(call.start(), args[-1][1] + 1)
                continue
            urls = args[1:3] if loader in {"atlas", "bitmapFont"} else args[1:2] if loader else args[:1]
            for start, end in urls:
                argument = uncommented[start:end].strip()
                literal = _literal(argument)
                if literal is not None:
                    found.append(Reference(literal, line(call.start()), method, key, loader))
                elif (loader == "audio" or call["glob"]) and argument.startswith("[") and argument.endswith("]"):
                    elements = [m for m in LEXER.finditer(argument) if m["literal"]]
                    residual = LEXER.sub("", argument[1:-1])
                    values = [_literal(m[0]) for m in elements]
                    if values and all(value is not None for value in values) and not residual.strip(", \t\r\n"):
                        found.extend(Reference(value, line(call.start()), method, key, loader) for value in values)
                    else:
                        log(call.start(), args[-1][1] + 1)
                else:
                    log(call.start(), args[-1][1] + 1)

    if kind in {"css", "scss", "html", "tsx", "jsx", "vue", "svelte"}:
        for match in MARKUP_URL.finditer(uncommented):
            value = match["css"] or match["html"]
            if "${" in value or value.startswith(("{", "$", "var(")):
                log(match.start(), match.end())
            else:
                found.append(Reference(value, line(match.start()), "css-url" if match["css"] else "html-attribute"))
    pwa_icons = set()
    if kind == "webmanifest" or PurePosixPath(path).name == "manifest.json":
        try:
            document = parse_json(source)
        except InvalidJSON:
            document = None
        icons = document.get("icons") if isinstance(document, dict) else None
        if isinstance(icons, list):
            pwa_icons = {icon["src"] for icon in icons if isinstance(icon, dict) and isinstance(icon.get("src"), str)}
    for match in lexer_tokens:
        if not match["literal"] or any(start <= match.start() < end for start, end in handled):
            continue
        raw = match[0]
        value = _literal(raw)
        suffix = re.search(r"\.([a-zA-Z0-9]+)$", re.split(r"[?#]", raw[1:-1], maxsplit=1)[0])
        extension = suffix[1].lower() if suffix else ""
        if extension not in formats.SUPPORTED | {"css", "scss", "webmanifest"}:
            continue
        before = masked[max(0, match.start() - 250):match.start()]
        after = masked[match.end():match.end() + 250]
        concatenated = kind not in {"json", "webmanifest"} and (
            re.search(r"\+\s*\(*\s*$", before) or re.match(r"\s*\)*\s*\+", after))
        if value is None or concatenated:
            log(match.start(), match.end())
            continue
        named = NAMED_IMPORT.search(before)
        if named or re.search(r"\bimport\s*$", before):
            method = "import"
        elif re.search(r"url\(\s*$", before):
            method = "css-url"
        elif re.search(r"\b(?:src|href)\s*=\s*$", before):
            method = "html-attribute"
        elif value in pwa_icons and re.search(r'"src"\s*:\s*$', uncommented[max(0, match.start() - 250):match.start()]):
            method = "pwa-icon"
        else:
            method = "literal"
        found.append(Reference(value, line(match.start()), method, named[1] if named else None))
    return scene, scene_method, found, sorted(dynamic)


def explicit_data_targets(modules, tree, indexed):
    return {target for path, (_, _, refs, _) in modules.items()
            for ref in refs if ref.loader in {"json", "multiatlas"}
            for target in resolve(path, ref, tree, indexed)}


def role_for(asset, path, ref):
    if ref.method == "pwa-icon":
        return "icon", "icons[].src", 0.95
    if ref.loader and LOADERS[ref.loader]:
        return LOADERS[ref.loader], f"this.load.{ref.loader}", 0.95
    family = asset["family"]["type"]
    if family in ROLES:
        return ROLES[family], family, 0.9
    words = {word.lower() for word in tokens(path)}
    if family == "audio":
        return ("music", "music token", 0.8) if words & PATH_ROLES["music"] else ("sfx", family, 0.55)
    for role in ("background", "icon", "ui"):
        if match := words & PATH_ROLES[role]:
            return role, ", ".join(sorted(match)), 0.75
    return "sprite", family, 0.45


def usage(copy, commit, path, game, scene, scene_method, asset, asset_path, ref, releases):
    role, basis, confidence = role_for(asset, asset_path, ref)
    return {"repo": copy.name, "provider": copy.provider, "game": game or copy.name, "scene": scene,
            "commit": commit, "codeRef": {"path": path, "line": ref.line},
            "role": role, "importName": ref.name or PurePosixPath(asset_path).stem or asset_path,
            "evidence": [f"{ref.method}: {asset_path}", f"{scene_method}: {scene}"],
            "status": "active", "releases": releases, "assetPath": asset_path,
            "inference": {"role": trace("heuristic", confidence, basis)}}


def emit(root, assets):
    by_asset, by_scene = {}, defaultdict(set)
    removed = []
    for asset in sorted(assets, key=lambda item: item["id"]):
        asset_id = asset["id"]
        by_asset[asset_id] = asset["usages"]
        for use in asset["usages"]:
            if use["status"] == "active":
                by_scene["/".join((use["repo"], use["game"], use["scene"]))].add(asset_id)
            else:
                removed.append({"assetId": asset_id, **use})
    destination = root / "generated"
    destination.mkdir(exist_ok=True)
    write_json(destination / "usage-index.json",
               {"byAsset": by_asset, "byScene": {k: sorted(v) for k, v in by_scene.items()}})
    (destination / "reports").mkdir(exist_ok=True)
    write_json(destination / "reports" / "removed-in-use.json", removed)
