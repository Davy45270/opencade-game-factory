"""Import et extraction explicite de planches dans le registre."""

import hashlib
import io
import os
import tempfile
from pathlib import Path

from PIL import Image

from tools.core.catalog import Catalogue, CatalogueScopeError, InvalidJSON, json_text, parse_json, write_json
from tools.core.exit_codes import ExitCode
from tools.core.schemas import schemas
from tools.discovery import formats
from tools.discovery.enrich import enrich
from tools.discovery.importer import MAX_BLOB, Importer, _asset
from tools.discovery.repos import Git, GitError, select
from tools.discovery.scan import cache_path, directory_lock
from tools.extract import aseprite, regions
from tools.extract.sheets import _region_key, link_region, sheet_record, table_entries
from tools.publish.licenses import emit as emit_licenses
from tools.discovery.references import emit as emit_usages


def _bounded_read(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_BLOB + 1)
    if len(raw) > MAX_BLOB:
        raise OSError("Planche de plus de 64 Mio.")
    return raw


def _destination(root, relative, prefix):
    rel = Path(relative)
    if rel.is_absolute():
        try:
            rel = rel.relative_to(root)
        except ValueError as exc:
            raise CatalogueScopeError(f"Destination attendue sous {prefix}/.") from exc
    if len(rel.parts) < 2 or rel.parts[0] != prefix or ".." in rel.parts:
        raise CatalogueScopeError(f"Destination attendue sous {prefix}/.")
    path = root
    for part in rel.parts:
        path = Catalogue._regular_path(path / part)
    return path


def _blob(root, sheet, args):
    digest = sheet["sha256"]
    if not schemas().validator("sheet").is_valid(sheet):
        raise InvalidJSON(f"Planche invalide ({sheet['id']}).")
    if local := sheet["files"].get("registry"):
        raw = _bounded_read(_destination(root, local, "sources"))
        if hashlib.sha256(raw).hexdigest() == digest:
            return raw
        raise OSError("Empreinte de la planche locale différente du catalogue.")
    selected, _ = select(root, args)
    copies = {copy.key: copy for copy in selected}
    git = Git(root)
    for location in sheet["files"]["locations"]:
        copy = copies.get((location["repo"], location.get("provider")))
        commit, path = location["commit"], location["path"]
        if not copy:
            continue
        try:
            mirror = git.prepare(copy, cache_path(args), False)
            blob = next((blob for blob in git.tree(mirror, commit, sizes=True) if blob.path == path), None)
            if not blob or blob.symlink or blob.size > MAX_BLOB:
                continue
            with git.batch(mirror) as batch:
                raw = batch.read(blob, MAX_BLOB)
            if hashlib.sha256(raw).hexdigest() == digest:
                return raw
        except GitError:
            continue
    raise OSError("Planche indisponible dans les miroirs autorisés. Utilisez --cache pour indiquer le miroir du scan.")


def _image(raw):
    try:
        with Image.open(io.BytesIO(raw)) as image:
            return image.convert("RGBA")
    except (Image.DecompressionBombError, ValueError, OSError) as exc:
        raise OSError("Image de planche illisible.") from exc


def _read_table(path):
    raw = _bounded_read(path)
    document = parse_json(raw)
    entries = table_entries(document)
    if not isinstance(document, dict) or not isinstance(document.get("elements"), list) or len(entries) != len(document["elements"]):
        raise InvalidJSON("Table de découpe invalide (elements attendu).")
    return entries, hashlib.sha256(raw).hexdigest()


