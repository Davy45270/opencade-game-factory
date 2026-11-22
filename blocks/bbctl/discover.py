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
import tomllib
import re
import subprocess
from pathlib import Path, PurePosixPath

from tools.core.catalog import InvalidJSON, json_text, parse_json, read_json, write_json

from .registry import spdx_ids
from .trace import releases

DISCOVERED_BY = "bbctl discover"
TEST_HARNESSES = {"vitest", "jest", "mocha", "playwright", "@playwright/test", "cypress", "ava", "uvu",
                  "@vitest/coverage-v8", "@vitest/browser", "c8", "nyc"}
LOCAL_ROOTS = (("src", "engines"), ("packages",))
SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
IMPORT = re.compile(r"""(?:^|[;\s])(?:import|export)\s[^'";]*?\bfrom\s*['"]([^'"]+)['"]|\bimport\s*\(?\s*['"]([^'"]+)['"]""")
EXPORT_DECL = re.compile(r"(?m)^\s*export\s+(?:declare\s+)?(?:default\s+)?(?:abstract\s+)?(?:async\s+)?"
                         r"(?:function\*?|const|let|var|class|type|interface|enum)\s+([A-Za-z_$][\w$]*)")
EXPORT_LIST = re.compile(r"(?m)^\s*export\s+(?:type\s+)?\{([^}]*)\}")
EXPORT_STAR = re.compile(r"""(?m)^\s*export\s+\*\s+from\s+['"](\.[^'"]*)['"]""")
TEST_FILE = re.compile(r"(?:^|/)(?:__tests__|tests?)/|\.(?:test|spec)\.[cm]?[jt]sx?$")
WORKFLOW_DIRS = {(".woodpecker",): "woodpecker", (".github", "workflows"): "github-actions",
                 (".forgejo", "workflows"): "forgejo-actions"}
SCRIPT_RUNTIMES = {".sh": ("shell", "posix-sh"), ".bash": ("shell", "bash"), ".py": ("python", "cpython"),
                   ".mjs": ("javascript", "node"), ".js": ("javascript", "node"), ".cjs": ("javascript", "node"),
                   ".ts": ("typescript", "node")}
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


def pnpm_versions(text, importer):
    """Versions résolues d'un importeur de pnpm-lock.yaml (v6 à v9), sans dépendance YAML : `importers:` → `<importeur>:`
    → `dependencies|devDependencies|optionalDependencies:` → `<nom>:` → `version: x(suffixe de pairs)`."""
    versions, section, depth, name = {}, None, None, None
    in_importers = current = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, _, value = line.strip().partition(":")
        key, value = key.strip().strip("'\""), value.strip().strip("'\"")
        if indent == 0:
            in_importers, current = key == "importers", False
            continue
        if not in_importers:
            continue
        if indent == 2:
            current, section = key == importer, None
        elif current and indent == 4:
            section = key if key in ("dependencies", "devDependencies", "optionalDependencies") else None
        elif current and section and indent == 6:
            name = key
        elif current and section and indent == 8 and key == "version" and name:
            versions[name] = re.split(r"[(\s]", value, maxsplit=1)[0] or None
    return versions


def npm(repo):
    """package.json à toute profondeur (hors node_modules) ; versions et licences du package-lock.json voisin, sinon
    versions du pnpm-lock.yaml (licence inconnue : pnpm ne la porte pas)."""
    found = []
    for path in repo.paths:
        pure = PurePosixPath(path)
        if pure.name != "package.json" or "node_modules" in pure.parts:
            continue
        manifest = repo.json(path)
        if not isinstance(manifest, dict):
            continue
        lock = repo.json(str(pure.with_name("package-lock.json"))) or repo.json("package-lock.json") or {}
        packages = lock.get("packages") if isinstance(lock.get("packages"), dict) else {}
        if not packages:
            for candidate in (str(pure.with_name("pnpm-lock.yaml")), "pnpm-lock.yaml"):
                if candidate in repo.paths:
                    importer = str(pure.parent) if candidate == "pnpm-lock.yaml" else "."
                    text = repo.read(candidate).decode("utf-8", errors="replace")
                    packages = {f"node_modules/{n}": {"version": v}
                                for n, v in pnpm_versions(text, importer).items()}
                    break
        linked = {key.removeprefix("node_modules/") for key, entry in packages.items()
                  if isinstance(entry, dict) and entry.get("link")}
        for section, dev in (("dependencies", False), ("devDependencies", True)):
            for name in sorted(manifest.get(section) or {}):
                if not isinstance(name, str) or name in linked:
                    continue                            # paquet de l'espace de travail : c'est un module local
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


