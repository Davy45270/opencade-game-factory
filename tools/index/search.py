"""Index FTS5 et reçus de recherche fondés sur le catalogue versionné."""

import hashlib
import re
import sqlite3
import tempfile
import unicodedata
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from tools.asset_versions import initialize, version_number
from tools.cli import UsageError, caller_path
from tools.core.catalog import Catalogue, InvalidJSON, write_json
from tools.core.exit_codes import ExitCode
from tools.discovery.importer import read_assets
from tools.discovery.references import emit as emit_usages
from tools.discovery.repos import Git, GitError
from tools.discovery.scan import directory_lock
from tools.index import dedup
from tools.publish.licenses import emit as emit_licenses

DATABASE = Path("build/registry.sqlite")
FIELDS = ("name", "description", "tags", "category", "originUniverse", "state", "orientation")
FILTERS = {"tag": "tags", "universe": "originUniverse", "orientation": "orientation",
           "state": "state", "license": "license", "used_by": "usages", "category": "category",
           "family": "family"}
OUTPUTS = ("catalog.json", "usage-index.json", "search-index.json", "licenses.json", "licenses.md",
           "reports/removed-in-use.json", "duplicates.json")
INDEX_VERSION = "1"
SYNONYMS = {
    "fouet": "whisk", "propre": "clean", "sale": "dirty", "cuillere": "spoon",
    "trois-quarts": "three-quarter", "three-quarters": "three-quarter",
    "de-face": "front", "vue-de-face": "front", "profil": "side",
}
PHRASES = re.compile(r"\b(trois[ -]quarts?|three[ -]quarters?|vue[ -]de[ -]face|de[ -]face)\b")


def terms(value):
    value = "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                    if not unicodedata.combining(c))
    def phrase(match):
        text = match[0].replace(" ", "-")
        if text.startswith("trois-"):
            text = "three-quarter"
        return text.replace("-", "_")

    value = PHRASES.sub(phrase, value)
    return [SYNONYMS.get(word.replace("_", "-"), word.replace("_", "-"))
            for word in re.findall(r"[^\W_]+(?:_[^\W_]+)*", value)]


def digest_files(files, root):
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def committed_fingerprint(git, commit):
    digest = hashlib.sha256()
    entries = git.run("ls-tree", "-r", "-z", "--full-tree", commit, "--", "catalog").split(b"\0")
    records = []
    for entry in filter(None, entries):
        header, _, path = entry.partition(b"\t")
        mode, kind, oid = header.split()
        if kind == b"blob" and mode in (b"100644", b"100755") and path.endswith(b".json"):
            records.append((path.removeprefix(b"catalog/"), oid))
    for path, oid in sorted(records):
        digest.update(path + b"\0")
        digest.update(hashlib.sha256(git.run("cat-file", "blob", oid.decode())).digest())
    return digest.hexdigest()


def catalogue_fingerprint(root):
    catalogue = Catalogue(root)
    files = []
    for path in sorted(catalogue.path.rglob("*.json")):
        catalogue._regular_path(path)
        for parent in path.parents:
            if parent == catalogue.path:
                break
            catalogue._regular_path(parent)
        if path.is_file():
            files.append(path)
    return digest_files(files, catalogue.path)


def family(asset):
    value = asset["family"]
    return value["type"] if isinstance(value, dict) else value


def row(asset):
    return {"id": asset["id"], "version": version_number(asset), **{field: asset.get(field) for field in FIELDS},
            **{field: asset.get(field) for field in ("format", "license", "licenseEvidence", "publicExport", "status",
                                                    "dimensions", "sha256", "visualStyle", "facing", "subcategory")},
            "family": family(asset), "usages": asset["usages"], "phash": asset.get("perceptual", {}).get("phash")}


