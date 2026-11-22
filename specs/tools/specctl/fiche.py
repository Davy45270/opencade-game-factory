"""Métadonnées d'une fiche de spécification (REG-003 § 2 et § 4) : titre, propriétaire, statuts orthogonaux, origine
canonique, classification public/privé, décisions BB-001 liées par identifiant.

Trois statuts orthogonaux :
  - `lifecycle` (draft|approved|deprecated|retired) : édité, jamais déduit. Passer en approved, deprecated ou retired
    exige la référence d'un commentaire de David (`HL-n 7-n`) : un agent propose, David approuve (§ 2) ;
  - `implementation` (not-started|partial|implemented|verified) et `evidence` (missing|unverified|verified) : DÉDUITS
    des exigences à chaque écriture, et contrôlés à chaque lecture (une fiche qui ment sur eux est refusée).

Choix de conception : les deux statuts déduits sont stockés dans la fiche pour qu'un export ou un index les
lise sans recalcul, mais `check_record` refuse toute valeur qui diffère du calcul : ils ne peuvent pas diverger.
"""

import copy
import re
from pathlib import PurePosixPath

LIFECYCLES = ("draft", "approved", "deprecated", "retired")
NEEDS_APPROVAL = {"approved", "deprecated", "retired"}
VISIBILITIES = ("private", "public")
OWNER = "david"
DRIVE_ID = re.compile(r"(?<![A-Za-z0-9_-])1[A-Za-z0-9_-]{24,43}(?![A-Za-z0-9_-])")
TITLE = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)


def derived(record):
    """(implementation, evidence) calculés depuis les exigences applicables (hors `ecartee`)."""
    rows = [row for row in record.get("requirements", []) if row["matrixStatus"] != "ecartee"]
    done = [row for row in rows if row["matrixStatus"] == "faite"]
    proved = [row for row in done if "evidence" in row]
    if not rows or not done:
        implementation = "not-started"
    elif len(done) < len(rows):
        implementation = "partial"
    elif len(proved) == len(done):
        implementation = "verified"
    else:
        implementation = "implemented"
    if not proved:
        evidence = "missing"
    elif len(proved) == len(done):
        evidence = "verified"
    else:
        evidence = "unverified"
    return implementation, evidence


def refresh(record):
    """Recalcule les statuts déduits (en place) et rend la fiche."""
    record["implementation"], record["evidence"] = derived(record)
    return record


def drive_ids(lines):
    """Identifiants Drive cités dans les commentaires d'un manifeste d'empreintes (provenance d'import, § 5)."""
    found = set()
    for line in lines:
        if line.lstrip().startswith("#") and "drive" in line.casefold():
            found.update(DRIVE_ID.findall(line))
    return sorted(found)


def title_of(source, record):
    """Premier titre Markdown `# …` des documents de la version la plus récente, sinon le nom du projet."""
    versions = record.get("versions") or []
    documents = versions[-1]["documents"] if versions else record.get("unversionedDocuments", [])
    paths = sorted(provenance["path"] for document in documents for provenance in document["provenances"]
                   if PurePosixPath(provenance["path"]).name.lower().endswith((".md", ".md.txt")))
    for path in paths:
        try:
            match = TITLE.search(source.read(path).decode("utf-8", "replace"))
        except (KeyError, OSError):
            continue
        if match:
            return match[1][:200]
    return record["project"]


# REG-003 § 3 : registry/{games,platform,shared,decisions}/. Les fiches de la plateforme (usine, registre d'assets,
# Control Tower) vont dans platform/, celles d'un jeu dans games/ ; shared/ et decisions/ sont prévus par la spec.
PLATEFORME = frozenset({"asset-registry", "control-tower", "game-factory"})


def categorie(project):
    return "platform" if project in PLATEFORME else "games"


def chemin(spec_id, project):
    """Chemin canonique d'une fiche dans l'usine (relatif à la racine)."""
    return f"specs/registry/{categorie(project)}/{spec_id}.json"


def defaults(record, *, title, source_commit, drive):
    """Métadonnées d'une fiche au premier import. Une fiche existante garde les siennes (elles s'éditent dans l'usine)."""
    record.setdefault("title", title)
    record.setdefault("owner", OWNER)
    record.setdefault("lifecycle", "draft")
    record.setdefault("visibility", "private")
    record.setdefault("canonical", {
        "editableIn": "usine",
        "path": chemin(record["id"], record.get("project")),
        "importedFrom": {"repo": "homelab-docs", "commitSha": source_commit},
    })
    origins = record.setdefault("importOrigins", {"drive": [], "authority": "usine"})
    origins["drive"] = sorted(set(origins.get("drive", [])) | set(drive))
    return refresh(record)


META = ("title", "owner", "lifecycle", "visibility", "canonical")


def adopt(record, incoming):
    """Réimport d'une fiche existante : seules les métadonnées ABSENTES sont reprises (migration) ; les identifiants
    Drive s'ajoutent ; tout le reste s'édite dans l'usine et n'est jamais écrasé par la doc."""
    for key in META:
        if key not in record:
            record[key] = copy.deepcopy(incoming[key])
    origins = record.setdefault("importOrigins", {"drive": [], "authority": "usine"})
    origins["drive"] = sorted(set(origins.get("drive", [])) | set(incoming.get("importOrigins", {}).get("drive", [])))
    return refresh(record)
