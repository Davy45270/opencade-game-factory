"""Commandes de REG-003 § 6 au-delà du socle : discover, search, impact, verify --project, compare, export, lock,
statuer, relier, blocks, report. Toutes rendent (code commun de l'usine, objet JSON) ; `__init__.main` traduit le code
vers la table de REG-003 § 6.

Choix de conception :
  - lecture seule partout sauf `statuer`, `relier` (et `import`, `arbitrer`) : écriture idempotente, transactionnelle
    (RegistryStore.publish : dossier préparé puis échangé en une opération) et journalisée (journal.event) ;
  - Drive n'est joignable que par le connecteur claude.ai : `discover --source drive` lit une LISTE exportée par ce
    connecteur (`--listing`) ; sans elle, la source est indisponible (code 4), jamais une non-conformité (T04) ;
  - GitHub : on lit les copies locales des dépôts autorisés (`catalog/sources.json`) au commit HEAD, par `git ls-tree`
    et `git cat-file` : aucune écriture, aucun réseau, aucun jeton ;
  - le verrou de spec d'une PR (`.woodpecker/usine/spec.json`, écrit par `ci/woodpecker.py rendre`) est comparé à la
    résolution courante par `verify --project --commit --repo` : une PR fondée sur une spec périmée est refusée (T03).
"""

import copy
import hashlib
import json
import re
import subprocess
import unicodedata
from pathlib import Path, PurePosixPath

from tools.core.catalog import CatalogueScopeError, InvalidJSON, json_text, parse_json
from tools.core.exit_codes import ExitCode

from . import fiche
from .source import SOURCES, document_entries, sha256

SPEC_NAME = re.compile(r"(?i)(?:^|[/_.-])(?:specs?|specifications?|exigences?|requirements?|adr|conformite|backlog)"
                       r"(?:[/_.-]|$)")
SPEC_EXT = (".md", ".txt", ".json", ".yaml", ".yml", ".zip", ".csv")
VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
RELATIONS = {"requires", "implements", "tested-by", "supersedes", "conflicts-with", "reuses", "consumes",
             "produces", "deployed-in"}
IMPACT_TYPES = {"requires", "consumes", "reuses", "implements", "tested-by", "deployed-in"}
LOCK = ".woodpecker/usine/spec.json"


# --- outils -------------------------------------------------------------------------------------------------------

