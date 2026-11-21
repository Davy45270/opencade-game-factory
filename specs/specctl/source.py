"""Inventaire en lecture seule du commit de documentation."""

import hashlib
import re
import subprocess
from pathlib import PurePosixPath

from tools.core.catalog import InvalidJSON, parse_json

from . import fiche

PROJECT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# `<projet>-sources/` ou `<projet>-sources-<x.y.z>/` : sources figées d'un projet, le suffixe donne leur version
SOURCES = re.compile(r"(.+)-sources(?:-((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)))?")
FINGERPRINT = re.compile(r"([a-fA-F0-9]{64}) [ *](.+)")
ZIP_NAME = re.compile(r"(?<![\w.+-])[\w.+-]+\.zip(?![\w+-]|\.[\w.])", re.IGNORECASE)
VERSION = re.compile(
    r"(?:^|[-_])v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:\.(0|[1-9][0-9]*))?(?!\.[0-9])"
    r"(?=[_.+-]|$)",
    re.IGNORECASE,
)
QUALIFIED_VERSION = re.compile(
    r"(?:^|[-_])v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?)"
    r"(?=_|$)",
    re.IGNORECASE,
)


class VersionConflict(ValueError):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def version_of(path):
    name = PurePosixPath(path).name
    stem = re.sub(r"(?:\.md\.txt|\.[A-Za-z][A-Za-z0-9]*)$", "", name)
    qualified = QUALIFIED_VERSION.search(stem)
    if qualified:
        return qualified[1]
    match = VERSION.search(name)
    if match:
        major, minor, patch = match.groups()
        return f"{major}.{minor}.{patch or '0'}"
    return None


def document_version(relative, archive_version):
    parts = PurePosixPath(relative).parts
    for name in reversed(parts):
        version = version_of(name)
        if version is not None:
            return version
    return archive_version


def relative_path(value):
    path = PurePosixPath(value)
    if (not path.parts or path.is_absolute() or ".." in path.parts
            or "\\" in value or any(ord(char) < 32 for char in value)):
        return None
    return path.as_posix()


