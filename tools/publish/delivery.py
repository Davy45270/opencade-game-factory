"""Résolution des binaires, contrôle des droits et livraison explicite."""

import hashlib
import os
import re
import tempfile
from contextlib import nullcontext
from pathlib import Path

from tools import asset_versions
from tools.cli import UsageError
from tools.core.catalog import Catalogue, CatalogueScopeError, InvalidJSON, json_text, read_json, write_json
from tools.core.exit_codes import ExitCode
from tools.core.schemas import schemas
from tools.discovery.importer import MAX_BLOB, read_assets
from tools.discovery.repos import Git, GitError, _copies
from tools.discovery.scan import cache_path, directory_lock
from tools.extract.commands import _bounded_read, _image
from tools.extract.regions import canonical_png, crop, in_image
from tools.publish.licenses import public_allowed


def scoped_path(path):
    path = Path(os.path.abspath(path))
    for entry in (*reversed(path.parents), path):
        Catalogue._regular_path(entry)
    return path


def copies_for(root):
    catalogue = Catalogue(root)
    return _copies(catalogue._regular_path(catalogue.path / "sources.json"))


def worktree(path):
    for entry in (path, *path.parents):
        marker = entry / ".git"
        if marker.is_symlink() or marker.is_file() or (marker / "HEAD").is_file():
            return entry
    return None


def output_path(root, path, *, kind):
    root = root.resolve()
    path = scoped_path(root / path)
    if any(part.lower() == ".git" for part in path.parts) or path.is_relative_to(root / "catalog"):
        raise CatalogueScopeError("Destination interdite dans les métadonnées Git ou le catalogue.")
    if kind not in {"materialize", "usage"}:
        checkout = worktree(path)
        if checkout and checkout != root:
            raise CatalogueScopeError("Destination située dans un autre dépôt Git.")
        if any(path.is_relative_to(Path(copy.address)) for copy in copies_for(root).values()
               if copy.provider == "local"):
            raise CatalogueScopeError("Destination située dans un dépôt source.")
    return path