def toml(repo, path):
    try:
        return tomllib.loads(repo.read(path).decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeError):
        return None


def external(key_ecosystem, name, version, path, repo, language, runtime, kind="external-library"):
    return {"key": f"{key_ecosystem}:{name if key_ecosystem != 'pypi' else name.lower()}@{version or 'unresolved'}",
            "ecosystem": key_ecosystem, "name": name, "kind": kind, "version": version, "license": "UNKNOWN",
            "path": path, "usedBy": [repo.name], "interface": {"language": language, "runtime": runtime}}


def pyproject(repo):
    found = []
    for path in repo.paths:
        if PurePosixPath(path).name != "pyproject.toml":
            continue
        data = toml(repo, path) or {}
        for entry in (data.get("project") or {}).get("dependencies") or []:
            match = REQUIREMENT.match(entry.strip()) if isinstance(entry, str) else None
            if match:
                found.append(external("pypi", match[1], match[2], path, repo, "python", "cpython"))
    return found


def cargo(repo):
    found = []
    for path in repo.paths:
        if PurePosixPath(path).name != "Cargo.toml":
            continue
        for name in sorted((toml(repo, path) or {}).get("dependencies") or {}):
            found.append(external("cargo", name, None, path, repo, "rust", "native"))
    return found


def gomod(repo):
    found = []
    for path in repo.paths:
        if PurePosixPath(path).name != "go.mod":
            continue
        block = False
        for line in repo.read(path).decode("utf-8", errors="replace").splitlines():
            line = line.split("//")[0].strip()
            if line.startswith("require ("):
                block = True
                continue
            if block and line == ")":
                block = False
                continue
            parts = line.removeprefix("require ").split() if (block or line.startswith("require ")) else []
            if len(parts) >= 2:
                found.append(external("go", parts[0], parts[1], path, repo, "go", "native"))
    return found


def dockerfile(repo):
    found = []
    for path in repo.paths:
        if not PurePosixPath(path).name.startswith("Dockerfile"):
            continue
        stages = set()
        for line in repo.read(path).decode("utf-8", errors="replace").splitlines():
            words = line.split()
            if len(words) >= 2 and words[0].upper() == "FROM":
                image = next((w for w in words[1:] if not w.startswith("--")), "")
                if len(words) >= 4 and words[-2].upper() == "AS":
                    stages.add(words[-1].lower())
                if not image or image.lower() in stages or "$" in image:
                    continue
                name, _, tag = image.partition("@")[0].rpartition(":") if ":" in image.split("/")[-1] else (image, "", "")
                found.append(external("docker", name or image, tag or None, path, repo, "container", "oci", "service"))
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
    analyses = {module: analyse(repo, module, modules) for module in modules}
    for path in repo.paths:                                    # usages par import RELATIF résolu (« ../save »)
        parts = PurePosixPath(path).parts
        if not path.endswith(SOURCE_SUFFIXES) or "node_modules" in parts:
            continue
        unit = consumer(repo, parts)
        if unit is None:
            continue
        for target in relative_targets(repo, path, modules):
            if not path.startswith(target + "/"):
                users[target].add(unit)
    return [{"key": f"local:{repo.name}:{module}", "ecosystem": "local", "name": name, "kind": "game-local-module",
             "version": None, "license": licenses[module], "path": module, "usedBy": sorted(users[module]),
             "interface": {"language": "typescript", "runtime": "browser", "exports": analyses[module]["exports"]},
             "commitSha": repo.commit, "analysis": {**analyses[module], "maturity": maturity(analyses[module],
                                                                                              users[module])}}
            for module, name in sorted(modules.items())]


def specifiers(text):
    return [a or b for a, b in IMPORT.findall(text)]


def owner(path, modules):
    return next((m for m in modules if path == m or path.startswith(m + "/")), None)