def create_database(connection, rows, fingerprint):
    connection.execute("CREATE TABLE metadata (fingerprint TEXT, version TEXT)")
    connection.execute("INSERT INTO metadata VALUES (?, ?)", (fingerprint, INDEX_VERSION))
    connection.execute("CREATE VIRTUAL TABLE assets USING fts5(id UNINDEXED, "
                       + ", ".join(FIELDS) + ", tokenize='unicode61 remove_diacritics 2')")
    for record in rows:
        values = []
        for field in FIELDS:
            value = record[field] or ""
            values.append(" ".join(terms(" ".join(value) if isinstance(value, list) else value)))
        connection.execute("INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (record["id"], *values))
    connection.commit()


def rebuild_database(root, rows, fingerprint):
    database = root / DATABASE
    Catalogue._regular_path(database.parent).mkdir(exist_ok=True)
    Catalogue._regular_path(database)
    with tempfile.TemporaryDirectory(dir=database.parent) as temporary:
        scratch = Path(temporary) / DATABASE.name
        with closing(sqlite3.connect(scratch)) as connection:
            create_database(connection, rows, fingerprint)
        scratch.replace(database)


def index(root, args):
    with directory_lock(root / "catalog"):
        catalogue = Catalogue(root)
        assets = sorted(read_assets(root).values(), key=lambda asset: asset["id"])
        for asset in assets:
            initialize(asset)
        sheets = [catalogue.read(path) for path in catalogue.documents("sheets")]
        universes = [catalogue.read(path) for path in catalogue.documents("universes")]
        fingerprint = catalogue_fingerprint(root)
        result = {"ok": True, "assets": len(assets), "sheets": len(sheets),
                  "catalogFingerprint": fingerprint}
        if args.dry_run:
            return ExitCode.OK, result
        generated = Catalogue._regular_path(root / "generated")
        Catalogue._regular_path(generated / "reports")
        for filename in OUTPUTS:
            Catalogue._regular_path(generated / filename)
        generated.mkdir(exist_ok=True)
        rows = [row(asset) for asset in assets]
        write_json(generated / "catalog.json", {"assets": assets, "sheets": sheets, "universes": universes})
        write_json(generated / "search-index.json", {"assets": rows})
        emit_usages(root, assets)
        emit_licenses(root, assets, sheets)
        write_json(generated / "duplicates.json", dedup.duplicates(assets, root))
        rebuild_database(root, rows, fingerprint)
        result["fingerprint"] = digest_files([generated / name for name in OUTPUTS], generated)
        return ExitCode.OK, result


def matching(connection, query):
    words = terms(query)
    if not words:
        return {asset_id: 0.0 for (asset_id,) in connection.execute("SELECT id FROM assets")}
    expression = " AND ".join(f'"{word}"' for word in words)
    return dict(connection.execute("SELECT id, -bm25(assets) FROM assets WHERE assets MATCH ?", (expression,)))


def scores(root, args, records, fingerprint):
    path = Catalogue._regular_path(root / DATABASE.parent) / DATABASE.name
    Catalogue._regular_path(path)
    if path.exists():
        try:
            with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True)) as connection:
                if connection.execute("SELECT * FROM metadata").fetchone() == (fingerprint, INDEX_VERSION):
                    return matching(connection, args.query)
        except sqlite3.Error:
            pass
    if args.dry_run:
        with closing(sqlite3.connect(":memory:")) as connection:
            create_database(connection, records.values(), fingerprint)
            return matching(connection, args.query)
    rebuild_database(root, records.values(), fingerprint)
    with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True)) as connection:
        return matching(connection, args.query)


def matches(record, name, value):
    field = record[FILTERS[name]]
    if name == "tag":
        return isinstance(field, list) and value in field
    if name == "used_by":
        return any(use["game"] == value and use["status"] == "active" for use in field)
    return field == value


def reference_hash(reference, records):
    if reference in records:
        if value := records[reference]["phash"]:
            return int(value, 16)
        raise InvalidJSON(f"pHash indisponible pour {reference}.")
    from PIL import Image

    with Image.open(caller_path(reference)) as image:
        return int(dedup.fingerprints(image)["phash"], 16)


def search(root, args):
    if args.limit is not None and args.limit < 1:
        raise UsageError("--limit doit être positif.")
    if not terms(args.query) and args.query.strip():
        raise UsageError("La recherche attend des mots.")
    filters = {name.replace("_", "-"): getattr(args, name) for name in FILTERS if getattr(args, name) is not None}
    if not args.query.strip() and not (args.similar_to or filters):
        raise UsageError("Indiquez du texte, un filtre ou une image de référence.")
    if args.receipt and not args.query.strip():
        raise UsageError("Un reçu exige une requête textuelle.")
    with directory_lock(root / "catalog"):
        records = {asset["id"]: row(asset) for asset in read_assets(root).values()}
        fingerprint = catalogue_fingerprint(root)
        reference = reference_hash(args.similar_to, records) if args.similar_to else None
        results = []
        for asset_id, score in scores(root, args, records, fingerprint).items():
            record = records[asset_id]
            if not all(matches(record, name.replace("-", "_"), value) for name, value in filters.items()):
                continue
            result = {**record, "score": score}
            if reference is not None:
                if not record["phash"]:
                    continue
                distance = (reference ^ int(record["phash"], 16)).bit_count()
                result["phashDistance"] = distance
                result["score"] = 1 - distance / 64
            results.append(result)
        results.sort(key=lambda item: (item.get("phashDistance", 0), -item["score"], item["id"]))
        if args.receipt and not args.dry_run:
            from tools.publish.delivery import output_path

            destination = output_path(root, args.receipt, kind="receipt")
            receipt = {"schemaVersion": "1.0", "query": args.query, "filters": filters.copy(),
                       "searchedAt": datetime.now(timezone.utc).isoformat(), "catalogFingerprint": fingerprint,
                       "results": [result["id"] for result in results], "rejectedCandidates": []}
            if args.similar_to:
                receipt["filters"]["similar-to"] = (args.similar_to if args.similar_to in records
                                                      else f"phash:{reference:016x}")
            if args.limit is not None:
                receipt["filters"]["limit"] = args.limit
            try:
                receipt["registryCommit"] = Git(root).run("rev-parse", "--verify", "HEAD").decode().strip()
            except GitError:
                pass
            write_json(destination, receipt)
        return ExitCode.OK, {"ok": True, "results": results[:args.limit], "catalogFingerprint": fingerprint}


def duplicates(root, args):
    with directory_lock(root / "catalog"):
        report = dedup.duplicates(read_assets(root).values(), root)
        if not args.dry_run:
            directory = Catalogue._regular_path(root / "generated")
            directory.mkdir(exist_ok=True)
            write_json(Catalogue._regular_path(directory / "duplicates.json"), report)
    return ExitCode.OK, {"ok": True, **report}
