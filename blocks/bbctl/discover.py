"""Découverte des briques dans les dépôts autorisés (BB-001 § 3), en lecture seule.

Chaque dépôt est lu dans sa copie locale AU COMMIT HEAD, par git (ls-tree, cat-file) : jamais l'arbre de travail, jamais
d'écriture. Un adaptateur par écosystème (§ 9) : npm (package.json, versions et licences du package-lock.json),
Python (requirements.txt), modules locaux d'un monorepo (`src/engines/<x>`, `packages/<x>`) avec leurs usages par jeu.

Seules les dépendances DIRECTES deviennent des briques (§ 4). Une bibliothèque sous deux versions donne deux briques
(T02). Ce qui est inconnu reste null ou UNKNOWN (§ 7). Les observations de chaque dépôt sont gardées par commit dans
`blocks/discovery.json` : un dépôt dont le commit n'a pas changé n'est pas relu ; le catalogue se reconstruit depuis
l'union des observations, à l'octet (T03). Les identifiants viennent de `blocks/ids.json` (ajout seul).
"""

import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

from tools.core.catalog import InvalidJSON, json_text, parse_json, read_json, write_json

from .registry import spdx_ids

DISCOVERED_BY = "bbctl discover"
TEST_HARNESSES = {"vitest", "jest", "mocha", "playwright", "@playwright/test", "cypress", "ava", "uvu",
                  "@vitest/coverage-v8", "@vitest/browser", "c8", "nyc"}
LOCAL_ROOTS = (("src", "engines"), ("packages",))
SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
REQUIREMENT = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(?:==\s*([A-Za-z0-9.!+_-]+))?")


class Repo:
    def __init__(self, name, directory, commit):
        self.name, self.directory, self.commit = name, directory, commit
        listing = self.git("ls-tree", "-r", "-z", "--name-only", commit).split(b"\0")
        self.paths = sorted(os.fsdecode(p) for p in listing if p)

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.directory), *args], capture_output=True,
                                env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0"})
        if result.returncode:
            raise OSError(result.stderr.decode(errors="replace").strip())
        return result.stdout

    def read(self, path):
        return self.git("cat-file", "blob", f"{self.commit}:{path}")

    def json(self, path):
        try:
            return parse_json(self.read(path)) if path in self.paths else None
        except InvalidJSON:
            return None


def license_of(raw):
    return raw if isinstance(raw, str) and raw in spdx_ids() else "UNKNOWN"


def npm(repo):
    """package.json à toute profondeur (hors node_modules) ; versions et licences du package-lock.json voisin."""
    found = []
    for path in repo.paths:
        pure = PurePosixPath(path)
        if pure.name != "package.json" or "node_modules" in pure.parts:
            continue
        manifest = repo.json(path)
        if not isinstance(manifest, dict):
            continue
        lock = repo.json(str(pure.with_name("package-lock.json"))) or {}
        packages = lock.get("packages") if isinstance(lock.get("packages"), dict) else {}
        for section, dev in (("dependencies", False), ("devDependencies", True)):
            for name in sorted(manifest.get(section) or {}):
                if not isinstance(name, str):
                    continue
                entry = packages.get(f"node_modules/{name}") or {}
                version = entry.get("version") if isinstance(entry.get("version"), str) else None
                kind = "test-harness" if name in TEST_HARNESSES else "cli-tool" if dev else "external-library"
                found.append({"key": f"npm:{name}@{version or 'unresolved'}", "ecosystem": "npm", "name": name,
                              "kind": kind, "version": version, "license": license_of(entry.get("license")),
                              "path": path, "usedBy": [repo.name],
                              "interface": {"language": "javascript", "runtime": "node" if dev else "browser"}})
    return found


def python(repo):
    found = []
    for path in repo.paths:
        if PurePosixPath(path).name != "requirements.txt":
            continue
        for line in repo.read(path).decode("utf-8", errors="replace").splitlines():
            entry = line.partition("#")[0].strip()
            match = REQUIREMENT.match(entry) if entry and not entry.startswith("-") else None
            if not match:
                continue
            name, version = match[1], match[2]
            found.append({"key": f"pypi:{name.lower()}@{version or 'unresolved'}", "ecosystem": "pypi", "name": name,
                          "kind": "external-library", "version": version, "license": "UNKNOWN", "path": path,
                          "usedBy": [repo.name], "interface": {"language": "python", "runtime": "cpython"}})
    return found


