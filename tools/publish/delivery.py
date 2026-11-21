"""Résolution des binaires, contrôle des droits et livraison explicite."""

import hashlib
import os
import re
import tempfile
from contextlib import nullcontext
from functools import cached_property
from pathlib import Path

from tools import asset_versions
from tools.cli import UsageError
from tools.core.catalog import Catalogue, CatalogueScopeError, InvalidJSON, json_text, parse_json, read_json, write_json
from tools.core.exit_codes import ExitCode
from tools.core.schemas import schemas
from tools.discovery.importer import MAX_BLOB, read_assets
from tools.discovery.repos import Git, GitError, _copies
from tools.discovery.scan import cache_path, directory_lock
from tools.extract.commands import _bounded_read, _image
from tools.extract.regions import canonical_png, crop, in_image
from tools.publish.licenses import PRIVATE_LICENSES, public_allowed


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
    if any(part.lower() == ".git" for part in path.parts) or any(path.is_relative_to(root / tree) for tree in ("catalog", "published")):
        raise CatalogueScopeError("Destination interdite dans les métadonnées Git, le catalogue ou le magasin publié.")
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


def granted_licenses(root, checkout):
    """Private licenses this checkout may publish: all of them when EVERY source matching it is a game of David
    (role « game » in catalog/sources.json, GAME_GRANT, HL-538 2026-11-21) ; none for any other destination."""
    if checkout is None:
        return frozenset()
    catalogue = Catalogue(root)
    value = read_json(catalogue._regular_path(catalogue.path / "sources.json"))
    if not isinstance(value, dict):
        return frozenset()
    names = set()
    for copy in copies_for(root).values():
        if copy.provider == "local" and Path(copy.address) == checkout:
            names.add(copy.name)
    if not names:
        try:
            origin = Git(checkout).run("config", "--local", "--no-includes", "--get",
                                       "remote.origin.url").decode().strip()
        except (GitError, UnicodeError):
            return frozenset()
        names = {copy.name for copy in copies_for(root).values() if copy.provider != "local"
                 and origin.removesuffix(".git") == copy.url.removesuffix(".git")}
    roles = [source.get("role") for source in value.get("sources", ()) if source.get("name") in names]
    return PRIVATE_LICENSES if roles and all(role == "game" for role in roles) else frozenset()


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
        self.assets = read_assets(root)
        self.copies = None
        self.git = Git(root)

    @cached_property
    def sheets(self):
        catalogue = Catalogue(self.root)
        return {path.stem: catalogue.read(path) for path in catalogue.documents("sheets")}

    @cached_property
    def sheet_hashes(self):
        return {record["sha256"].lower() for record in self.sheets.values()}

    def asset(self, asset_id, *, public=False, granted=frozenset()):
        if asset_id not in self.assets:
            raise InvalidJSON(f"Asset introuvable : {asset_id}")
        asset = self.assets[asset_id]
        if public and isinstance(asset, dict) and isinstance(asset.get("sha256"), str):
            self.require_public({**asset, "id": asset_id}, granted=granted)
        if (not schemas().validator("asset").is_valid(asset) or asset["id"] != asset_id
                or next(asset_versions.problems(asset), None)):
            raise InvalidJSON(f"Fiche d’asset invalide : {asset_id}")
        return asset

    def revision(self, asset, number):
        if not 1 <= number <= len(asset_versions.history(asset)):
            raise InvalidJSON(f"Version inconnue pour {asset['id']} : {number}.")
        entry = asset_versions.history(asset)[number - 1]
        current = number == asset_versions.version_number(asset)
        publication = entry.get("publication", {})
        files = {
            **(asset["files"] if current else {}),
            "registry": publication.get("registry") or (asset["files"].get("registry") if current else None),
            "locations": [loc for loc in asset["files"]["locations"] if loc.get("assetVersion", 1) == number],
        }
        if frames := entry.get("atlasFrames"):
            files.update(atlasFrames=frames, sha256Method="canonical-crop-png")
        rights = asset if current else publication
        return {**asset, "version": number, "files": files, "sha256": entry["sha256"], "format": entry.get("format", asset["format"]),
                "sourceSheetId": asset["sourceSheetId"] if current else None,
                "sourceRegion": asset["sourceRegion"] if current else None,
                "license": rights.get("license"), "licenseEvidence": rights.get("licenseEvidence"),
                "publicExport": rights.get("publicExport"), "provenance": rights.get("provenance", {})}

    def require_public(self, asset, *, commit=None, sheet_hashes=None, granted=frozenset()):
        def find_parent(parent_id):
            try:
                if commit is not None:
                    return revision_at(self.git, commit, parent_id)
                return self.asset(parent_id)
            except (GitError, InvalidJSON):
                return None

        hashes = self.sheet_hashes if sheet_hashes is None else sheet_hashes
        if not public_allowed(asset, hashes, find_parent, granted):
            raise CatalogueScopeError(f"Export public interdit pour {asset['id']}.")

    def registry_file(self, record):
        if local := record["files"].get("registry"):
            path = scoped_path(self.root / local)
            if not path.is_relative_to(self.root) or not path.relative_to(self.root).parts:
                raise CatalogueScopeError("Fichier hors du registre.")
            if any(part.lower() == ".git" for part in path.parts):
                raise CatalogueScopeError("Objet Git interdit comme fichier du registre.")
            if path.is_file():
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
        entry = asset_versions.history(asset)[asset_versions.version_number(asset) - 1]
        stored = entry.get("publication", {}).get("registry")
        if stored:
            asset = {**asset, "files": {**asset["files"], "registry": stored}}
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
    granted = granted_licenses(root, worktree(destination)) if public else frozenset()
    requested = getattr(args, "version", None)
    asset = delivery.asset(args.id, public=public and requested is None, granted=granted)
    if requested is not None:
        if requested < 1:
            raise UsageError("--version doit être un entier positif.")
        if requested > len(asset_versions.history(asset)):
            raise OSError(f"Version indisponible pour {args.id} : {requested}.")
        asset = delivery.revision(asset, requested)
        if destination.is_dir() or not destination.suffix:
            destination = scoped_path(destination / (asset["id"] + extension(asset)))
    else:
        asset = delivery.revision(asset, asset_versions.version_number(asset))
    raw = delivery.bytes(asset)
    if public and requested is not None:
        delivery.require_public(asset, granted=granted)
    check_destination(destination, raw)
    if not args.dry_run:
        put(destination, raw)
    return ExitCode.OK, {"ok": True, "id": args.id, "path": str(destination), "sha256": asset["sha256"]}


