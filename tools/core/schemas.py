"""Chargement local des schémas et de leurs références."""

import re
from datetime import datetime
from functools import cache
from urllib.parse import urlsplit

from .catalog import ROOT, InvalidJSON, read_json

NAMES = ("asset", "sheet", "usage", "import-job", "source", "sources", "lock", "search-receipt", "migration")


DATE_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


def _date_time(value):
    if not isinstance(value, str):
        return True
    if not DATE_TIME.fullmatch(value):
        return False
    datetime.fromisoformat(value.upper())
    return True


def _repository_url(value):
    if not isinstance(value, str):
        return True
    url = urlsplit(value)
    if not url.hostname or url.username is not None or url.password is not None:
        return False
    return url.scheme in {"http", "https"} and (url.port is None or url.port > 0)


class SchemaSet:
    def __init__(self):
        from jsonschema import Draft202012Validator, FormatChecker
        from jsonschema.exceptions import SchemaError
        from referencing import Registry, Resource

        try:
            documents = {
                name: read_json(ROOT / "schemas" / f"{name}.schema.json") for name in NAMES
            }
            for schema in documents.values():
                Draft202012Validator.check_schema(schema)
            registry = Registry().with_resources(
                (schema["$id"], Resource.from_contents(schema)) for schema in documents.values()
            )
        except (InvalidJSON, SchemaError, KeyError) as exc:
            raise OSError(f"Schémas du registre inutilisables : {exc}") from exc

        formats = FormatChecker()
        formats.checks("date-time", raises=ValueError)(_date_time)
        formats.checks("repository-url", raises=ValueError)(_repository_url)
        self._validators = {
            name: Draft202012Validator(schema, registry=registry, format_checker=formats)
            for name, schema in documents.items()
        }

    def validator(self, name):
        return self._validators[name]


@cache
def schemas():
    return SchemaSet()