def consumer(repo, parts):
    """Unité qui consomme : le jeu (`src/games/<jeu>`) ou le dossier de second niveau (`apps/web`, `packages/x`)."""
    if parts[:2] == ("src", "games") and len(parts) > 3:
        return f"{repo.name}/{parts[2]}"
    if parts[0] == "src" and len(parts) > 3:
        return f"{repo.name}/{parts[1]}/{parts[2]}"
    return f"{repo.name}/{parts[0]}/{parts[1]}" if len(parts) > 2 else None


def local_modules(repo):
    """Modules d'un monorepo (`src/engines/<x>`, `packages/<x>`) et unités qui les importent, par chemin relatif ou
    par le nom du paquet d'espace de travail (`@scope/x`)."""
    modules = {}
    for path in repo.paths:
        parts = PurePosixPath(path).parts
        for root in LOCAL_ROOTS:
            if len(parts) > len(root) + 1 and parts[:len(root)] == root:
                modules.setdefault("/".join(parts[:len(root) + 1]), parts[len(root)])
    if not modules:
        return []
    repo_license = (repo.json("package.json") or {}).get("license")
    patterns, licenses = {}, {}
    for module in modules:
        manifest = repo.json(f"{module}/package.json") or {}
        relative = module.split("/", 1)[-1] if module.startswith("src/") else module
        names = [re.escape(relative) + r"(?:/[^'\"]*)?"]
        if isinstance(manifest.get("name"), str):
            names.append(re.escape(manifest["name"]) + r"(?:/[^'\"]*)?")
        alternatives = "|".join([r"[^'\"]*\b" + names[0]] + names[1:])
        patterns[module] = re.compile(r"""(?:from|import)\s*\(?\s*['"](?:""" + alternatives + r""")['"]""")
        licenses[module] = license_of(manifest.get("license") or repo_license)
    users = {module: set() for module in modules}
    for path in repo.paths:
        parts = PurePosixPath(path).parts
        if not path.endswith(SOURCE_SUFFIXES) or "node_modules" in parts:
            continue
        unit = consumer(repo, parts)
        if unit is None:
            continue
        text = None
        for module, pattern in patterns.items():
            if path.startswith(module + "/"):
                continue
            text = repo.read(path).decode("utf-8", errors="replace") if text is None else text
            if pattern.search(text):
                users[module].add(unit)
    return [{"key": f"local:{repo.name}:{module}", "ecosystem": "local", "name": name, "kind": "game-local-module",
             "version": None, "license": licenses[module], "path": module, "usedBy": sorted(users[module]),
             "interface": {"language": "typescript", "runtime": "browser"}, "commitSha": repo.commit}
            for module, name in sorted(modules.items())]


ADAPTERS = (npm, python, local_modules)


def observe(repo):
    seen = {}
    for adapter in ADAPTERS:
        for row in adapter(repo):
            previous = seen.get(row["key"])
            if previous:
                previous["usedBy"] = sorted(set(previous["usedBy"]) | set(row["usedBy"]))
            else:
                seen[row["key"]] = row
    return [seen[key] for key in sorted(seen)]


def slug(text):
    return re.sub(r"-+", "-", re.sub(r"[^A-Z0-9]+", "-", text.upper())).strip("-") or "X"


def allocate(ids, key, prefix):
    if key in ids:
        return ids[key]
    taken = {value for value in ids.values() if value.startswith(prefix + "-")}
    number = 1
    while f"{prefix}-{number:03d}" in taken:
        number += 1
    ids[key] = f"{prefix}-{number:03d}"
    return ids[key]


def build(observations, ids, existing):
    """Catalogue depuis l'union des observations ; les champs tenus par d'autres (décision, qualité, specs,
    capacités) d'une fiche existante sont conservés."""
    by_key = {}
    for repo, state in sorted(observations.items()):
        for row in state["blocks"]:
            entry = by_key.setdefault(row["key"], {"row": row, "usedBy": set(), "observedIn": []})
            entry["usedBy"].update(row["usedBy"])
            entry["observedIn"].append({"repo": repo, "commitSha": state["commitSha"], "path": row["path"]})
    records = {}
    for key, entry in sorted(by_key.items()):
        row = entry["row"]
        if row["ecosystem"] == "local":
            prefix = f"BB-{slug(entry['observedIn'][0]['repo'])}-{slug(row['name'])}"
        else:
            prefix = f"BB-{slug(row['ecosystem'])}-{slug(row['name'])}"
        block_id = allocate(ids, key, prefix)
        origin = {"repositoryUrl": None, "licenseSpdx": row["license"], "commitSha": row.get("commitSha"),
                  "version": row["version"]}
        if row["ecosystem"] == "local":
            origin |= {"repo": entry["observedIn"][0]["repo"], "path": row["path"]}
        previous = existing.get(block_id) or {}
        record = {
            "schemaVersion": "1.0", "id": block_id, "name": row["name"], "kind": row["kind"], "origin": origin,
            "capabilities": previous.get("capabilities", []), "interfaces": [row["interface"]],
            "specIds": previous.get("specIds", []), "usedBy": sorted(entry["usedBy"]),
            "quality": previous.get("quality", {"status": "discovered", "sbomRef": None, "securityReportRef": None}),
            "decision": previous.get("decision", {"status": "pending", "rationale": None}),
            "provenance": previous.get("provenance", {"discoveredBy": DISCOVERED_BY, "verifiedAt": None}),
            "discovery": {"key": key, "ecosystem": row["ecosystem"]},
            "observedIn": sorted(entry["observedIn"], key=lambda o: (o["repo"], o["path"])),
        }
        records[block_id] = record
    return records


