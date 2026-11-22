"""Accès aux fiches BB-001 et validation du catalogue."""

import fcntl
import os
from contextlib import contextmanager
from functools import cache

from tools.core.catalog import CatalogueScopeError, InvalidJSON, ROOT, read_json
from tools.core.schemas import schemas


@cache
def validator():
    from jsonschema import Draft202012Validator, FormatChecker

    schema = read_json(ROOT / "blocks" / "schemas" / "block.schema.json")
    return Draft202012Validator(schema, format_checker=FormatChecker())


@cache
def spdx_ids():
    return frozenset(schemas().validator("asset").schema["$defs"]["license"]["enum"]) - {"unknown"}


def check_path(path, *, directory=False):
    if path.is_symlink():
        raise CatalogueScopeError(f"Lien symbolique interdit : {path.name}")
    if path.exists() and not (path.is_dir() if directory else path.is_file()):
        raise OSError(f"Type de chemin inattendu : {path.name}")


@contextmanager
def lock(root, *, write=False):
    # Le même verrou que specctl, sans créer de fichier lors d'une lecture.
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        check_path(root / "blocks", directory=True)
        yield
    finally:
        os.close(descriptor)


def read_catalogue(directory):
    check_path(directory, directory=True)
    records = {}
    for path in sorted(directory.rglob("*.json")):
        check_path(path)
        record = read_json(path)
        error = next(validator().iter_errors(record), None)
        if error:
            location = "/".join(map(str, error.absolute_path)) or "/"
            raise InvalidJSON(f"{path.name} : schéma invalide ({location}, {error.validator}).")
        block_id = record["id"]
        if block_id in records:
            raise InvalidJSON(f"Identifiant dupliqué : {block_id}.")
        license_id = record["origin"]["licenseSpdx"]
        if license_id != "UNKNOWN" and license_id not in spdx_ids():
            raise InvalidJSON(f"{block_id} : licenseSpdx n'est ni un identifiant SPDX ni UNKNOWN.")
        records[block_id] = (path, record)
    return records