def third_party(assets):
    """Manifeste de provenance et THIRD_PARTY_ASSETS.md d'un export public (EXT-001 § 6)."""
    rows, lines = [], ["# Ressources tierces", ""]
    for asset in sorted(assets, key=lambda row: row["id"]):
        origin = asset["provenance"]
        external = origin.get("external")
        row = {"id": asset["id"], "sha256": asset["sha256"], "license": asset["license"],
               "author": origin.get("author", "unknown"), "provenanceType": origin["type"]}
        if external:
            row.update(provider=external["provider"], pack=external["externalPackId"],
                       sourceVersion=external["sourceVersion"], sourceUrl=external["sourceUrl"],
                       licenseEvidence=external["license"]["evidence"], licenseText=external["license"].get("textPath"),
                       pathInArchive=external["pathInArchive"], restrictions=external["restrictions"])
            lines.append(f"- **{asset['name']}** (`{asset['id']}`) — {external['provider']} / {external['externalPackId']} "
                         f"{external['sourceVersion']}, auteur {row['author']}, licence {asset['license']}, "
                         f"source {external['sourceUrl']}")
        elif asset["license"].startswith("CC-BY"):
            lines.append(f"- **{asset['name']}** (`{asset['id']}`) — auteur {row['author']}, licence {asset['license']}")
        rows.append(row)
    if len(lines) == 2:
        lines.append("Aucune ressource tierce ni attribution requise dans cet export.")
    return {"schemaVersion": "1.0", "assets": rows}, "\n".join(lines) + "\n"


def publish(root, args):
    with (nullcontext() if args.dry_run else directory_lock(root / "catalog")):
        return _publish(root, args)