def relative_targets(repo, path, modules):
    """Modules locaux atteints par les imports relatifs d'un fichier."""
    text = repo.read(path).decode("utf-8", errors="replace")
    out = set()
    for spec in specifiers(text):
        if spec.startswith("."):
            target = owner(os.path.normpath(str(PurePosixPath(path).parent / spec)), modules)
            if target:
                out.add(target)
    return out


def package_of(spec):
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") else parts[0]


def entry_files(repo, module, sources):
    manifest = repo.json(f"{module}/package.json") or {}
    declared = [manifest.get(k) for k in ("types", "module", "main")]
    exports = manifest.get("exports")
    if isinstance(exports, str):
        declared.insert(0, exports)
    elif isinstance(exports, dict) and isinstance(exports.get("."), str):
        declared.insert(0, exports["."])
    for d in declared:
        if isinstance(d, str):
            p = os.path.normpath(f"{module}/{d}")
            if p in sources:
                return [p]
    index = [p for p in sources if PurePosixPath(p).parent == PurePosixPath(module) and PurePosixPath(p).stem == "index"]
    return index[:1] or sources


def exported_names(repo, path, sources, seen):
    if path in seen or path not in repo.paths:
        return set()
    seen.add(path)
    text = repo.read(path).decode("utf-8", errors="replace")
    names = set(EXPORT_DECL.findall(text))
    for group in EXPORT_LIST.findall(text):
        for item in group.split(","):
            item = item.strip().removeprefix("type ").strip()
            if item:
                names.add(item.split(" as ")[-1].strip())
    for spec in EXPORT_STAR.findall(text):
        base = os.path.normpath(str(PurePosixPath(path).parent / spec))
        target = next((p for p in sources if p == base or os.path.splitext(p)[0] in (base, base + "/index")), None)
        if target:
            names |= exported_names(repo, target, sources, seen)
    return {n for n in names if n and n != "default" and re.fullmatch(r"[A-Za-z_$][\w$]*", n)}


def analyse(repo, module, modules):
    """BB-001 § 3 : exports publics (fichier d'entrée du module), imports (paquets et autres modules locaux), tests du
    module, mainteneurs DÉCLARÉS par son package.json ; la couverture n'est pas mesurée ici : null."""
    files = [p for p in repo.paths if p.startswith(module + "/") and "node_modules" not in PurePosixPath(p).parts]
    sources = [p for p in files if p.endswith(SOURCE_SUFFIXES) and not TEST_FILE.search(p[len(module):])]
    tests = sorted(p for p in files if p.endswith(SOURCE_SUFFIXES) and TEST_FILE.search(p[len(module):]))
    exports, seen = set(), set()
    for entry in entry_files(repo, module, sources):
        exports |= exported_names(repo, entry, sources, seen)
    imports = set()
    for path in sources:
        for spec in specifiers(repo.read(path).decode("utf-8", errors="replace")):
            if spec.startswith("."):
                target = owner(os.path.normpath(str(PurePosixPath(path).parent / spec)), modules)
                if target and target != module:
                    imports.add(f"local:{repo.name}:{target}")
            elif spec:
                imports.add(package_of(spec))
    manifest = repo.json(f"{module}/package.json") or {}
    people = []
    for person in [manifest.get("author")] + list(manifest.get("maintainers") or []):
        name = person.get("name") if isinstance(person, dict) else person
        if isinstance(name, str) and name.strip():
            people.append(name.strip())
    return {"exports": sorted(exports), "imports": sorted(imports), "tests": tests,
            "maintainers": people or None, "coverage": None}


def maturity(analysis, users):
    if not users:
        return "unused"
    return "tested" if analysis["tests"] else "untested"


def kebab(name):
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def workflows_and_scripts(repo):
    """BB-001 § 3 : workflows CI et scripts du dépôt (inventaire de découverte ; le gate ne les compte pas)."""
    found = []
    for path in repo.paths:
        pure = PurePosixPath(path)
        runtime = WORKFLOW_DIRS.get(pure.parts[:-1])
        if runtime and pure.suffix in (".yml", ".yaml"):
            found.append({"key": f"workflow:{repo.name}:{path}", "ecosystem": "workflow", "name": pure.stem,
                          "kind": "workflow", "version": None, "license": "UNKNOWN", "path": path,
                          "usedBy": [repo.name], "interface": {"language": "yaml", "runtime": runtime},
                          "commitSha": repo.commit})
        elif len(pure.parts) == 2 and pure.parts[0] == "scripts" and pure.suffix in SCRIPT_RUNTIMES:
            language, rt = SCRIPT_RUNTIMES[pure.suffix]
            found.append({"key": f"script:{repo.name}:{path}", "ecosystem": "script", "name": pure.name,
                          "kind": "cli-tool", "version": None, "license": "UNKNOWN", "path": path,
                          "usedBy": [repo.name], "interface": {"language": language, "runtime": rt},
                          "commitSha": repo.commit})
    return found