def _extract(target, sheet, image, entries, evidence, output=None, exact=False):
    results, outputs = [], {}
    region_assets = {}
    for item in sheet["regions"]:
        asset_id = item["assetId"]
        if asset_id in target.assets:
            identity = _region_key(sheet["id"], item)
            region_assets.setdefault(identity, []).append(asset_id)
    for entry in entries:
        name = entry.get("id")
        box = regions.named_box(entry.get("boite"))
        margin = entry.get("marge", 0)
        if not isinstance(name, str) or not name.strip() or not box or not regions.in_image(box, image):
            raise InvalidJSON("Élément de découpe invalide (id et boîte [w,h,x,y] dans la planche attendus).")
        if type(margin) is not int or not 0 <= margin <= max(image.size):
            raise InvalidJSON("Marge de découpe invalide.")
        expected = entry.get("planche_sha256")
        if expected is not None and expected != sheet["sha256"]:
            raise InvalidJSON("L’empreinte de la table ne correspond pas à la planche.")
        identity = _region_key(sheet["id"], box)
        size = regions.frame_size(entry["taille"]) if "taille" in entry else None
        if "taille" in entry and size is None:
            raise InvalidJSON("Taille de découpe attendue sous la forme N, WxH ou [W,H].")
        pixels = regions.crop(image, box) if exact else regions.normalize(image, box, margin, size, entry.get("ancre"))
        raw = regions.canonical_png(pixels)
        digest = hashlib.sha256(raw).hexdigest()
        linked = region_assets.get(identity, ())
        matching = [asset_id for asset_id in linked if target.assets[asset_id]["sha256"] == digest]
        if len(matching) > 1 or linked and not matching:
            raise InvalidJSON(f"La région de {name} correspond à une découpe existante différente ou ambiguë.")
        asset_id = matching[0] if matching else target.ids.allouer(identity, "sprite", name)
        if asset_id in {result["assetId"] for result in results}:
            raise InvalidJSON("Deux éléments décrivent la même région.")
        if asset_id in target.assets and target.assets[asset_id]["sha256"] != digest:
            raise InvalidJSON(f"La découpe modifierait le contenu existant de {asset_id}.")
        family = {"type": "sprite", "sprite": {"frameName": name}}
        asset = target.assets.get(asset_id)
        if asset is None:
            measured = formats.Format(family, formats.dimensions(*pixels.size),
                                      pixels.getchannel("A").getextrema()[0] < 255, pixels)
            asset = _asset(asset_id, name, evidence, None, None, None, digest, measured, family, "png")
            # A local table records the actual operation. It does not grant redistribution rights.
            asset.pop("creation")
            asset["provenance"].update(evidence=[evidence], sourceSheetSha256=sheet["sha256"])
            asset["files"]["sha256Method"] = "canonical-crop-png"
            enrich(asset, name)
            link_region(target, asset, sheet, box, True, evidence)
            target.assets[asset_id] = asset
        result, path = _attach_output(target, asset, output)
        outputs[path] = raw
        results.append(result)
    return results, outputs


def _attach_output(target, asset, output):
    asset_id = asset["id"]
    category = asset["category"] or "sprite"
    previous = asset["files"].get("registry")
    path = _destination(target.root, previous or f"{output or 'sprites/' + category}/{asset_id}.png", "sprites")
    if output and previous and path.parent != _destination(target.root, Path(output) / path.name, "sprites").parent:
        raise InvalidJSON(f"Une sortie est déjà enregistrée pour {asset_id}.")
    relative = path.relative_to(target.root).as_posix()
    if asset["status"] == "published" and previous != relative:
        raise CatalogueScopeError(f"La sortie de {asset_id} est publiée.")
    asset["files"]["registry"] = relative
    return {"assetId": asset_id, "path": relative, "sourceRegion": asset["sourceRegion"]}, path


def _extract_registered(target, sheet, args):
    frames = {asset["id"]: (asset, frame)
              for asset in target.assets.values()
              for frame in asset["files"].get("atlasFrames", ())
              if frame["atlasSheetId"] == sheet["id"]}
    for item in sheet["regions"]:
        asset = target.assets.get(item["assetId"])
        if asset and item["status"] == "verified" and asset["id"] not in frames:
            candidates = asset["files"].get("atlasFrames", ())
            frames[asset["id"]] = (asset, candidates[0] if candidates else {**item, "atlasSheetId": sheet["id"]})
    if not frames:
        raise InvalidJSON("Aucune région vérifiée. Indiquez --regions ou --candidates.")
    images, results, outputs = {}, [], {}
    for asset_id, (asset, frame) in sorted(frames.items()):
        if existing := asset["files"].get("registry"):
            raw = _bounded_read(_destination(target.root, existing, "sprites"))
        else:
            frame_sheet_id = frame["atlasSheetId"]
            if frame_sheet_id not in images:
                images[frame_sheet_id] = _image(_blob(target.root, target.sheets[frame_sheet_id], args))
            raw = regions.canonical_png(regions.crop(images[frame_sheet_id], frame))
        if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
            raise InvalidJSON(f"La région enregistrée ne reproduit pas {asset_id}. Indiquez --regions.")
        result, path = _attach_output(target, asset, args.out)
        results.append(result)
        outputs[path] = raw
    return results, outputs