def discover(blocks, sources_file, clones, dry_run):
    try:
        entries = parse_json(Path(sources_file).read_bytes())["sources"]
        authorized = sorted(str(entry["name"]) for entry in entries)
        declared = {str(entry["name"]): Path(copy["path"]).expanduser() for entry in entries
                    for copy in entry.get("copies") or [] if copy.get("provider") == "local" and copy.get("path")}
    except (KeyError, TypeError) as exc:
        raise InvalidJSON(f"Liste des dépôts autorisés invalide : {sources_file}") from exc
    state_path, ids_path, catalog = blocks / "discovery.json", blocks / "ids.json", blocks / "catalog"
    state = read_json(state_path) if state_path.is_file() else {}
    ids = read_json(ids_path) if ids_path.is_file() else {}
    clones = Path(clones).expanduser()
    existing_dirs = {entry.name.casefold(): entry for entry in clones.iterdir()} if clones.is_dir() else {}
    exceptions, scanned, skipped, observations = [], [], [], {}
    for name in authorized:
        directory = declared.get(name) or existing_dirs.get(name.casefold())
        if directory is None or not (directory / ".git").exists():
            exceptions.append({"repo": name, "reason": "copie-locale-absente"})
            if name in state:
                observations[name] = state[name]
            continue
        head = subprocess.run(["git", "-C", str(directory), "rev-parse", "--verify", "HEAD^{commit}"],
                              capture_output=True, text=True)
        if head.returncode:
            exceptions.append({"repo": name, "reason": "git-illisible"})
            continue
        commit = head.stdout.strip()
        if state.get(name, {}).get("commitSha") == commit:
            skipped.append(name)
            observations[name] = state[name]
            continue
        observations[name] = {"commitSha": commit, "blocks": observe(Repo(name, directory, commit))}
        scanned.append(name)
    existing = {}
    if catalog.is_dir():
        for path in sorted(catalog.glob("*.json")):
            record = read_json(path)
            existing[record.get("id")] = record
    records = build(observations, ids, existing)
    unknown = sorted(record["id"] for record in records.values() if record["origin"]["licenseSpdx"] == "UNKNOWN")
    if not dry_run:
        catalog.mkdir(parents=True, exist_ok=True)
        for block_id, record in records.items():
            target = catalog / f"{block_id}.json"
            if not target.is_file() or target.read_text(encoding="utf-8") != json_text(record):
                write_json(target, record)
        for path, value in ((ids_path, dict(sorted(ids.items()))), (state_path, dict(sorted(observations.items())))):
            if not path.is_file() or path.read_text(encoding="utf-8") != json_text(value):
                write_json(path, value)
    return {"dryRun": dry_run, "repos": authorized, "scanned": scanned, "skipped": skipped,
            "exceptions": exceptions, "blocks": len(records), "licenseUnknown": unknown}


def inspect(records, block_id):
    if block_id not in records:
        raise InvalidJSON(f"Brique absente du catalogue : {block_id}.")
    return {"block": records[block_id][1]}


def usages(records, block_id):
    block = inspect(records, block_id)["block"]
    return {"id": block_id, "usedBy": block["usedBy"], "observedIn": block.get("observedIn", [])}


def impact(records, block_id, to_version):
    block = inspect(records, block_id)["block"]
    key = block.get("discovery", {})
    if key.get("ecosystem") in (None, "local"):
        impacted = block["usedBy"]
    else:
        same = [b for _, b in records.values() if b["name"] == block["name"]
                and b.get("discovery", {}).get("ecosystem") == key["ecosystem"]]
        impacted = sorted({user for b in same if b["origin"].get("version") != to_version for user in b["usedBy"]})
    return {"id": block_id, "toVersion": to_version, "impacted": impacted}
