"""Import déterministe des tableaux de décisions Markdown."""

import hashlib
import re
import unicodedata

from tools.core.catalog import CatalogueScopeError, InvalidJSON, json_text, write_json

from .registry import check_path, spdx_ids

COLUMNS = {
    "besoin": "need", "composant": "need", "candidat": "candidate",
    "version": "version", "licence": "licenseRaw",
    "choix": "verdict", "decision": "verdict", "constat": "verdict",
}


class VersionConflict(ValueError):
    pass


def cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith(r"\|"):
        line = line[:-1]
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line)]


def normalize_heading(heading):
    heading = unicodedata.normalize("NFKD", heading.strip("*_` ").casefold())
    return "".join(char for char in heading if not unicodedata.combining(char))


def candidates_in(markdown, name):
    lines = iter(markdown.splitlines())
    previous = ""
    found = False
    candidates = []
    for line in lines:
        headings = cells(previous)
        previous = line
        separator = cells(line)
        if (len(headings) != len(separator) or len(separator) < 2
                or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator)):
            continue
        columns = [COLUMNS.get(normalize_heading(cell)) for cell in headings]
        if "candidate" not in columns:
            continue
        found = True
        for line in lines:
            if "|" not in line or not line.strip():
                break
            row = cells(line)
            if len(row) != len(columns):
                raise InvalidJSON(f"{name} : ligne de tableau de candidats mal formée.")
            candidate = dict.fromkeys(COLUMNS.values())
            candidate.update((key, value or None) for key, value in zip(columns, row) if key)
            if not candidate["candidate"]:
                raise InvalidJSON(f"{name} : candidat vide.")
            license_raw = candidate["licenseRaw"]
            candidate["licenseSpdx"] = license_raw if license_raw in spdx_ids() else "UNKNOWN"
            candidates.append(candidate)
        previous = ""
    return candidates if found else None


def import_decisions(blocks, source, repo, commit, dry_run):
    if not source.is_dir():
        raise OSError("Dossier source indisponible.")
    destination = blocks / "decisions" / repo
    if destination.resolve().is_relative_to(source.resolve()):
        raise CatalogueScopeError("La destination se trouve dans le dossier source.")
    check_path(destination.parent, directory=True)
    check_path(destination, directory=True)

    changes = {}
    ids = set()
    decisions = []
    ignored = []
    for path in sorted(source.glob("*.md")):
        check_path(path)
        raw = path.read_bytes()
        candidates = candidates_in(raw.decode("utf-8-sig"), path.name)
        if candidates is None:
            ignored.append({"path": path.name, "reason": "Colonne Candidat absente."})
            continue
        decision_id = "DEC-" + re.sub(r"[^A-Z0-9]+", "-", f"{repo}-{path.stem}".upper()).strip("-")
        if decision_id in ids:
            raise VersionConflict(f"Identifiant de décision dupliqué : {decision_id}.")
        ids.add(decision_id)
        record = {
            "id": decision_id,
            "source": {
                "repo": repo,
                "path": f"docs/reuse-decisions/{path.name}",
                "commitSha": commit,
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
            "candidates": candidates,
        }
        target = destination / f"{path.stem}.json"
        check_path(target)
        if target.exists():
            if target.read_bytes() != json_text(record).encode("utf-8"):
                raise VersionConflict(f"Une autre version de {decision_id} existe déjà.")
        else:
            changes[target] = record
        decisions.append(record)

    if changes and not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
        for path, record in changes.items():
            write_json(path, record)
    return {"decisions": decisions, "ignored": ignored}