ADAPTERS = (npm, python, pyproject, cargo, gomod, dockerfile, local_modules)
LOCAL_ECOSYSTEMS = ("local", "workflow", "script")


def observe(repo, inventory=False):
    """`inventory` (discover) ajoute workflows et scripts ; le gate « reuse before build » ne les compte pas."""
    seen = {}
    for adapter in ADAPTERS + ((workflows_and_scripts,) if inventory else ()):
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
        if row["ecosystem"] in LOCAL_ECOSYSTEMS:
            prefix = f"BB-{slug(entry['observedIn'][0]['repo'])}-{slug(row['name'])}"
        else:
            prefix = f"BB-{slug(row['ecosystem'])}-{slug(row['name'])}"
        block_id = allocate(ids, key, prefix)
        origin = {"repositoryUrl": None, "licenseSpdx": row["license"], "commitSha": row.get("commitSha"),
                  "version": row["version"]}
        if row["ecosystem"] in LOCAL_ECOSYSTEMS:
            origin |= {"repo": entry["observedIn"][0]["repo"], "path": row["path"]}
        previous = existing.get(block_id) or {}
        derived = sorted({kebab(n) for n in (row.get("analysis") or {}).get("exports", [])} - {""})
        record = {
            "schemaVersion": "1.0", "id": block_id, "name": row["name"], "kind": row["kind"], "origin": origin,
            "capabilities": previous.get("capabilities") or derived, "interfaces": [row["interface"]],
            "specIds": previous.get("specIds", []), "usedBy": sorted(entry["usedBy"]),
            "quality": previous.get("quality", {"status": "discovered", "sbomRef": None, "securityReportRef": None}),
            "decision": previous.get("decision", {"status": "pending", "rationale": None}),
            "provenance": previous.get("provenance", {"discoveredBy": DISCOVERED_BY, "verifiedAt": None}),
            "discovery": {"key": key, "ecosystem": row["ecosystem"]},
            "observedIn": sorted(entry["observedIn"], key=lambda o: (o["repo"], o["path"])),
        }
        if row.get("analysis") is not None:
            record["analysis"] = row["analysis"]
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
            # Commit inchangé : briques non relues, mais les releases (tags) peuvent avoir bougé — relevées à chaque passage.
            observations[name] = {**state[name], "releases": releases(directory, commit)}
            continue
        observations[name] = {"commitSha": commit, "blocks": observe(Repo(name, directory, commit), inventory=True),
                              "releases": releases(directory, commit)}          # E179 : tags atteignables
        scanned.append(name)
    existing = {}
    if catalog.is_dir():
        for path in sorted(catalog.glob("*.json")):
            record = read_json(path)
            existing[record.get("id")] = record
    records = build(observations, ids, existing)
    for block_id, record in existing.items():                 # plus observée : gardée (jamais recyclée), plus utilisée
        if block_id in records or (record.get("provenance") or {}).get("discoveredBy") != DISCOVERED_BY:
            continue
        records[block_id] = {**record, "usedBy": [], "observedIn": []}
    unknown = sorted(record["id"] for record in records.values() if record["origin"]["licenseSpdx"] == "UNKNOWN")
    # ARCH-001 AT-04 : composant implémenté (observé dans un dépôt autorisé) sans fiche au catalogue AVANT ce passage.
    # Avec --dry-run, c'est la liste de ce qu'il reste à enregistrer ; sans, ce que ce passage vient d'enregistrer.
    unregistered = sorted(block_id for block_id in records if block_id not in existing)
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
            "exceptions": exceptions, "blocks": len(records), "licenseUnknown": unknown, "unregistered": unregistered}


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