class Source:
    def __init__(self, root):
        self.root = root.resolve()
        if self._git("rev-parse", "--show-toplevel").decode().strip() != str(self.root):
            raise OSError("Le dossier source doit être la racine du dépôt de documentation.")
        self.head = self._git("rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        self.drive = {}
        self.files = {}
        for item in self._git("ls-tree", "-r", "-z", self.head, "--", "specs/").split(b"\0"):
            if item:
                metadata, path = item.split(b"\t", 1)
                mode, _, oid = metadata.split()
                if mode in (b"100644", b"100755"):
                    self.files[path.decode("utf-8")] = oid.decode("ascii")
        if not self.files:
            raise OSError("Le commit source ne contient aucun fichier sous specs/.")

    def _git(self, *args):
        result = subprocess.run(["git", "-C", self.root, *args], capture_output=True, check=False)
        if result.returncode:
            raise OSError(f"Impossible de lire la documentation Git ({args[0]}).")
        return result.stdout

    def read(self, path):
        return self._git("cat-file", "blob", self.files[path])

    def frozen(self, path, digest, pinned_commit):
        if path not in self.files or sha256(self.read(path)) != digest:
            return False
        if pinned_commit == self.head:
            return True
        result = subprocess.run(
            ["git", "-C", self.root, "cat-file", "blob", f"{pinned_commit}:{path}"],
            capture_output=True, check=False,
        )
        return result.returncode == 0 and sha256(result.stdout) == digest

    def inventory(self):
        folders = sorted({PurePosixPath(path).parts[1] for path in self.files
                          if len(PurePosixPath(path).parts) >= 3
                          and SOURCES.fullmatch(PurePosixPath(path).parts[1])})
        if not folders:
            raise OSError("Aucun dossier d’archives dans le commit source.")
        par_projet, warnings = {}, []
        for folder in folders:
            project, folder_version = SOURCES.fullmatch(folder).groups()
            if not PROJECT.fullmatch(project):
                raise InvalidJSON(f"Nom de projet invalide : {folder}")
            par_projet.setdefault(project, []).extend(self.documents(folder, warnings, folder_version, project))
        records = {}
        for project, entries in sorted(par_projet.items()):
            spec_id = f"SPEC-{project.upper()}"
            record = {"id": spec_id, "project": project, "requirements": []}
            set_documents(record, entries)
            record["requirements"] = self.requirements(project, spec_id, warnings)
            fiche.defaults(record, title=fiche.title_of(self, record), source_commit=self.head,
                           drive=self.drive.get(project, ()))
            records[spec_id] = record
        return records, warnings

    def matrix_fingerprints(self, folder, project):
        """Empreintes d'un dossier de sources SANS manifeste : les `sources` de la matrice du projet qui y sont rangées
        (spec tirée d'un dépôt de jeu, pas de Drive). Lignes au format du manifeste : « <sha256>  <chemin relatif> »."""
        matrix = f"specs/{project}-conformite.json"
        if matrix not in self.files:
            return None
        try:
            sources = parse_json(self.read(matrix)).get("sources") or []
        except AttributeError as exc:
            raise InvalidJSON(f"Matrice invalide : {matrix}") from exc
        prefix = f"specs/{folder}/"
        lines = [f"{s['sha256']}  {s['fichier'][len(prefix):]}" for s in sources
                 if isinstance(s, dict) and str(s.get("fichier", "")).startswith(prefix) and s.get("sha256")]
        return lines or None

    def documents(self, folder, warnings, folder_version=None, project=None):
        manifest = f"specs/{folder}/empreintes-drive.sha256"
        if manifest in self.files:
            lines = self.read(manifest).decode("utf-8-sig").splitlines()
            if project:
                self.drive.setdefault(project, set()).update(fiche.drive_ids(lines))
        else:
            lines = self.matrix_fingerprints(folder, project) if project else None
            if lines is None:
                warnings.append({"path": manifest, "issue": "manifest-missing"})
                return []
            manifest = f"specs/{project}-conformite.json"
        archive_versions = {
            version
            for line in lines if line.lstrip().startswith("#")
            for name in ZIP_NAME.findall(line)
            if (version := version_of(name)) is not None
        }
        archive_version = next(iter(archive_versions)) if len(archive_versions) == 1 else folder_version
        entries = []
        for number, line in enumerate(lines, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = FINGERPRINT.fullmatch(line)
            if not match:
                raise InvalidJSON(f"Empreinte invalide dans {manifest}, ligne {number}.")
            digest, name = match.groups()
            relative = relative_path(name)
            if relative is None:
                warnings.append({"path": manifest, "line": number, "issue": "path-outside-archive"})
                continue
            path = f"specs/{folder}/{relative}"
            if path not in self.files:
                warnings.append({"path": path, "issue": "archive-not-in-commit"})
                continue
            if sha256(self.read(path)) != digest.lower():
                raise InvalidJSON(f"Empreinte différente du manifeste : {path}")
            entries.append((document_version(relative, archive_version), digest.lower(),
                            {"repo": "homelab-docs", "path": path, "commitSha": self.head}))
        return entries

    def requirements(self, project, spec_id, warnings):
        matrix = f"specs/{project}-conformite.json"
        if matrix not in self.files:
            return []
        value = parse_json(self.read(matrix))
        requirements = []
        try:
            for row in value["exigences"]:
                matrix_id = row["id"]
                if not isinstance(matrix_id, str):
                    raise TypeError("Identifiant de matrice non textuel")
                source = row["source"]
                path = relative_path(source["fichier"])
                if path is None:
                    # La matrice commitée reste la référence pour les preuves hors dépôt.
                    path = matrix
                    warnings.append({"path": matrix, "requirement": matrix_id,
                                     "issue": "requirement-source-outside-repo"})
                requirement = {
                    "id": f"REQ-{spec_id.removeprefix('SPEC-')}-{matrix_id.upper()}",
                    "matrixId": matrix_id,
                    "statement": row["exigence"] if "exigence" in row else source["extrait"],
                    "matrixStatus": row["statut"],
                    "source": {"path": path},
                }
                if "ancre" in source:
                    requirement["source"]["anchor"] = source["ancre"]
                if "preuve_attendue" in row:
                    requirement["acceptance"] = row["preuve_attendue"]
                if "preuve" in row:
                    evidence = row["preuve"]
                    fields = {"type": "type", "ref": "ref", "valeur": "value", "seuil": "threshold"}
                    requirement["evidence"] = {key: evidence[original] for original, key in fields.items()
                                               if original in evidence}
                if "arbitrage" in row:
                    requirement["arbitrage"] = row["arbitrage"]
                if isinstance(row.get("ancien_id"), str):
                    requirement["_previousMatrixId"] = row["ancien_id"]      # suivi des renommages (sync), jamais écrit
                requirements.append(requirement)
        except (KeyError, TypeError, AttributeError) as exc:
            raise InvalidJSON(f"Matrice invalide : {matrix}") from exc
        return sorted(requirements, key=lambda row: (len(row["matrixId"]), row["matrixId"]))


def document_entries(record):
    for version in record["versions"]:
        for document in version["documents"]:
            for provenance in document["provenances"]:
                yield version["version"], document["sha256"], provenance
    for document in record.get("unversionedDocuments", []):
        for provenance in document["provenances"]:
            yield None, document["sha256"], provenance


def set_documents(record, entries):
    by_hash, by_path = {}, {}
    for version, digest, provenance in entries:
        path = provenance["path"]
        if path in by_path and by_path[path] != digest:
            raise VersionConflict(f"Le contenu de l’archive a changé : {path}")
        by_path[path] = digest
        versions, provenances = by_hash.setdefault(digest, (set(), {}))
        if version is not None:
            versions.add(version)
        provenances.setdefault(path, provenance)

    groups = {}
    for digest, (versions, provenances) in sorted(by_hash.items()):
        if len(versions) > 1:
            raise VersionConflict(f"Plusieurs versions pour la même empreinte dans {record['id']}.")
        group = groups.setdefault(next(iter(versions), None), [])
        group.append({"sha256": digest, "provenances": [provenances[key] for key in sorted(provenances)]})
    unversioned = groups.pop(None, [])
    if unversioned:
        record["unversionedDocuments"] = unversioned
    else:
        record.pop("unversionedDocuments", None)
    record["versions"] = [{"version": version, "documents": groups[version]} for version in sorted(groups)]
