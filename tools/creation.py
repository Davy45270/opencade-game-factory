"""Création justifiée et variantes reproductibles."""

import re
from datetime import datetime, timedelta, timezone
from itertools import chain

from PIL import Image, ImageOps

from tools import asset_versions
from tools.cli import UsageError
from tools.core.catalog import Catalogue, CatalogueScopeError, InvalidJSON, parse_json, read_json, write_json
from tools.core.exit_codes import ExitCode
from tools.core.ids import IdRegistry
from tools.core.schemas import schemas
from tools.discovery import formats
from tools.discovery.importer import _asset, _trace
from tools.discovery.repos import Git, GitError, OID
from tools.discovery.scan import directory_lock
from tools.extract.commands import _bounded_read, _image
from tools.extract.regions import canonical_png, crop, in_image
from tools.index.search import catalogue_fingerprint, committed_fingerprint
from tools.publish.delivery import Delivery, check_destination, put, scoped_path, sha
from tools.publish.licenses import DERIVABLE

RECEIPT_AGE = timedelta(days=7)


def matching_snapshot(root, receipt, fingerprint):
    if receipt["catalogFingerprint"] == fingerprint:
        return True
    commit = receipt.get("registryCommit", "")
    if not OID.fullmatch(commit):
        return False
    git = Git(root)
    try:
        head = git.run("rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        if git.run("merge-base", head, commit, ok=(0, 1)).decode().strip() != head:
            return False
        return fingerprint == committed_fingerprint(git, head) and (
            receipt["catalogFingerprint"] == committed_fingerprint(git, commit)
        )
    except GitError:
        return False


def receipt_for(args, now):
    if not args.receipt:
        raise CatalogueScopeError("Un reçu de recherche récent est requis.")
    try:
        receipt = read_json(scoped_path(args.receipt))
        if not schemas().validator("search-receipt").is_valid(receipt) or "results" not in receipt:
            raise ValueError
        searched = datetime.fromisoformat(receipt["searchedAt"])
        if searched.tzinfo is None or not timedelta(0) <= now - searched <= RECEIPT_AGE:
            raise ValueError
    except (OSError, ValueError, KeyError) as exc:
        raise CatalogueScopeError("Reçu de recherche invalide ou expiré.") from exc

    rejected = {}
    for rejection in args.reject:
        candidate, _, reason = rejection.partition(":")
        if candidate in rejected or not reason.strip():
            raise CatalogueScopeError("Chaque rejet doit donner un ID unique et une raison.")
        rejected[candidate] = reason.strip()
    if set(receipt["results"]) != rejected.keys():
        raise CatalogueScopeError("Chaque candidat du reçu exige un rejet motivé.")
    rows = [{"assetId": candidate, "reason": rejected[candidate]} for candidate in receipt["results"]]
    return {"searchReceipt": {**receipt, "rejectedCandidates": rows}, "rejectedCandidates": rows}


def save_asset(root, ids, asset, raw, dry_run, parent=None):
    catalogue = Catalogue(root)
    directory = catalogue._regular_path(catalogue.path / "assets")
    path = catalogue._regular_path(directory / f"{asset['id']}.json")
    parent_path = catalogue._regular_path(directory / f"{parent['id']}.json") if parent else None
    binary = scoped_path(root / asset["files"]["registry"])
    ids_path = catalogue._regular_path(catalogue.path / "ids.json")
    for record in chain([asset], [parent] if parent else []):
        error = next(schemas().validator("asset").iter_errors(record), None)
        if error:
            raise InvalidJSON(f"Asset invalide ({record['id']}) : {error.message}")
    check_destination(binary, raw)
    if not dry_run:
        binary_existed = binary.exists()
        previous_parent = catalogue.read(parent_path) if parent_path is not None else None
        parent_written = False
        put(binary, raw)
        try:
            write_json(path, asset)
            if parent_path is not None:
                write_json(parent_path, parent)
                parent_written = True
            write_json(ids_path, ids.entries)
        except OSError:
            path.unlink(missing_ok=True)
            if not binary_existed:
                binary.unlink(missing_ok=True)
            if parent_written:
                write_json(parent_path, previous_parent)
            raise
    return ExitCode.OK, {"ok": True, "id": asset["id"], "asset": asset}


def register(root, args):
    if not args.name.strip() or (not re.fullmatch(r"[a-z][a-z0-9]*", args.category) or args.category == "sheet"):
        raise UsageError("Nom non vide et catégorie ASCII minuscules attendus.")
    with directory_lock(root / "catalog"):
        now = datetime.now(timezone.utc)
        creation = receipt_for(args, now)
        source = scoped_path(args.file)
        raw = _bounded_read(source)
        try:
            measured = formats.inspect(source.name, raw)
        except formats.Unreadable as exc:
            raise InvalidJSON("Fichier incompatible ou illisible.") from exc
        if measured is None or measured.family["type"] == "code-generated":
            raise InvalidJSON("Fichier incompatible avec register.")
        digest = sha(raw)
        catalogue = Catalogue(root)
        ids = IdRegistry(catalogue.read(catalogue.path / "ids.json"))
        identity = f"file:sha256:{digest}"
        asset_id = ids.allouer(identity, args.category, args.name)
        path = catalogue._regular_path(catalogue.path / "assets" / f"{asset_id}.json")
        if path.exists():
            existing = catalogue.read(path)
            if (existing.get("creation") == creation and existing["name"] == args.name
                    and existing["category"] == args.category and existing["sha256"] == digest):
                delivery = Delivery(root, args)
                verified = delivery.asset(asset_id)
                delivery.bytes(verified)
                return ExitCode.OK, {"ok": True, "id": asset_id, "asset": verified}
            raise CatalogueScopeError(f"Contenu déjà enregistré sous {asset_id}.")
        if not matching_snapshot(root, creation["searchReceipt"], catalogue_fingerprint(root)):
            raise CatalogueScopeError("Le reçu vise un état différent du catalogue.")
        kind = formats.extension(source.name)
        time = now.isoformat()
        evidence = f"Import local de {source.name}, SHA-256 {digest}"
        asset = _asset(asset_id, args.name, evidence, time, time, None, digest, measured, measured.family, kind)
        asset["creation"] = creation
        asset["provenance"]["type"] = "unknown"
        asset["category"] = args.category
        asset["inference"]["category"] = _trace("Catégorie déclarée avec register.")
        folder = "sprites" if measured.image is not None else "sources"
        asset["files"]["registry"] = f"{folder}/{asset_id}.{kind}"
        asset.pop("thumbnail", None)
        return save_asset(root, ids, asset, raw, args.dry_run)


def transform(image, recipe):
    if not isinstance(recipe, dict) or not recipe or set(recipe) - {"crop", "mirror", "resize", "tint"}:
        raise InvalidJSON("Recette attendue avec crop, mirror, resize ou tint.")
    if "crop" in recipe:
        box = recipe["crop"]
        if (not isinstance(box, dict) or set(box) != {"x", "y", "w", "h"}
                or any(type(value) is not int for value in box.values()) or not in_image(box, image)
                or min(box["x"], box["y"]) < 0
                or min(box["w"], box["h"]) <= 0):
            raise InvalidJSON("crop exige un cadre {x,y,w,h} dans l’image.")
        image = crop(image, box)
    mirror = recipe.get("mirror", False)
    if mirror is True or mirror == "horizontal":
        image = ImageOps.mirror(image)
    elif mirror == "vertical":
        image = ImageOps.flip(image)
    elif mirror is not False:
        raise InvalidJSON("mirror exige un booléen, horizontal ou vertical.")
    if "resize" in recipe:
        size = recipe["resize"]
        if (not isinstance(size, list) or len(size) != 2
                or any(type(n) is not int or not 1 <= n <= 8192 for n in size)):
            raise InvalidJSON("resize exige [largeur, hauteur] entre 1 et 8192.")
        image = image.resize(tuple(size), Image.Resampling.LANCZOS)
    if "tint" in recipe:
        color = recipe["tint"]
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise InvalidJSON("tint exige une couleur #RRGGBB.")
        alpha = image.getchannel("A")
        image = ImageOps.colorize(ImageOps.grayscale(image), "#000000", color)
        image.putalpha(alpha)
    return image


def derive(root, args):
    with directory_lock(root / "catalog"):
        delivery = Delivery(root, args)
        parent = delivery.asset(args.id)
        recipe_data = _bounded_read(scoped_path(args.recipe))
        recipe = parse_json(recipe_data)
        recipe_hash = sha(recipe_data)
        parent_version = asset_versions.version_number(parent)
        parent_digest = parent["sha256"].lower()
        input_hash = sha(f"{parent_version}:{parent_digest}:{recipe_hash}".encode("ascii"))
        original_identity = f"derived:{args.id}:{recipe_hash}"
        revision_identity = f"derived:{args.id}:{input_hash}"
        identity = original_identity if parent_version == 1 else revision_identity
        catalogue = Catalogue(root)
        ids = IdRegistry(catalogue.read(catalogue.path / "ids.json"))
        parent_revision = {"parentId": args.id, "parentVersion": parent_version, "parentSha256": parent_digest}
        name = f"{parent['name']} variante"
        def render():
            parent_raw = delivery.bytes(delivery.revision(parent, parent_version))
            return canonical_png(transform(_image(parent_raw), recipe))

        asset_id = ids.allouer(identity, "sprite", name)
        existing = delivery.asset(asset_id) if asset_id in delivery.assets else None
        raw = None
        if existing and identity == original_identity and "parentId" not in existing["provenance"]:
            if asset_id not in parent["variants"] or existing["provenance"].get("derivedFrom") != args.id:
                return ExitCode.VERSION_CONFLICT, {"ok": False, "error": "derived-record-conflict"}
            raw = render()
            if sha(raw) == existing["sha256"].lower():
                delivery.bytes(existing)
                existing["provenance"].update(parent_revision)
                if not args.dry_run:
                    record = catalogue._regular_path(catalogue.path / "assets" / f"{asset_id}.json")
                    write_json(record, existing)
                return ExitCode.OK, {"ok": True, "id": asset_id, "asset": existing}
            asset_id = ids.allouer(revision_identity, "sprite", name)
            existing = delivery.asset(asset_id) if asset_id in delivery.assets else None
        if existing:
            if (asset_id not in parent["variants"] or existing["provenance"].get("derivedFrom") != args.id
                    or any(existing["provenance"].get(key) != value for key, value in parent_revision.items())):
                return ExitCode.VERSION_CONFLICT, {"ok": False, "error": "derived-record-conflict"}
            delivery.bytes(existing)
            return ExitCode.OK, {"ok": True, "id": asset_id, "asset": existing}
        if raw is None:
            raw = render()
        digest = sha(raw)
        measured = formats.inspect("sprite.png", raw)
        time = datetime.now(timezone.utc).isoformat()
        evidence = f"Recette SHA-256 {recipe_hash}, parent {args.id}"
        asset = _asset(asset_id, name, evidence, time, time, None, digest, measured, measured.family, "png")
        asset.pop("creation")
        asset.pop("thumbnail", None)
        asset["files"]["registry"] = f"sprites/{asset_id}.png"
        asset["provenance"] = {"type": "derived", "derivedFrom": args.id,
                               **parent_revision,
                               "author": parent["provenance"]["author"], "evidence": [evidence]}
        if parent["license"] in DERIVABLE and parent.get("licenseEvidence"):
            asset["license"] = parent["license"]
            asset["licenseEvidence"] = parent["licenseEvidence"]
            if parent.get("publicExport") == "forbidden" or parent["sha256"].lower() in delivery.sheet_hashes:
                asset["publicExport"] = "forbidden"
        updated_parent = {**parent, "variants": [*parent["variants"], asset_id]}
        return save_asset(root, ids, asset, raw, args.dry_run, updated_parent)
