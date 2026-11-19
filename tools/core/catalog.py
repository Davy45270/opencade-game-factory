"""Lecture stricte et écriture atomique des JSON versionnés."""

import json
import math
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLLECTIONS = ("assets", "sheets", "universes")


class InvalidJSON(ValueError):
    """Le document ne représente pas un JSON exploitable."""


class CatalogueScopeError(ValueError):
    """Une entrée du catalogue sort du périmètre de lecture."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidJSON(f"Clé JSON répétée : {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise InvalidJSON(f"Constante hors JSON : {value}")


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        _invalid_constant(value)
    return parsed


def _check_unicode(value):
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, dict):
        for key, child in value.items():
            _check_unicode(key)
            _check_unicode(child)
    elif isinstance(value, list):
        for child in value:
            _check_unicode(child)


def parse_json(content):
    try:
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        value = json.loads(content, object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant, parse_float=_finite_float)
        _check_unicode(value)
        return value
    except InvalidJSON:
        raise
    except (ValueError, RecursionError) as exc:
        raise InvalidJSON(str(exc)) from exc


def read_json(path):
    return parse_json(path.read_bytes())


def json_text(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def write_json(path, value):
    write_text(path, json_text(value))


def write_text(path, content):
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Catalogue:
    def __init__(self, root=ROOT):
        self.path = Path(root) / "catalog"
        self._regular_path(self.path)

    @staticmethod
    def _regular_path(path):
        if path.is_symlink():
            raise CatalogueScopeError(f"Lien symbolique interdit dans le catalogue : {path.name}")
        return path

    def documents(self, collection):
        if collection not in COLLECTIONS:
            raise ValueError(f"Collection inconnue : {collection}")
        directory = self._regular_path(self.path / collection)
        return sorted(path for path in directory.iterdir() if path.suffix == ".json")

    def read(self, path):
        checked = self._regular_path(path)
        if not checked.is_file():
            raise OSError(f"Fichier du catalogue indisponible : {path.name}")
        return read_json(checked)