def _save(target, outputs):
    for sheet in target.sheets.values():
        if not schemas().validator("sheet").is_valid(sheet):
            raise InvalidJSON(f"Planche invalide ({sheet['id']}).")
    for asset in target.assets.values():
        if not schemas().validator("asset").is_valid(asset):
            raise InvalidJSON(f"Asset invalide ({asset['id']}).")
    for path, raw in outputs.items():
        if path.exists() and (not path.is_file() or _bounded_read(path) != raw):
            raise CatalogueScopeError(f"Une sortie différente existe déjà pour {path.name}.")
    if target.dry_run:
        return
    for path, raw in outputs.items():
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".extract-", delete=False) as stream:
            temp = Path(stream.name)
            try:
                stream.write(raw)
                stream.close()
                os.link(temp, path)
            finally:
                temp.unlink(missing_ok=True)
    if target.ids.entries != target.initial_ids:
        write_json(target.ids_path, target.ids.entries)
    for asset_id, asset in target.assets.items():
        document = Catalogue._regular_path(target.catalogue.path / "assets" / f"{asset_id}.json")
        if not document.exists() or target.catalogue.read(document) != asset:
            write_json(document, asset)
    for sheet_id, sheet in target.sheets.items():
        if json_text(sheet) != target.initial_sheets.get(sheet_id):
            write_json(Catalogue._regular_path(target.catalogue.path / "sheets" / f"{sheet_id}.json"), sheet)
    emit_usages(target.root, target.assets.values())
    emit_licenses(target.root, target.assets.values(), target.sheets.values())


def preflight(root, args):
    args.sources = args.only = args.provider = None
    _, copies = select(root, args)
    log = getattr(args, "log", None)
    if log and any(log.resolve().is_relative_to(Path(copy.address)) for copy in copies):
        raise CatalogueScopeError("Journal dans un dépôt source.")
    for folder in ("catalog", "catalog/assets", "catalog/sheets", "generated", "generated/reports"):
        Catalogue._regular_path(root / folder)


def run(root, args):
    root = root.resolve()
    with directory_lock(root / "catalog"):
        target = Importer(root, None, args.dry_run)
        if args.command == "import-sheet":
            return _import(target, args)
        return _extract_command(target, args)


def _import(target, args):
    exact = False
    entries, table_digest = _read_table(args.decoupe) if args.decoupe else ([], None)
    source = args.file
    format_id = formats.extension(source.name)
    if format_id in {"ase", "aseprite"}:
        with tempfile.TemporaryDirectory(prefix="assetctl-aseprite-") as tmp:
            png, metadata = Path(tmp) / "sheet.png", Path(tmp) / "sheet.json"
            aseprite.export(source, png, metadata)
            raw = _bounded_read(png)
            format_id = "png"
            if not args.decoupe:
                atlas = formats.inspect("sheet.json", metadata.read_bytes())
                if not atlas or atlas.family["type"] != "atlas":
                    raise OSError("JSON hash Aseprite illisible.")
                entries = [{"id": item["name"], "boite": [item[k] for k in "whxy"]}
                           for item in atlas.family["frames"]]
                exact = True
    elif format_id in formats.RASTER:
        raw = _bounded_read(source)
    else:
        raise InvalidJSON("Format de planche matricielle ou Aseprite attendu.")
    image = _image(raw)
    digest = hashlib.sha256(raw).hexdigest()
    evidence = f"{source.name} · SHA-256 {digest}"
    sheet = sheet_record(target, digest, source.stem or digest[:16], formats.dimensions(*image.size), evidence)
    relative = sheet["files"]["registry"] or f"sources/original-sheets/{sheet['id']}.{format_id}"
    path = _destination(target.root, relative, "sources")
    sheet["files"]["registry"] = relative
    if args.decoupe:
        evidence = _table_evidence(args.decoupe, table_digest, digest)
    results, outputs = _extract(target, sheet, image, entries, evidence, exact=exact)
    _save(target, {path: raw, **outputs})
    return ExitCode.OK, {"ok": True, "sheetId": sheet["id"], "assets": results}


def _table_evidence(path, table_digest, digest):
    return f"{path.name} · SHA-256 {table_digest} · planche {digest}"


def _extract_command(target, args):
    sheet = target.sheets.get(args.sheet_id)
    if sheet is None:
        return ExitCode.CHECK_FAILED, {"ok": False, "error": "not-found", "id": args.sheet_id}
    if args.candidates:
        image = _image(_blob(target.root, sheet, args))
        return ExitCode.OK, {"ok": True, "sheetId": sheet["id"], "candidates": regions.components(image)}
    if args.regions is None:
        results, outputs = _extract_registered(target, sheet, args)
    else:
        image = _image(_blob(target.root, sheet, args))
        entries, table_digest = _read_table(args.regions)
        evidence = _table_evidence(args.regions, table_digest, sheet["sha256"])
        results, outputs = _extract(target, sheet, image, entries, evidence, args.out)
    _save(target, outputs)
    return ExitCode.OK, {"ok": True, "sheetId": sheet["id"], "assets": results}
