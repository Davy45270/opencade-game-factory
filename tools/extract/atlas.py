"""Atlas Phaser JSON Hash et validation des cadres contre le catalogue."""

import io
import math
from pathlib import Path

from PIL import Image

from tools.cli import UsageError
from tools.core.catalog import InvalidJSON, json_text, read_json
from tools.core.exit_codes import ExitCode
from tools.discovery.importer import read_assets
from tools.extract.commands import _bounded_read, _image
from tools.extract.regions import canonical_png, in_image
from tools.publish.delivery import Delivery, check_destination, output_path, put, scoped_path

COORDINATES = ("x", "y", "w", "h")


def verify(atlas, image, assets):
    if image.format not in (None, "PNG") or image.mode != "RGBA" or image.getchannel("A").getextrema()[0] == 255:
        raise InvalidJSON("Atlas PNG RGBA avec transparence réelle requis.")
    if not isinstance(atlas, dict) or not isinstance(atlas.get("frames"), dict) or not atlas["frames"]:
        raise InvalidJSON("Un atlas Phaser JSON Hash exige des cadres nommés.")
    meta = atlas.get("meta")
    if not isinstance(meta, dict) or ("size" in meta and meta["size"] != {"w": image.width, "h": image.height}):
        raise InvalidJSON("Dimensions déclarées de l’atlas incorrectes.")
    for name, item in atlas["frames"].items():
        if not name.strip() or not isinstance(item, dict) or not isinstance(item.get("frame"), dict):
            raise InvalidJSON(f"Cadre invalide : {name}")
        asset_id = item.get("assetId", name)
        asset = assets.get(asset_id) if isinstance(asset_id, str) else None
        if not asset or not asset["dimensions"]:
            raise InvalidJSON(f"Référence d’asset introuvable ou dimensions inconnues : {asset_id!r}")
        box = item["frame"]
        if any(type(box.get(key)) is not int for key in COORDINATES):
            raise InvalidJSON(f"Coordonnées entières requises pour {name}.")
        dimensions = asset["dimensions"]
        if (box["w"], box["h"]) != (dimensions["width"], dimensions["height"]):
            raise InvalidJSON(f"Dimensions incompatibles pour {name}.")
        if min(box["x"], box["y"]) < 0 or min(box["w"], box["h"]) < 1 or not in_image(box, image):
            raise InvalidJSON(f"Cadre hors image : {name}")


def layout(images, padding):
    area = sum((image.width + padding) * (image.height + padding) for _, image in images)
    width = max(max(image.width + 2 * padding for _, image in images),
                math.isqrt(area) + 2 * padding)
    x = y = padding
    shelf_height = used = 0
    frames = {}
    for asset_id, image in images:
        if x > padding and x + image.width + padding > width:
            y += shelf_height + padding
            x, shelf_height = padding, 0
        frame = {"x": x, "y": y, "w": image.width, "h": image.height}
        size = {"w": image.width, "h": image.height}
        frames[asset_id] = {"frame": frame, "rotated": False, "trimmed": False,
                            "spriteSourceSize": {"x": 0, "y": 0, **size}, "sourceSize": size}
        x += image.width + padding
        used = max(used, x)
        shelf_height = max(shelf_height, image.height)
    return frames, (used, y + shelf_height + padding)


def export_atlas(root, args):
    if args.padding < 0:
        raise UsageError("--padding doit être positif ou nul.")
    if len(set(args.ids)) != len(args.ids):
        raise InvalidJSON("IDs répétés dans l’atlas.")
    output = output_path(root, args.out, kind="atlas")
    atlas_folder = root.resolve() / "atlases"
    if not output.is_relative_to(atlas_folder) or output == atlas_folder:
        raise UsageError("--out attend un nom sous atlases/.")
    base = output.with_suffix("") if output.suffix in {".png", ".json"} else output
    png = scoped_path(base.with_name(f"{base.name}.png"))
    json_path = scoped_path(base.with_name(f"{base.name}.json"))
    delivery = Delivery(root, args)
    images = [(asset_id, _image(delivery.bytes(delivery.asset(asset_id)))) for asset_id in args.ids]
    images.sort(key=lambda item: (-item[1].height, -item[1].width, item[0]))
    frames, size = layout(images, args.padding)
    if size[0] * size[1] > Image.MAX_IMAGE_PIXELS:
        raise InvalidJSON("Dimensions cumulées de l’atlas trop grandes.")
    image = Image.new("RGBA", size)
    for asset_id, pixels in images:
        frame = frames[asset_id]["frame"]
        image.paste(pixels, (frame["x"], frame["y"]))
    atlas = {"frames": frames, "meta": {"image": png.name, "format": "RGBA8888",
                                       "size": {"w": image.width, "h": image.height}, "scale": "1"}}
    verify(atlas, image, delivery.assets)
    outputs = [(png, canonical_png(image)), (json_path, json_text(atlas).encode())]
    for path, raw in outputs:
        check_destination(path, raw)
    if not args.dry_run:
        for path, raw in outputs:
            put(path, raw)
    return ExitCode.OK, {"ok": True, "atlas": str(json_path), "image": str(png), "frames": len(frames)}


def validate_atlas(root, args):
    path = scoped_path(root / args.file)
    try:
        atlas = read_json(path)
        name = atlas["meta"]["image"]
        if not isinstance(name, str) or not name or Path(name).name != name or "\\" in name or name in {".", ".."}:
            raise InvalidJSON("meta.image doit désigner un fichier voisin.")
        raw = _bounded_read(scoped_path(path.parent / name))
        with Image.open(io.BytesIO(raw)) as image:
            verify(atlas, image, read_assets(root))
    except (KeyError, TypeError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidJSON("JSON ou image d’atlas indisponible ou invalide.") from exc
    return ExitCode.OK, {"ok": True, "frames": len(atlas["frames"])}