def normalize(text):
    text = unicodedata.normalize("NFKD", str(text).casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def tokens(text):
    return [token for token in re.split(r"[^a-z0-9]+", normalize(text)) if len(token) > 1]


def git(repo, *args, check=True):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if check and result.returncode:
        raise OSError(f"git {args[0]} impossible dans {Path(repo).name}.")
    return result


def known_digests(records):
    return {digest: spec_id for spec_id, record in records.items() for _, digest, _ in document_entries(record)}


def spec_version(spec_id, records):
    """Version applicable d'une spec (arbitrage, sinon version unique), ou None."""
    record = records.get(spec_id)
    if record is None:
        return None
    versions = [entry["version"] for entry in record["versions"]]
    if record.get("arbitration"):
        return record["arbitration"]["version"]
    return versions[0] if len(versions) == 1 else None


def satisfies(version, rule):
    """Plage de version d'une relation : `1.2.3` ou `=1.2.3` exact, `^` même majeure, `~` même mineure, `>=`."""
    if version is None:
        return False
    match = VERSION.match(version)
    wanted = re.sub(r"^(\^|~|>=|=)", "", rule)
    target = tuple(map(int, VERSION.match(wanted).groups()))
    current = tuple(map(int, match.groups())) if match else None
    if current is None:
        return False
    if rule.startswith("^"):
        return current[0] == target[0] and current >= target
    if rule.startswith("~"):
        return current[:2] == target[:2] and current >= target
    if rule.startswith(">="):
        return current >= target
    return current == target


def spec_digest(record, version):
    """Empreinte du contenu d'une version : sha256 des empreintes triées de ses documents."""
    digests = sorted(document["sha256"] for entry in record["versions"] if entry["version"] == version
                     for document in entry["documents"])
    return sha256("\n".join(digests).encode("ascii")) if digests else None


# --- discover ------------------------------------------------------------------------------------------------------

def discover_docs(records, root):
    """Documents des dossiers `specs/<x>-sources*/` du commit HEAD de la doc, connus ou non du registre."""
    from .source import Source
    source = Source(root)
    known = known_digests(records)
    items = []
    for path, _ in sorted(source.files.items()):
        parts = PurePosixPath(path).parts
        if len(parts) < 3 or not SOURCES.fullmatch(parts[1]):
            continue
        digest = sha256(source.read(path))
        items.append({"path": path, "commitSha": source.head, "sha256": digest,
                      "knownAs": known.get(digest), "status": "known" if digest in known else "new"})
    return ExitCode.OK, {"status": "ok", "source": "docs", "commitSha": source.head, "documents": items,
                         "new": sum(item["status"] == "new" for item in items), "readOnly": True}


def discover_github(records, sources_file, clones):
    """Fichiers de spécification des dépôts autorisés, lus dans leur copie locale à HEAD (lecture seule)."""
    try:
        authorized = parse_json(Path(sources_file).read_bytes())["sources"]
    except (KeyError, TypeError) as exc:
        raise InvalidJSON(f"Liste des dépôts autorisés invalide : {sources_file}") from exc
    known = known_digests(records)
    clones = Path(clones)
    existing = {entry.name.casefold(): entry for entry in clones.iterdir()} if clones.is_dir() else {}
    items, unavailable, repos = [], [], []
    for repo in sorted(entry["name"] for entry in authorized):
        directory = existing.get(repo.casefold())
        if directory is None or not (directory / ".git").exists():
            unavailable.append({"repo": repo, "reason": "copie-locale-absente"})
            continue
        head = git(directory, "rev-parse", "--verify", "HEAD^{commit}", check=False)
        if head.returncode:
            unavailable.append({"repo": repo, "reason": "git-illisible"})
            continue
        commit = head.stdout.decode().strip()
        repos.append({"repo": repo, "commitSha": commit})
        listing = git(directory, "ls-tree", "-r", "-z", commit).stdout.split(b"\0")
        for item in listing:
            if not item:
                continue
            metadata, raw = item.split(b"\t", 1)
            path = raw.decode("utf-8", "replace")
            if (metadata.split()[0] not in (b"100644", b"100755") or "node_modules/" in path
                    or not path.lower().endswith(SPEC_EXT) or not SPEC_NAME.search(path)):
                continue
            blob = git(directory, "cat-file", "blob", metadata.split()[2].decode()).stdout
            digest = sha256(blob)
            items.append({"repo": repo, "path": path, "commitSha": commit, "sha256": digest,
                          "knownAs": known.get(digest), "status": "known" if digest in known else "new"})
    if not repos:
        return ExitCode.IO, {"status": "source-unavailable", "source": "github", "unavailable": unavailable}
    return ExitCode.OK, {"status": "partial" if unavailable else "ok", "source": "github", "repos": repos,
                         "documents": items, "unavailable": unavailable,
                         "new": sum(item["status"] == "new" for item in items), "readOnly": True}


def discover_drive(records, listing):
    """Liste Drive exportée par le connecteur (id, name) : rapprochée des identifiants Drive des fiches."""
    if listing is None:
        return ExitCode.IO, {"status": "source-unavailable", "source": "drive",
                             "message": "Drive n'est lisible que par le connecteur claude.ai : fournir --listing."}
    try:
        files = parse_json(Path(listing).read_bytes())
        files = files["files"] if isinstance(files, dict) else files
        rows = [(str(entry["id"]), str(entry.get("name", ""))) for entry in files]
    except (KeyError, TypeError) as exc:
        raise InvalidJSON("Liste Drive invalide : objets {id, name} attendus.") from exc
    known = {drive_id: spec_id for spec_id, record in records.items()
             for drive_id in record.get("importOrigins", {}).get("drive", [])}
    items = [{"driveId": drive_id, "name": name, "knownAs": known.get(drive_id),
              "status": "known" if drive_id in known else "new"} for drive_id, name in sorted(rows)]
    return ExitCode.OK, {"status": "ok", "source": "drive", "documents": items,
                         "new": sum(item["status"] == "new" for item in items), "readOnly": True}


# --- search, impact, blocks ----------------------------------------------------------------------------------------

def search(records, query, project=None, limit=20):
    wanted = set(tokens(query))
    if not wanted:
        return ExitCode.USAGE, {"status": "usage", "message": "Requête vide."}
    hits = []
    for spec_id, record in sorted(records.items()):
        if project and record["project"] != project:
            continue
        for kind, ident, text in [("spec", spec_id, record.get("title", ""))] + [
                ("requirement", row["id"], row["statement"]) for row in record["requirements"]]:
            words = set(tokens(text))
            score = len(wanted & words)
            if score:
                hits.append({"kind": kind, "id": ident, "specId": spec_id, "project": record["project"],
                             "text": text[:240], "score": round(score / len(wanted), 4)})
    hits.sort(key=lambda hit: (-hit["score"], hit["id"]))
    return ExitCode.OK, {"status": "ok", "query": query, "hits": hits[:limit], "total": len(hits)}


def impact(records, spec_id):
    """Consommateurs directs et transitifs d'une spec (relations inverses), projets à prévenir (T06)."""
    if spec_id not in records:
        return ExitCode.CHECK_FAILED, {"status": "spec-not-found", "specId": spec_id}
    reverse = {}
    for source_id, record in records.items():
        for relation in record.get("relations", []):
            if relation["type"] in IMPACT_TYPES:
                reverse.setdefault(relation["target"], []).append((source_id, relation["type"]))
    seen, frontier, consumers = {spec_id}, [spec_id], []
    depth = 0
    while frontier:
        depth += 1
        following = []
        for target in frontier:
            for source_id, kind in sorted(reverse.get(target, [])):
                if source_id in seen:
                    continue
                seen.add(source_id)
                following.append(source_id)
                consumers.append({"specId": source_id, "project": records[source_id]["project"], "relation": kind,
                                  "via": target, "depth": depth})
        frontier = following
    projects = sorted({consumer["project"] for consumer in consumers})
    return ExitCode.OK, {"status": "ok", "specId": spec_id, "version": spec_version(spec_id, records),
                         "consumers": consumers, "projects": projects}


def blocks(records, root, spec_id):
    """Décisions BB-001 liées à une spec, lues dans le catalogue des briques par leur identifiant (jamais recopiées)."""
    if spec_id not in records:
        return ExitCode.CHECK_FAILED, {"status": "spec-not-found", "specId": spec_id}
    catalogue = {}
    directory = root / "blocks" / "catalog"
    if directory.is_dir():
        from blocks.bbctl.registry import read_catalogue
        catalogue = {block_id: record for block_id, (_, record) in read_catalogue(directory).items()}
    declared = set(records[spec_id].get("decisions", []))
    linked = sorted(declared | {block_id for block_id, block in catalogue.items() if spec_id in block["specIds"]})
    rows, missing, untraceable = [], [], []
    for block_id in linked:
        block = catalogue.get(block_id)
        if block is None:
            missing.append(block_id)
            continue
        decision, origin = block["decision"], block["origin"]
        row = {"blockId": block_id, "choice": decision.get("choice"), "decided": decision["status"] == "decided",
               "rationale": bool(decision.get("rationale")), "licenseSpdx": origin["licenseSpdx"],
               "repositoryUrl": origin.get("repositoryUrl"), "commitSha": origin.get("commitSha")}
        if not row["decided"] or not row["rationale"] or origin["licenseSpdx"] == "UNKNOWN":
            untraceable.append(block_id)
        rows.append(row)
    failed = bool(missing or untraceable)
    return (ExitCode.CHECK_FAILED if failed else ExitCode.OK), {
        "status": "non-compliant" if failed else "ok", "specId": spec_id, "decisions": rows,
        "brokenLinks": missing, "untraceable": untraceable}


# --- verrou d'une PR -----------------------------------------------------------------------------------------------

def lock(records, project):
    """Verrou du jeu de specs appliqué (SemVer, empreinte du contenu, horodatage de résolution donné par resolve)."""
    from . import resolve
    code, payload = resolve(records, project)
    if code != ExitCode.OK:
        return code, payload
    specs = []
    for entry in payload["specs"]:
        record = records[entry["specId"]]
        specs.append({"specId": entry["specId"], "version": entry["version"],
                      "specDigest": spec_digest(record, entry["version"])})
    return ExitCode.OK, {"status": "ok", "project": project, "specs": specs, "resolvedAt": payload["resolvedAt"]}


def verify_project(records, project, commit, repo):
    """Verrou d'une PR (spec.json au commit) comparé à la résolution courante : périmé = non conforme (T03)."""
    shown = git(repo, "show", f"{commit}:{LOCK}", check=False)
    if shown.returncode:
        probe = git(repo, "cat-file", "-e", f"{commit}^{{commit}}", check=False)
        if probe.returncode:
            return ExitCode.IO, {"status": "source-unavailable", "project": project, "commitSha": commit}
        return ExitCode.CHECK_FAILED, {"status": "lock-missing", "project": project, "commitSha": commit}
    try:
        locked = parse_json(shown.stdout)
    except InvalidJSON:
        return ExitCode.CHECK_FAILED, {"status": "lock-invalid", "project": project, "commitSha": commit}
    code, current = lock(records, project)
    if code != ExitCode.OK:
        return code, current
    applicable = current["specs"][0] if len(current["specs"]) == 1 else None
    reasons = []
    if locked.get("project") != project:
        reasons.append("projet")
    if applicable is None or locked.get("specId") != applicable["specId"]:
        reasons.append("specId")
    elif locked.get("version") != applicable["version"]:
        reasons.append("version")
    elif "specDigest" in locked and locked["specDigest"] != applicable["specDigest"]:
        reasons.append("contenu")
    if locked.get("status") != "ok":
        reasons.append("statut")
    result = {"project": project, "commitSha": commit, "locked": locked, "current": current["specs"],
              "reasons": reasons}
    if reasons:
        return ExitCode.CHECK_FAILED, {"status": "outdated", **result}
    return ExitCode.OK, {"status": "ok", **result}


# --- compare, export -----------------------------------------------------------------------------------------------

def registry_at(root, ref):
    """Fiches du registre à un commit de l'usine (lecture seule)."""
    listing = git(root, "ls-tree", "-z", f"{ref}:specs/registry", check=False)
    if listing.returncode:
        probe = git(root, "rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
        if probe.returncode:
            raise ValueError(f"Référence inconnue : {ref}")
        return {}
    records = {}
    for item in listing.stdout.split(b"\0"):
        if not item:
            continue
        metadata, name = item.split(b"\t", 1)
        name = name.decode()
        if name.startswith("SPEC-") and name.endswith(".json"):
            records[name[:-5]] = parse_json(git(root, "cat-file", "blob", metadata.split()[2].decode()).stdout)
    return records


def compare(root, before_ref, after_ref, spec_filter=None):
    if git(root, "rev-parse", "--git-dir", check=False).returncode:
        return ExitCode.IO, {"status": "source-unavailable", "message": "Le registre n'est pas un dépôt git."}
    try:
        before, after = registry_at(root, before_ref), registry_at(root, after_ref)
    except ValueError as exc:
        return ExitCode.USAGE, {"status": "usage", "message": str(exc)}
    ids = sorted(set(before) | set(after))
    if spec_filter:
        ids = [spec_id for spec_id in ids if spec_id == spec_filter]
    changes = []
    for spec_id in ids:
        old, new = before.get(spec_id), after.get(spec_id)
        if old is None or new is None:
            changes.append({"specId": spec_id, "change": "added" if old is None else "removed"})
            continue
        versions = lambda r: {entry["version"]: spec_digest(r, entry["version"]) for entry in r["versions"]}
        rows = lambda r: {row["id"]: row for row in r["requirements"]}
        ov, nv, orows, nrows = versions(old), versions(new), rows(old), rows(new)
        diff = {
            "versionsAdded": sorted(set(nv) - set(ov)), "versionsRemoved": sorted(set(ov) - set(nv)),
            "versionsChanged": sorted(v for v in set(ov) & set(nv) if ov[v] != nv[v]),
            "requirementsAdded": sorted(set(nrows) - set(orows)),
            "requirementsRemoved": sorted(set(orows) - set(nrows)),
            "requirementsStatusChanged": [
                {"id": key, "from": orows[key]["matrixStatus"], "to": nrows[key]["matrixStatus"]}
                for key in sorted(set(orows) & set(nrows))
                if orows[key]["matrixStatus"] != nrows[key]["matrixStatus"]],
            "fieldsChanged": sorted(key for key in set(old) | set(new)
                                    if key not in ("versions", "requirements") and old.get(key) != new.get(key)),
        }
        if any(diff.values()):
            changes.append({"specId": spec_id, "change": "modified", **diff})
    return ExitCode.OK, {"status": "ok", "from": before_ref, "to": after_ref, "changes": changes}


def public_view(record):
    """Ce qu'un export public peut porter d'une spec publique : ni preuves, ni chemins d'archives, ni Drive."""
    version = spec_version(record["id"], {record["id"]: record})
    return {"id": record["id"], "project": record["project"], "title": record["title"], "version": version,
            "lifecycle": record["lifecycle"], "implementation": record["implementation"],
            "evidence": record["evidence"],
            "requirements": [{"id": row["id"], "statement": row["statement"], "status": row["matrixStatus"]}
                             for row in record["requirements"]]}


def export(records, fmt, public):
    if public:
        specs = [public_view(record) for _, record in sorted(records.items()) if record["visibility"] == "public"]
        excluded = sorted(spec_id for spec_id, record in records.items() if record["visibility"] != "public")
    else:
        specs = [copy.deepcopy(record) for _, record in sorted(records.items())]
        excluded = []
    payload = {"status": "ok", "classification": "public" if public else "private", "format": fmt,
               "specs": specs, "excludedPrivate": len(excluded)}
    if fmt == "markdown":
        lines = [f"# Registre des spécifications ({payload['classification']})", ""]
        for record in specs:
            version = record.get("version") or spec_version(record["id"], {record["id"]: record}) or "?"
            lines += [f"## {record['id']} — {record['title']}", "",
                      f"- projet : {record['project']} ; version : {version}",
                      f"- lifecycle : {record['lifecycle']} ; implementation : {record['implementation']} ; "
                      f"evidence : {record['evidence']}", ""]
            for row in record["requirements"]:
                status = row.get("status") or row.get("matrixStatus")
                lines.append(f"- `{row['id']}` ({status}) {row['statement']}")
            lines.append("")
        payload["markdown"] = "\n".join(lines)
    return ExitCode.OK, payload


# --- écritures : statuer, relier -----------------------------------------------------------------------------------

def statuer(store, records, spec_id, lifecycle, visibility, ref):
    """lifecycle / visibilité d'une spec. Approuver, déprécier, retirer ou rendre publique exige `HL-n 7-n` (§ 2)."""
    record = records.get(spec_id)
    if record is None:
        return ExitCode.CHECK_FAILED, {"status": "spec-not-found", "specId": spec_id}
    if lifecycle is None and visibility is None:
        return ExitCode.USAGE, {"status": "usage", "message": "--lifecycle ou --visibility attendu."}
    needs = (lifecycle in fiche.NEEDS_APPROVAL) or visibility == "public"
    if needs and not (ref and re.fullmatch(r"HL-[0-9]+ 7-[0-9]+", ref)):
        return ExitCode.SAFETY, {"status": "approval-required", "specId": spec_id,
                                 "message": "Approbation de David requise : --ref « HL-n 7-n »."}
    updated = copy.deepcopy(record)
    if lifecycle is not None:
        updated["lifecycle"] = lifecycle
        if lifecycle in fiche.NEEDS_APPROVAL:
            updated["lifecycleRef"] = ref
        else:
            updated.pop("lifecycleRef", None)
    if visibility is not None:
        updated["visibility"] = visibility
        if visibility == "public":
            updated["visibilityRef"] = ref
        else:
            updated.pop("visibilityRef", None)
    if updated != record:
        store.publish({spec_id: updated})
    return ExitCode.OK, {"status": "ok", "specId": spec_id, "lifecycle": updated["lifecycle"],
                         "visibility": updated["visibility"], "changed": updated != record}


def relier(store, records, spec_id, kind, target, rule):
    record = records.get(spec_id)
    if record is None:
        return ExitCode.CHECK_FAILED, {"status": "spec-not-found", "specId": spec_id}
    if target.startswith("SPEC-") and target not in records:
        return ExitCode.CHECK_FAILED, {"status": "broken-link", "specId": spec_id, "target": target}
    relation = {"type": kind, "target": target}
    if rule:
        relation["range"] = rule
    updated = copy.deepcopy(record)
    relations = [r for r in updated.get("relations", []) if (r["type"], r["target"]) != (kind, target)]
    updated["relations"] = sorted(relations + [relation], key=lambda r: (r["type"], r["target"]))
    if updated != record:
        store.publish({spec_id: updated})
    return ExitCode.OK, {"status": "ok", "specId": spec_id, "relation": relation, "changed": updated != record}


# --- rapport de migration (§ 5) ------------------------------------------------------------------------------------

def report(records, source, warnings, incoming):
    """Rapport de migration : correspondance chemin → SPEC-ID, doublons (une identité, plusieurs provenances),
    conflits de version à arbitrer, éléments inconnus, liens cassés, couverture et graphe spec → jeu → briques."""
    mapping, duplicates, conflicts, coverage, graph = [], [], [], [], []
    for spec_id, record in sorted(incoming.items()):
        for _, digest, provenance in document_entries(record):
            mapping.append({"path": provenance["path"], "specId": spec_id, "sha256": digest})
        for entry in record["versions"]:
            for document in entry["documents"]:
                if len(document["provenances"]) > 1:
                    duplicates.append({"specId": spec_id, "sha256": document["sha256"],
                                       "paths": [p["path"] for p in document["provenances"]]})
        current = records.get(spec_id, record)
        versions = [entry["version"] for entry in record["versions"]]
        if len(versions) > 1 and not current.get("arbitration"):
            conflicts.append({"specId": spec_id, "versions": versions, "decision": "arbitrage de David requis"})
        rows = [row for row in current["requirements"] if row["matrixStatus"] != "ecartee"]
        done = [row for row in rows if row["matrixStatus"] == "faite" and "evidence" in row]
        coverage.append({"specId": spec_id, "applicable": len(rows), "proved": len(done),
                         "ratio": round(len(done) / len(rows), 4) if rows else None})
        graph.append({"specId": spec_id, "project": record["project"],
                      "relations": current.get("relations", []), "decisions": current.get("decisions", [])})
    known = set(incoming) | set(records)
    broken = [{"specId": spec_id, **relation} for spec_id, record in sorted(records.items())
              for relation in record.get("relations", [])
              if relation["target"].startswith("SPEC-") and relation["target"] not in known]
    return {"sourceCommit": source.head, "mapping": sorted(mapping, key=lambda m: m["path"]),
            "duplicates": duplicates, "conflicts": conflicts, "unknown": warnings, "brokenLinks": broken,
            "coverage": coverage, "graph": graph,
            "decisionsRequired": [conflict["specId"] for conflict in conflicts]}