def _publish(root, args):
    delivery = Delivery(root, args)
    assets = [delivery.asset(asset_id, public=args.target == "public") for asset_id in dict.fromkeys(args.ids)]
    directory = output_path(root, args.dest, kind="publish")
    paths = []
    rows = []
    stored = {}
    store = scoped_path(root / "published" / "sha256")
    if store.is_dir():
        for path in sorted(store.iterdir()):
            if re.fullmatch(r"[a-f0-9]{64}\.[A-Za-z0-9][A-Za-z0-9_-]{0,31}", path.name):
                digest = path.stem
                if digest in stored:
                    raise InvalidJSON(f"Plusieurs fichiers publiés pour {digest}.")
                stored[digest] = path
    records = []
    catalogue = Catalogue(root)
    for asset in assets:
        path = scoped_path(directory / (asset["id"] + extension(asset)))
        revision = delivery.revision(asset, asset_versions.version_number(asset))
        raw = delivery.bytes(revision)
        digest = sha(raw)
        kept = stored.setdefault(digest, scoped_path(store / (digest + extension(asset))))
        paths.append((path, raw))
        asset_versions.initialize(asset)
        asset["status"] = "published"
        entry = asset["versions"][asset_versions.version_number(asset) - 1]
        entry.setdefault("format", asset["format"])
        published_path = kept.relative_to(delivery.root).as_posix()
        proof = asset_versions.publication_proof(asset, published_path)
        if previous := entry.get("publication"):
            if {**previous, "registry": previous.get("registry", published_path)} != proof:
                raise CatalogueScopeError(f"Preuve de publication immuable pour {asset['id']}.")
        entry["publication"] = proof
        record_path = catalogue._regular_path(catalogue.path / "assets" / (asset["id"] + ".json"))
        records.append((record_path, asset, kept, raw))
        author = asset["provenance"]["author"]
        rows.append({"id": asset["id"], "sha256": asset["sha256"], "path": path.name,
                     "license": asset["license"], "licenseEvidence": asset.get("licenseEvidence"),
                     **({"attribution": {"title": asset["name"], "author": author,
                                         "license": "https://creativecommons.org/licenses/by/4.0/",
                                         "derivedFrom": asset["provenance"].get("derivedFrom")}}
                        if asset["license"] == "CC-BY-4.0" else {})})
    manifest = {"target": args.target, "assets": rows}
    paths.append((scoped_path(directory / "manifest.json"), json_text(manifest).encode()))
    if args.target == "public":
        # EXT-001 § 6 (EXT-T10) : crédits et manifeste de provenance à CHAQUE export public.
        provenance, credits = third_party(assets)
        paths.append((scoped_path(directory / "provenance.json"), json_text(provenance).encode()))
        paths.append((scoped_path(directory / "THIRD_PARTY_ASSETS.md"), credits.encode()))
    for record_path, _, kept, raw in records:
        check_destination(kept, raw)
        if not record_path.is_file():
            raise OSError(f"Fiche indisponible pour la publication : {record_path.name}.")
    for path, raw in paths:
        check_destination(path, raw)
    if not args.dry_run:
        for path, raw in paths:
            put(path, raw)
        for path, asset, kept, raw in records:
            put(kept, raw)
            if read_json(path) != asset:
                write_json(path, asset)
    return ExitCode.OK, {"ok": True, **manifest}


def read_lock(path):
    lock = read_json(scoped_path(path))
    error = next(schemas().validator("lock").iter_errors(lock), None)
    if error:
        raise InvalidJSON(f"Lock invalide : {error.message}")
    return lock


def contains_version(asset, row):
    return any(str(entry["version"]) == row["assetVersion"] and entry["sha256"].lower() == row["sha256"].lower()
               for entry in asset_versions.history(asset))


def revision_at(git, commit, asset_id):
    path = f"catalog/assets/{asset_id}.json"
    # A Git symlink is a blob too. Only accept a regular tracked fiche.
    tree = git.run("ls-tree", commit, "--", f":(literal){path}").split()
    if not tree or tree[0] not in {b"100644", b"100755"}:
        return None
    oid = tree[2].decode("ascii")
    if int(git.run("cat-file", "-s", oid)) > MAX_BLOB:
        return None
    record = parse_json(git.run("cat-file", "blob", oid))
    if (schemas().validator("asset").is_valid(record) and record["id"] == asset_id
            and not next(asset_versions.problems(record), None)):
        return record
    return None


def sheet_hashes_at(git, commit):
    hashes = set()
    validator = schemas().validator("sheet")
    with git.batch(None) as batch:
        for blob in git.tree(None, commit, sizes=True, paths=("catalog/sheets/",)):
            if not blob.path.endswith(".json"):
                continue
            path = Path(blob.path)
            if path.parent.as_posix() != "catalog/sheets":
                continue
            if blob.symlink or blob.size > MAX_BLOB:
                raise InvalidJSON(f"Planche invalide au commit attesté : {path}.")
            sheet = parse_json(batch.read(blob, MAX_BLOB))
            if not validator.is_valid(sheet) or sheet["id"] != path.stem:
                raise InvalidJSON(f"Planche invalide au commit attesté : {path}.")
            hashes.add(sheet["sha256"].lower())
    return hashes


def valid_locked_file(checkout, row):
    try:
        path = scoped_path(checkout / row["path"])
        return path.is_file() and sha(_bounded_read(path)) == row["sha256"].lower()
    except (OSError, CatalogueScopeError):
        return False


