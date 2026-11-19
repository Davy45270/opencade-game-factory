"""Lecture d’un instantané Git sans toucher à l’index ni à l’arbre de travail."""

import os
import subprocess
from pathlib import PurePosixPath

from .catalog import parse_json


class InvalidRef(ValueError):
    pass


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=False, capture_output=True,
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1"},
    )


def _output(result):
    if result.returncode:
        raise OSError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def read_base(root, ref):
    _output(_git(root, "rev-parse", "--git-dir"))
    revision = _git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    if revision.returncode:
        raise InvalidRef(f"Révision Git introuvable ou invalide : {ref}")
    commit = revision.stdout.decode("ascii").strip()
    tree = _output(_git(root, "ls-tree", "-rz", "--name-only", commit, "--",
                        "catalog/ids.json", "catalog/assets/", "catalog/sheets/"))
    paths = [PurePosixPath(os.fsdecode(path)) for path in tree.split(b"\0") if path]
    documents = {
        path for path in paths if len(path.parts) == 3 and path.suffix == ".json"
    }
    if PurePosixPath("catalog/ids.json") in paths:
        ids = parse_json(_output(_git(root, "cat-file", "blob", f"{commit}:catalog/ids.json")))
    elif documents:
        raise OSError("Le catalogue de base contient des fiches sans registre d’identifiants.")
    else:
        ids = {}
    def read_document(path):
        return parse_json(_output(_git(root, "cat-file", "blob", f"{commit}:{path}")))

    return ids, documents, read_document
