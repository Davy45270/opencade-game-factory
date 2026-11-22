"""Lecture, validation et publication atomique du registre."""

import ctypes
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from contextlib import contextmanager
from functools import cache
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from tools.core.catalog import CatalogueScopeError, InvalidJSON, ROOT, json_text, parse_json, read_json, write_json

from . import fiche
from .source import SOURCES, document_entries, relative_path


@cache
def validator():
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    directory = ROOT / "specs" / "schemas"
    # REG-003 § 3 : cinq schémas ; la fiche (specification) référence les quatre autres par leur $id.
    specification = read_json(directory / "specification.schema.json")
    references = Registry()
    for nom in ("requirement", "dependency", "implementation", "decision", "specification"):
        schema = read_json(directory / f"{nom}.schema.json")
        Draft202012Validator.check_schema(schema)
        references = references.with_resource(schema["$id"], Resource.from_contents(schema))
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

    if (record["implementation"], record["evidence"]) != fiche.derived(record):
        raise InvalidJSON(f"{spec_id} : statuts implementation/evidence différents du calcul sur les exigences.")
    if record["lifecycle"] in fiche.NEEDS_APPROVAL and "lifecycleRef" not in record:
        raise InvalidJSON(f"{spec_id} : lifecycle {record['lifecycle']} sans approbation de David (lifecycleRef).")
    if record["visibility"] == "public" and "visibilityRef" not in record:
        raise InvalidJSON(f"{spec_id} : spec publique sans approbation de David (visibilityRef).")
    if record["canonical"]["path"] != fiche.chemin(spec_id, record.get("project")):
        raise InvalidJSON(f"{spec_id} : origine canonique incohérente.")

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


IDS, JOURNAL = "ids.json", "journal.jsonl"


class BaseInconnue(ValueError):
    pass


def owned_ids(record):
    """Identifiants qu'une fiche fait naître : la spec et chacune de ses exigences, tous rattachés à la spec."""
    return {record["id"]: record["id"], **{row["id"]: record["id"] for row in record["requirements"]}}


def check_ids(records, ids):
    """§ 2 : un identifiant publié n'est jamais recyclé. Chaque identifiant porté par une fiche est au registre
    d'IDs (ajout seul), rattaché à la bonne spec."""
    errors = []
    for record in records.values():
        for key, owner in sorted(owned_ids(record).items()):
            if ids.get(key) != owner:
                errors.append(f"{key} : absent du registre d'IDs ou rattaché à {ids.get(key)} (attendu {owner}).")
    return errors


def check_against_base(root, ref, ids):
    """Ajout seul par rapport à la base de la PR : aucune clé retirée, aucune clé réattribuée."""
    git = ["git", "-C", str(root)]
    if subprocess.run([*git, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"],
                      capture_output=True).returncode:
        raise BaseInconnue(f"Révision Git introuvable : {ref}")
    shown = subprocess.run([*git, "show", f"{ref}:specs/registry/{IDS}"], capture_output=True)
    base = parse_json(shown.stdout) if shown.returncode == 0 else {}
    errors = []
    for key, owner in sorted(base.items()):
        if key not in ids:
            errors.append(f"{key} : identifiant retiré du registre d'IDs (jamais recyclé).")
        elif ids[key] != owner:
            errors.append(f"{key} : identifiant réattribué ({owner} → {ids[key]}).")
    return errors


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
        for path in sorted(self.path.rglob("SPEC-*.json")):
            if path.is_symlink():
                raise CatalogueScopeError(f"Lien symbolique interdit : {path.name}")
            if not path.is_file():
                raise InvalidJSON(f"Fiche inaccessible : {path.name}")
            record = read_json(path)
            check_record(path.stem, record)
            if record["id"] in records:
                raise InvalidJSON(f"{record['id']} : fiche en double dans le registre.")
            records[record["id"]] = record
        return records

    def ids(self):
        path = self.path / IDS
        return read_json(path) if path.is_file() else {}

    def publish_side(self, name, value, command, key):
        """Fichier annexe du registre (ex. documents Drive à importer), publié dans le même lot atomique, journalisé."""
        self.publish({}, command, side={name: value}, key=key)

    def publish(self, changes, command, side=None, key=None):
        """Prépare le lot avant de rendre visible le nouveau dossier en une opération. Le registre d'IDs (ajout seul)
        et le journal d'audit (une ligne par fiche dont le contenu change) font partie du même lot atomique."""
        self.path.parent.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix=".registry-", dir=self.path.parent) as workspace:
            stage = Path(workspace) / "registry"
            if self.path.exists():
                shutil.copytree(self.path, stage, symlinks=True)
            else:
                stage.mkdir()
            ids = read_json(stage / IDS) if (stage / IDS).is_file() else {}
            at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            lines = []
            for spec_id, record in changes.items():
                fiche.refresh(record)
                check_record(spec_id, record)
                for key, owner in owned_ids(record).items():
                    if ids.setdefault(key, owner) != owner:
                        raise InvalidJSON(f"{key} : identifiant déjà attribué à {ids[key]}, jamais recyclé.")
                target = stage / PurePosixPath(fiche.chemin(spec_id, record.get("project"))).relative_to("specs/registry")
                for ailleurs in stage.rglob(f"{spec_id}.json"):
                    if ailleurs != target:          # changement de catégorie : une seule fiche par identifiant
                        ailleurs.unlink()
                target.parent.mkdir(parents=True, exist_ok=True)
                before = sha256_text(target.read_text(encoding="utf-8")) if target.is_file() else None
                after = sha256_text(json_text(record))
                if before == after:
                    continue
                write_json(target, record)
                lines.append({"at": at, "command": command, "specId": spec_id,
                              "sha256Before": before, "sha256After": after})
            for name, value in (side or {}).items():
                target = stage / name
                before = sha256_text(target.read_text(encoding="utf-8")) if target.is_file() else None
                after = sha256_text(json_text(value))
                if before != after:
                    write_json(target, value)
                    lines.append({"at": at, "command": command, "file": name, "key": key,
                                  "sha256Before": before, "sha256After": after})
            if not (stage / IDS).is_file() or read_json(stage / IDS) != ids:
                write_json(stage / IDS, dict(sorted(ids.items())))
            if lines:
                with open(stage / JOURNAL, "a", encoding="utf-8") as journal:
                    journal.writelines(json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n" for line in lines)
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