def check_lock(root, args):
    delivery = Delivery(root, args)
    path = scoped_path(root / args.file)
    lock = read_lock(path)
    errors = []
    warnings = []
    try:
        commit = delivery.git.run("rev-parse", "--verify", "--end-of-options",
                                  lock["registryCommit"] + "^{commit}").decode().strip()
        if commit != lock["registryCommit"].lower():
            raise GitError("registryCommit ne désigne pas directement un commit.")
    except GitError:
        return ExitCode.CHECK_FAILED, {"ok": False, "errors": [{"error": "unknown-registry-commit"}], "warnings": []}

    committed = {}
    locked = []
    for row in lock["assets"]:
        asset_id = row["assetId"]
        asset = delivery.assets.get(asset_id)
        try:
            if asset_id not in committed:
                committed[asset_id] = revision_at(delivery.git, commit, asset_id)
            record = committed[asset_id]
        except (OSError, InvalidJSON):
            record = None
        if not record or not contains_version(record, row):
            error = "version-absent-at-registry-commit"
        elif asset is None or not contains_version(delivery.asset(asset_id), row):
            error = "version-or-digest-mismatch"
        elif not valid_locked_file(path.parent, row):
            error = "locked-file-digest-mismatch"
        else:
            locked.append(delivery.revision(record, int(row["assetVersion"])))
            if row["assetVersion"] != asset_version(asset):
                warnings.append({"id": asset_id, "path": row["path"], "warning": "non-current-version",
                                 "assetVersion": row["assetVersion"], "currentVersion": asset_version(asset)})
            continue
        errors.append({"id": asset_id, "path": row["path"], "error": error})
    if args.public and not errors and locked:
        hashes = sheet_hashes_at(delivery.git, commit)
        granted = granted_licenses(root, worktree(path.parent))
        for revision in locked:
            delivery.require_public(revision, commit=commit, sheet_hashes=hashes, granted=granted)
    return (ExitCode.CHECK_FAILED if errors else ExitCode.OK), {"ok": not errors, "errors": errors, "warnings": warnings}


COMMIT_CATALOGUE = "Avant usage add, commite le catalogue avec les versions du lock."


def usage_head(git):
    try:
        head = git.run("rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        dirty = git.run("status", "--porcelain=v1", "--untracked-files=all", "--", "catalog/")
    except GitError:
        raise CatalogueScopeError(COMMIT_CATALOGUE) from None
    if dirty:
        raise CatalogueScopeError(COMMIT_CATALOGUE)
    return head


def require_committed_versions(git, head, rows):
    committed = {}
    for row in rows:
        asset_id = row["assetId"]
        try:
            if asset_id not in committed:
                committed[asset_id] = revision_at(git, head, asset_id)
        except (OSError, InvalidJSON):
            committed[asset_id] = None
        if not committed[asset_id] or not contains_version(committed[asset_id], row):
            raise CatalogueScopeError(COMMIT_CATALOGUE)
    return committed


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
    head = usage_head(delivery.git)
    if args.id not in delivery.assets:
        raise CatalogueScopeError(COMMIT_CATALOGUE)
    public = not (args.private_target or private_destination(root, checkout))
    asset = delivery.asset(args.id)
    relative = args.path or Path("assets") / (asset["id"] + extension(asset))
    destination = output_path(root, checkout / relative, kind="usage")
    lock_path = output_path(root, checkout / "assets.lock.json", kind="usage")
    if relative.is_absolute() or ".." in relative.parts or destination == lock_path or worktree(destination) != checkout:
        raise CatalogueScopeError("--path doit être un chemin de fichier relatif au jeu.")
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
        committed = require_committed_versions(delivery.git, head, lock["assets"])
        lock["registryCommit"] = head
        if not schemas().validator("lock").is_valid(lock):
            raise InvalidJSON("La nouvelle entrée ne respecte pas le schéma de lock.")
        if any(not valid_locked_file(checkout, row) for row in other_rows if row["path"] != entry["path"]):
            raise InvalidJSON("Un fichier de jeu diffère de la version verrouillée ou est indisponible.")
        if public:
            hashes = sheet_hashes_at(delivery.git, head)
            granted = granted_licenses(root, checkout)
            for row in lock["assets"]:
                revision = delivery.revision(committed[row["assetId"]], int(row["assetVersion"]))
                delivery.require_public(revision, commit=head, sheet_hashes=hashes, granted=granted)
        raw = delivery.bytes(asset)
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