def private_destination(root, checkout):
    if checkout is None:
        return False
    allowed = copies_for(root).values()
    copies = [copy for copy in allowed if copy.provider == "local" and Path(copy.address) == checkout]
    if not copies:
        try:
            origin = Git(checkout).run("config", "--local", "--no-includes", "--get",
                                       "remote.origin.url").decode().strip()
        except (GitError, UnicodeError):
            return False
        copies = [copy for copy in allowed if copy.provider != "local" and
                  origin.removesuffix(".git") == copy.url.removesuffix(".git")]
    return bool(copies) and all(copy.visibility == "private" for copy in copies)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def staged_bytes(path, raw, *, replace=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(raw)
            stream.close()
            if replace:
                temporary.replace(path)
            else:
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    check_destination(path, raw)
        finally:
            temporary.unlink(missing_ok=True)


def check_destination(path, raw):
    Catalogue._regular_path(path)
    if path.exists() and (not path.is_file() or path.stat().st_size != len(raw) or path.read_bytes() != raw):
        raise CatalogueScopeError(f"Une sortie différente existe déjà pour {path.name}.")


def put(path, raw):
    check_destination(path, raw)
    if not path.exists():
        staged_bytes(path, raw)


class Delivery:
    def __init__(self, root, args):
        self.root = root.resolve()
        self.cache = scoped_path(cache_path(args))
        catalogue = Catalogue(root)
        self.assets = read_assets(root)
        self.sheets = {path.stem: catalogue.read(path) for path in catalogue.documents("sheets")}
        self.sheet_hashes = {record["sha256"].lower() for record in self.sheets.values()}
        self.copies = None
        self.git = Git(root)

    def asset(self, asset_id, *, public=False):
        if asset_id not in self.assets:
            raise InvalidJSON(f"Asset introuvable : {asset_id}")
        asset = self.assets[asset_id]
        if public:
            self.require_public(asset)
        if not schemas().validator("asset").is_valid(asset):
            raise InvalidJSON(f"Fiche d’asset invalide : {asset_id}")
        return asset

    def require_public(self, asset):
        if not public_allowed(asset, self.sheet_hashes):
            raise CatalogueScopeError(f"Export public interdit pour {asset['id']}.")

    def registry_file(self, record):
        if local := record["files"].get("registry"):
            path = scoped_path(self.root / local)
            if not path.is_relative_to(self.root) or not path.relative_to(self.root).parts:
                raise CatalogueScopeError("Fichier hors du registre.")
            if any(part.lower() == ".git" for part in path.parts):
                raise CatalogueScopeError("Objet Git interdit comme fichier du registre.")
            yield _bounded_read(path)

    def mirror_files(self, record):
        if self.copies is None:
            self.copies = copies_for(self.root)
        for loc in record["files"]["locations"]:
            for copy in self.copies.values():
                if copy.name != loc["repo"] or loc.get("provider") not in (None, copy.provider):
                    continue
                mirror = scoped_path(self.cache / copy.provider / f"{copy.name}.git")
                if not mirror.is_dir():
                    continue
                try:
                    self.git.check_mirror(copy, mirror)
                    path = loc["path"]
                    commit = loc["commit"]
                    entry = self.git.run("ls-tree", "-z", commit, "--", f":(literal){path}", mirror=mirror)
                    header, _, name = entry.rstrip(b"\0").partition(b"\t")
                    fields = header.split()
                    if len(fields) != 3 or fields[0] not in {b"100644", b"100755"} or name != path.encode():
                        continue
                    oid = fields[-1].decode("ascii")
                    size = int(self.git.run("cat-file", "-s", oid, mirror=mirror))
                    if size <= MAX_BLOB:
                        yield self.git.run("cat-file", "blob", oid, mirror=mirror)
                except GitError:
                    continue

    def verified(self, record, sources):
        for raw in sources:
            if sha(raw) == record["sha256"].lower():
                return raw
        raise OSError(f"Binaire vérifié indisponible pour {record['id']}.")

    def crops(self, asset):
        jobs = [(frame["atlasSheetId"], frame) for frame in asset["files"].get("atlasFrames", ())]
        if asset["sourceSheetId"] and asset["sourceRegion"]:
            jobs.append((asset["sourceSheetId"], asset["sourceRegion"]))
        for sheet_id, box in jobs:
            sheet = self.sheets.get(sheet_id)
            if not sheet or not schemas().validator("sheet").is_valid(sheet):
                continue
            try:
                raw = self.verified(sheet, self.registry_file(sheet) if sheet["files"].get("registry")
                                    else self.mirror_files(sheet))
                image = _image(raw)
                if in_image(box, image):
                    yield canonical_png(crop(image, box))
            except OSError:
                continue

    def bytes(self, asset):
        if asset["files"].get("registry"):
            sources = self.registry_file(asset)
        elif asset["files"].get("sha256Method") == "canonical-crop-png":
            sources = self.crops(asset)
        else:
            sources = self.mirror_files(asset)
        return self.verified(asset, sources)


def extension(asset):
    kind = asset["format"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", kind):
        raise InvalidJSON("Format inutilisable comme extension de fichier.")
    return "." + kind


def asset_version(asset):
    return str(asset_versions.version_number(asset))


def materialize(root, args):
    delivery = Delivery(root, args)
    destination = output_path(root, args.to, kind="materialize")
    public = not (args.private_target or private_destination(root, worktree(destination)))
    asset = delivery.asset(args.id, public=public)
    raw = delivery.bytes(asset)
    check_destination(destination, raw)
    if not args.dry_run:
        put(destination, raw)
    return ExitCode.OK, {"ok": True, "id": args.id, "path": str(destination), "sha256": asset["sha256"]}


def publish(root, args):
    delivery = Delivery(root, args)
    assets = [delivery.asset(asset_id, public=args.target == "public") for asset_id in dict.fromkeys(args.ids)]
    directory = output_path(root, args.dest, kind="publish")
    paths = []
    rows = []
    for asset in assets:
        path = scoped_path(directory / (asset["id"] + extension(asset)))
        paths.append((path, delivery.bytes(asset)))
        author = asset["provenance"]["author"]
        rows.append({"id": asset["id"], "sha256": asset["sha256"], "path": path.name,
                     "license": asset["license"], "licenseEvidence": asset.get("licenseEvidence"),
                     **({"attribution": {"title": asset["name"], "author": author,
                                         "license": "https://creativecommons.org/licenses/by/4.0/",
                                         "derivedFrom": asset["provenance"].get("derivedFrom")}}
                        if asset["license"] == "CC-BY-4.0" else {})})
    manifest = {"target": args.target, "assets": rows}
    paths.append((scoped_path(directory / "manifest.json"), json_text(manifest).encode()))
    for path, raw in paths:
        check_destination(path, raw)
    if not args.dry_run:
        for path, raw in paths:
            put(path, raw)
    return ExitCode.OK, {"ok": True, **manifest}


def read_lock(path):
    lock = read_json(scoped_path(path))
    error = next(schemas().validator("lock").iter_errors(lock), None)
    if error:
        raise InvalidJSON(f"Lock invalide : {error.message}")
    return lock


def check_lock(root, args):
    delivery = Delivery(root, args)
    lock = read_lock(root / args.file)
    errors = []
    warnings = []
    for row in lock["assets"]:
        asset = delivery.assets.get(row["assetId"])
        if asset is None:
            errors.append({"id": row["assetId"], "error": "unknown-asset"})
            continue
        asset = delivery.asset(row["assetId"], public=args.public)
        if not any(str(int(entry["version"])) == row["assetVersion"] and entry["sha256"].lower() == row["sha256"].lower()
                   for entry in asset_versions.history(asset)):
            errors.append({"id": row["assetId"], "error": "version-or-digest-mismatch"})
        elif row["assetVersion"] != asset_version(asset):
            warnings.append({"id": row["assetId"], "path": row["path"], "warning": "non-current-version",
                             "assetVersion": row["assetVersion"], "currentVersion": asset_version(asset)})
    return (ExitCode.CHECK_FAILED if errors else ExitCode.OK), {"ok": not errors, "errors": errors, "warnings": warnings}


def usage(root, args):
    delivery = Delivery(root, args)
    if args.subject != "add":
        if args.id or args.game or args.scene or args.role or args.repo_dir or args.path or args.private_target:
            raise UsageError("Syntaxe attendue : usage <id> ou usage add <id> avec ses options.")
        asset = delivery.asset(args.subject)
        return ExitCode.OK, {"ok": True, "id": asset["id"], "usages": asset["usages"]}
    if not (args.id and args.repo_dir and all(value and value.strip() for value in (args.game, args.scene, args.role))):
        raise UsageError("usage add exige un ID, --game, --scene, --role et --repo-dir.")
    checkout = scoped_path(root / args.repo_dir)
    if not checkout.is_dir() or worktree(checkout) != checkout or checkout == root.resolve():
        raise CatalogueScopeError("--repo-dir doit désigner la racine du dépôt de jeu.")
    public = not (args.private_target or private_destination(root, checkout))
    asset = delivery.asset(args.id, public=public)
    relative = args.path or Path("assets") / (asset["id"] + extension(asset))
    destination = output_path(root, checkout / relative, kind="usage")
    lock_path = output_path(root, checkout / "assets.lock.json", kind="usage")
    if relative.is_absolute() or ".." in relative.parts or destination == lock_path or worktree(destination) != checkout:
        raise CatalogueScopeError("--path doit être un chemin de fichier relatif au jeu.")
    raw = delivery.bytes(asset)
    head = delivery.git.run("rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    entry = {"assetId": asset["id"], "assetVersion": asset_version(asset), "sha256": asset["sha256"],
             "scene": args.scene, "role": args.role, "path": relative.as_posix()}
    with (nullcontext() if args.dry_run else directory_lock(checkout)):
        lock = read_lock(lock_path) if lock_path.exists() else {
            "schemaVersion": "1.0", "game": args.game, "registryCommit": head, "assets": [],
        }
        if lock["game"] != args.game:
            return ExitCode.VERSION_CONFLICT, {"ok": False, "error": "lock-game-mismatch"}
        rows = lock["assets"]
        slot = ("scene", "role", "path")
        matching = [row for row in rows if all(row[field] == entry[field] for field in slot)]
        other_rows = [row for row in rows if row not in matching]
        if len(matching) > 1 or any(row["path"] == entry["path"] and row["sha256"].lower() != entry["sha256"].lower()
                                    for row in other_rows):
            return ExitCode.VERSION_CONFLICT, {"ok": False, "error": "lock-path-conflict"}
        lock["assets"] = sorted([*other_rows, entry], key=lambda row: (*[row[field] for field in slot], row["assetId"]))
        lock["registryCommit"] = head
        if not schemas().validator("lock").is_valid(lock):
            raise InvalidJSON("La nouvelle entrée ne respecte pas le schéma de lock.")
        previous = None
        if matching and matching[0]["sha256"].lower() != entry["sha256"].lower() and destination.is_file():
            previous = _bounded_read(destination)
            if sha(previous) != matching[0]["sha256"].lower():
                raise CatalogueScopeError("Le fichier de jeu diffère de la version verrouillée.")
        else:
            check_destination(destination, raw)
        if not args.dry_run:
            existed = destination.exists()
            if previous is not None:
                staged_bytes(destination, raw, replace=True)
            else:
                put(destination, raw)
            try:
                if not lock_path.exists() or read_lock(lock_path) != lock:
                    write_json(lock_path, lock)
            except OSError:
                if previous is not None:
                    staged_bytes(destination, previous, replace=True)
                elif not existed:
                    destination.unlink(missing_ok=True)
                raise
    return ExitCode.OK, {"ok": True, "lock": lock, "materialized": entry["path"]}
