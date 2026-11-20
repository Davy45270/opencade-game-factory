"""Lecture, validation et publication atomique du registre."""

import ctypes
import fcntl
import os
import shutil
from contextlib import contextmanager
from functools import cache
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from tools.core.catalog import CatalogueScopeError, InvalidJSON, ROOT, read_json, write_json

from .source import SOURCES, document_entries, relative_path


@cache
def validator():
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    directory = ROOT / "specs" / "schemas"
    requirement = read_json(directory / "requirement.schema.json")
    specification = read_json(directory / "specification.schema.json")
    for schema in (requirement, specification):
        Draft202012Validator.check_schema(schema)
    references = Registry().with_resource(requirement["$id"], Resource.from_contents(requirement))
    return Draft202012Validator(specification, registry=references)


def check_record(name, record):
    error = next(validator().iter_errors(record), None)
    if error:
        location = "/".join(map(str, error.absolute_path)) or "/"
        raise InvalidJSON(f"{name} : schéma invalide ({location}, {error.validator}).")

    spec_id = record["id"]
    project = record["project"]
    if name != spec_id or spec_id != f"SPEC-{project.upper()}":
        raise InvalidJSON(f"{name} : identifiant incohérent avec la fiche {spec_id} ou son projet.")

    matrix_ids = set()
    for requirement in record["requirements"]:
        matrix_id = requirement["matrixId"]
        expected_id = f"REQ-{spec_id.removeprefix('SPEC-')}-{matrix_id.upper()}"
        source_path = requirement["source"]["path"]
        if (requirement["id"] != expected_id or matrix_id in matrix_ids
                or relative_path(source_path) != source_path):
            raise InvalidJSON(f"{spec_id} : exigence incohérente ou dupliquée ({expected_id}).")
        matrix_ids.add(matrix_id)

    versions = [entry["version"] for entry in record["versions"]]
    if len(set(versions)) != len(versions):
        raise InvalidJSON(f"{spec_id} : version dupliquée.")
    if "arbitration" in record and record["arbitration"]["version"] not in versions:
        raise InvalidJSON(f"{spec_id} : arbitrage sans version correspondante.")

    documents = [document for entry in record["versions"] for document in entry["documents"]]
    documents.extend(record.get("unversionedDocuments", []))
    if len({document["sha256"] for document in documents}) != len(documents):
        raise InvalidJSON(f"{spec_id} : empreinte dupliquée.")
    paths = set()
    for _, _, provenance in document_entries(record):
        path = provenance["path"]
        dossier = PurePosixPath(path).parts[1] if len(PurePosixPath(path).parts) > 1 else ""
        m = SOURCES.fullmatch(dossier)
        if (relative_path(path) != path or PurePosixPath(path).parts[0] != "specs" or not m or m[1] != project
                or path in paths):
            raise InvalidJSON(f"{spec_id} : provenance hors archive ou dupliquée.")
        paths.add(path)


def check_directory(path):
    if path.is_symlink():
        raise CatalogueScopeError(f"Lien symbolique interdit : {path.name}")
    if path.exists() and not path.is_dir():
        raise OSError(f"Ce chemin doit être un dossier : {path.name}")


class RegistryStore:
    def __init__(self, root):
        self.root = root
        self.path = root / "specs" / "registry"

    @contextmanager
    def lock(self, *, write=False):
        # Le dossier racine reste stable pendant le remplacement de registry/.
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            check_directory(self.path.parent)
            check_directory(self.path)
            yield
        finally:
            os.close(descriptor)

    def read(self):
        records = {}
        for path in sorted(self.path.glob("SPEC-*.json")):
            if path.is_symlink():
                raise CatalogueScopeError(f"Lien symbolique interdit : {path.name}")
            if not path.is_file():
                raise InvalidJSON(f"Fiche inaccessible : {path.name}")
            record = read_json(path)
            check_record(path.stem, record)
            records[record["id"]] = record
        return records

    def publish(self, changes):
        """Prépare le lot avant de rendre visible le nouveau dossier en une opération."""
        self.path.parent.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix=".registry-", dir=self.path.parent) as workspace:
            stage = Path(workspace) / "registry"
            if self.path.exists():
                shutil.copytree(self.path, stage, symlinks=True)
            else:
                stage.mkdir()
            for spec_id, record in changes.items():
                check_record(spec_id, record)
                write_json(stage / f"{spec_id}.json", record)
            if self.path.exists():
                exchange_directories(stage, self.path)
            else:
                stage.rename(self.path)


def exchange_directories(first, second):
    """Échange deux dossiers sur le même système de fichiers (Linux renameat2)."""
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise OSError("Le système ne fournit pas le remplacement atomique du registre.") from exc
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    at_fdcwd, rename_exchange = -100, 2
    if rename(at_fdcwd, os.fsencode(first), at_fdcwd, os.fsencode(second), rename_exchange):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
