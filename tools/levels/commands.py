"""`assetctl level …` (EXT-002 § 6) : discover, import, search, inspect, derive, generate, validate, simulate, usages,
publish.

Chaque commande rend `operationId`, `status`, `artifacts[]` et `diagnostics[]`, en JSON, sans dialogue. Codes : la
table commune (docs/ARCHITECTURE.md § Codes de retour) — référence absente et validation échouée → 1, droits et
licences → 3, infrastructure → 4, version publiée modifiée → 5 ; `inconclusive` rend 1, jamais 0.
"""

import argparse
import ast
import hashlib
import json
import re
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from tools.core.catalog import json_text, read_json, write_json
from tools.discovery.scan import directory_lock
from tools.levels import LevelExit, enabled, status_code
from tools.levels.formats import (CODE_EXTENSIONS, LEVEL_EXTENSIONS, OTHER_EXTENSIONS, SCANNED, TILESET_EXTENSIONS,
                                  Unsupported, parse, parse_tileset, semantics)
from tools.levels.generate import GENERATORS, TRANSFORMS
from tools.levels.validators import VALIDATORS, Budget, validate as run_validators

SUBCOMMANDS = ("discover", "import", "search", "inspect", "derive", "generate", "validate", "simulate", "usages",
               "publish")
SKIPPED_DIRS = {".git", "node_modules", ".venv", "dist", "build", "__pycache__"}
KINDS = ("rpg", "dungeon", "platformer", "circuit", "puzzle")
AGENTS = {"platform-bot": "platformer", "dungeon-bot": "dungeon", "kart-bot": "circuit", "rpg-bot": "rpg"}
LEVEL_PATH_HINT = re.compile(r"(?i)(level|levels|map|maps|niveau|carte|stage|world|track|circuit|donjon|dungeon)")
REFERENCE = re.compile(r"""["']([^"'\n]{1,200}\.(?:tmx|tmj|ldtk|ldtkl|json))["']""")
DYNAMIC = re.compile(r"""(`[^`\n]*\$\{[^`\n]*\.(?:tmx|tmj|ldtk|json)[^`\n]*`|["'][^"'\n]*["']\s*\+\s*[\w.]+\s*\+\s*["']"""
                     r"""[^"'\n]*\.(?:tmx|tmj|ldtk|json)["']|\.\.\s*["'][^"'\n]*\.(?:tmx|tmj|ldtk|json)["'])""")
GENERATOR = re.compile(r"\b((?:ROT\.Map\.\w+)|(?:generate\w*|bsp\w*|cellular\w*|drunkard\w*|wfc\w*|"
                       r"\w*Generator))\s*\(([^()\n]{0,200})\)")


def configure(parser, caller_path):
    sub = parser.add_subparsers(dest="level_command", required=True)
    for name in SUBCOMMANDS:
        command = sub.add_parser(name, allow_abbrev=False)
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        command.add_argument("--format", choices=("json",), default=None)
        command.add_argument("--dry-run", action="store_true")
        if name in {"inspect", "derive", "validate", "simulate", "usages", "publish"}:
            command.add_argument("level_id")
        if name in {"discover", "usages"}:
            command.add_argument("--scope", type=caller_path, required=name == "discover")
        if name == "import":
            command.add_argument("--source", choices=("local", "archive", "github", "forgejo"), required=True)
            command.add_argument("--repo")
            command.add_argument("--ref")
            command.add_argument("--path", action="append", default=[])
            command.add_argument("--archive", type=caller_path)
            command.add_argument("--game")
            command.add_argument("--universe", default="unknown")
            command.add_argument("--kind", choices=KINDS)
            command.add_argument("--license", help="identifiant SPDX déclaré par la source")
            command.add_argument("--license-evidence", help="chemin du texte de licence dans la source")
            command.add_argument("--author")
            command.add_argument("--source-url")
        if name == "search":
            command.add_argument("--query", default="")
            command.add_argument("--type", choices=KINDS)
        if name in {"derive", "generate"}:
            command.add_argument("--constraints", type=caller_path, required=True)
            command.add_argument("--seed", type=int, required=True)
        if name == "generate":
            command.add_argument("--genre", choices=KINDS, required=True)
            command.add_argument("--game", default="generated")
        if name in {"validate", "simulate", "publish"}:
            command.add_argument("--profile", type=caller_path)
        if name == "simulate":
            command.add_argument("--agent", choices=sorted(AGENTS), required=True)
        if name == "publish":
            command.add_argument("--version", required=True)


# --- Stockage ----------------------------------------------------------------------------------------------------

def _dir(root):
    return Path(root) / "catalog" / "levels"


def _load_all(root):
    folder = _dir(root)
    return {p.stem: read_json(p) for p in sorted(folder.glob("level-*.json"))} if folder.is_dir() else {}


def _known_assets(root):
    known = {}
    for path in sorted((Path(root) / "catalog" / "assets").glob("*.json")):
        asset = read_json(path)
        versions = {str(v.get("version")) for v in asset.get("versions", [])} | {str(asset.get("version", 1))}
        known[asset["id"]] = versions
    return known


def _write(path, record):
    """Toute fiche écrite respecte schemas/level.schema.json (contrat de la spec) ; sinon rien n'est écrit."""
    from tools.core.catalog import InvalidJSON
    from tools.core.schemas import schemas

    error = next(schemas().validator("level").iter_errors(record), None)
    if error is not None:
        raise InvalidJSON(f"Fiche de niveau {record.get('id')} invalide : {error.message}")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)


def _sha(value):
    raw = value if isinstance(value, bytes) else json_text(value).encode()
    return hashlib.sha256(raw).hexdigest()


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "x"


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _envelope(code, status, artifacts=(), diagnostics=(), **extra):
    return code, {"ok": code == LevelExit.OK, "operationId": uuid.uuid4().hex, "status": status,
                  "artifacts": list(artifacts), "diagnostics": list(diagnostics), **extra}


def _content(level):
    return {k: v for k, v in level.items() if k not in ("losses", "diagnostics")}


def _guess_kind(level):
    sem = semantics(level)
    types = {e["type"] for e in sem["entities"]}
    declared = {p["name"]: p.get("value") for p in level.get("properties", []) if isinstance(p, dict)}
    if declared.get("kind") in KINDS:
        return declared["kind"]
    if sem["track"]:
        return "circuit"
    if types & {"key", "door", "switch", "gate"}:
        return "dungeon"
    if types & {"moving-platform", "hazard", "spike"} or "gravity" in declared:
        return "platformer"
    return "rpg"


def _mechanics(level):
    names = {"key": "keys", "door": "keys", "switch": "switches", "gate": "switches", "boss": "boss",
             "quest": "quests", "checkpoint": "checkpoints", "moving-platform": "moving-platforms",
             "transition": "transitions"}
    return sorted({names[e["type"]] for e in semantics(level)["entities"] if e["type"] in names})


# --- Sources : dépôt git (lecture seule) ou dossier ---------------------------------------------------------------

class Source:
    """Lit un dépôt sans jamais l'écrire : `git show <commit>:<chemin>` si c'est un dépôt git, sinon le disque."""

    def __init__(self, path, ref=None):
        self.path = Path(path)
        # Un clone (`.git`) ou un miroir nu (`HEAD` + `objects/`, ceux de scan-repos) se lisent tous deux par git ;
        # un miroir nu lu comme un dossier ordinaire ne montrerait aucun fichier et passerait pour vide.
        self.git = (self.path / ".git").exists() or ((self.path / "HEAD").is_file() and (self.path / "objects").is_dir())
        self.commit = "unversioned"
        if self.git:
            self.commit = self._git("rev-parse", "--verify", f"{ref or 'HEAD'}^{{commit}}").decode().strip()

    def _git(self, *args):
        return subprocess.run(["git", "-C", str(self.path), *args], check=True, capture_output=True).stdout

    def files(self):
        if self.git:
            names = self._git("ls-tree", "-r", "--name-only", "-z", self.commit).decode().split("\0")
            return sorted(n for n in names if n and not set(PurePosixPath(n).parts) & SKIPPED_DIRS)
        return sorted(p.relative_to(self.path).as_posix() for p in self.path.rglob("*")
                      if p.is_file() and not set(p.relative_to(self.path).parts) & SKIPPED_DIRS)

    def read(self, name):
        try:
            if self.git:
                return self._git("show", f"{self.commit}:{name}")
            return (self.path / name).read_bytes()
        except (subprocess.CalledProcessError, OSError):
            return None

    def reader(self, base):
        folder = PurePosixPath(base).parent

        def read(relative):
            target = PurePosixPath(*(folder / relative).parts)
            parts = []
            for part in target.parts:
                if part == "..":
                    if not parts:
                        return None
                    parts.pop()
                elif part != ".":
                    parts.append(part)
            return self.read("/".join(parts))
        return read


def _fingerprint(path):
    root = Path(path)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and ".git" not in p.relative_to(root).parts}


def _code_scan(name, text):
    """Références de niveaux, générateurs et constructions dynamiques d'un fichier de code — sans l'exécuter."""
    references, generators, dynamic = set(), [], []
    if name.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        inside = {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for part in node.values} \
            if tree else set()
        for node in ast.walk(tree) if tree else ():
            if id(node) in inside:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and \
                    re.search(r"\.(tmx|tmj|ldtk|ldtkl|json)$", node.value):
                references.add(node.value)
            elif isinstance(node, ast.JoinedStr) and re.search(r"\.(tmx|tmj|ldtk|json)", ast.unparse(node)):
                dynamic.append({"line": node.lineno, "expression": ast.unparse(node)[:200]})
            elif isinstance(node, ast.Call):
                func = ast.unparse(node.func)
                if re.fullmatch(r"(?i).*(generate\w*|bsp\w*|cellular\w*|drunkard\w*|wfc\w*|\w*generator)", func):
                    params = [ast.literal_eval(a) if isinstance(a, ast.Constant) else ast.unparse(a) for a in node.args]
                    generators.append({"line": node.lineno, "call": func, "params": params})
    else:
        for line_no, line in enumerate(text.splitlines(), start=1):
            for match in REFERENCE.finditer(line):
                references.add(match.group(1))
            for match in DYNAMIC.finditer(line):
                dynamic.append({"line": line_no, "expression": match.group(0)[:200]})
            for match in GENERATOR.finditer(line):
                generators.append({"line": line_no, "call": match.group(1),
                                   "params": [p.strip() for p in match.group(2).split(",") if p.strip()]})
    return sorted(references), generators, dynamic


def _game_for(repo, name):
    games = repo.get("games") or {}
    best = max((prefix for prefix in games if name == prefix or name.startswith(prefix.rstrip("/") + "/")),
               key=len, default=None)
    return games[best] if best else repo.get("game", repo["name"])


def discover(root, args):
    scope = read_json(args.scope)
    base = Path(args.scope).parent
    report, totals, diagnostics = [], {"detected": 0, "inventoried": 0, "exceptions": 0, "ignored": 0}, []
    for repo in scope.get("repos", []):
        path = (base / repo["path"]).resolve()
        if not path.is_dir():
            diagnostics.append({"code": "repo-missing", "severity": "error", "message": f"dépôt absent : {repo['name']}"})
            continue
        before = _fingerprint(path)
        source = Source(path, repo.get("ref"))
        rows = {"name": repo["name"], "commit": source.commit, "levels": [], "tilesets": [], "references": [],
                "generators": [], "dynamic": [], "exceptions": [], "ignored": []}
        for name in source.files():
            suffix = PurePosixPath(name).suffix.lower()
            if suffix not in SCANNED:
                continue
            totals["detected"] += 1
            raw = source.read(name)
            game = _game_for(repo, name)
            if suffix in CODE_EXTENSIONS:
                refs, gens, dyn = _code_scan(name, raw.decode("utf-8", errors="replace"))
                rows["references"] += [{"file": name, "game": game, "target": r} for r in refs
                                       if not r.endswith(".json") or LEVEL_PATH_HINT.search(r)]
                rows["generators"] += [{"file": name, "game": game, **g} for g in gens]
                rows["dynamic"] += [{"file": name, "game": game, "status": "unresolved", **d} for d in dyn]
                if refs or gens or dyn:
                    totals["inventoried"] += 1
                else:
                    rows["ignored"].append({"file": name, "game": game, "reason": "code sans référence de niveau"})
                    totals["ignored"] += 1
                continue
            if suffix in TILESET_EXTENSIONS:
                try:
                    rows["tilesets"].append({"file": name, "game": game, **parse_tileset(raw, name)})
                    totals["inventoried"] += 1
                except (Unsupported, ValueError) as exc:
                    rows["exceptions"].append({"file": name, "game": game, "reason": str(exc)})
                    totals["exceptions"] += 1
                continue
            if suffix == ".blend":
                rows["exceptions"].append({"file": name, "game": game, "reason": "scène Blender : conversion 3D hors "
                                           "périmètre initial, inventoriée sans import"})
                totals["exceptions"] += 1
                continue
            try:
                levels = parse(name if suffix != ".xml" else name[:-4] + ".tmx", raw, source.reader(name))
            except (Unsupported, ValueError, KeyError, TypeError) as exc:
                if suffix == ".json" and not LEVEL_PATH_HINT.search(name):
                    rows["ignored"].append({"file": name, "game": game, "reason": "JSON sans structure de niveau"})
                    totals["ignored"] += 1
                else:
                    rows["exceptions"].append({"file": name, "game": game, "reason": str(exc) or type(exc).__name__})
                    totals["exceptions"] += 1
                continue
            for level in levels:
                sem = semantics(level)
                rows["levels"].append({"file": name, "game": game, "name": level["name"], "format": level["format"],
                                       "width": level["width"], "height": level["height"],
                                       "layers": [l["name"] for l in level["layers"]],
                                       "entities": sorted({e["type"] for e in sem["entities"]}),
                                       "triggers": sum(e["type"] == "trigger" for e in sem["entities"]),
                                       "checkpoints": sum(e["type"] == "checkpoint" for e in sem["entities"]),
                                       "transitions": sum(e["type"] == "transition" for e in sem["entities"]),
                                       "collisionCells": len(sem["solid"]),
                                       "tilesets": [t.get("source") or t.get("name") for t in level["tilesets"]],
                                       "sha256": _sha(raw), "structureSha256": _sha(_content(level)["layers"]),
                                       "diagnostics": level["diagnostics"]})
            totals["inventoried"] += 1
        by_sha = {}
        for row in rows["levels"]:
            by_sha.setdefault(row["structureSha256"], []).append(row["file"])
        rows["duplicates"] = [{"files": sorted(files), "kind": "structure-identique", "merged": False}
                              for files in by_sha.values() if len(files) > 1]
        rows["sourcesUnchanged"] = _fingerprint(path) == before
        report.append(rows)
    classified = totals["inventoried"] + totals["exceptions"] + totals["ignored"]
    coverage = {**totals, "classified": classified, "ratio": 1.0 if not totals["detected"] else
                round(classified / totals["detected"], 4)}
    unchanged = all(r["sourcesUnchanged"] for r in report)
    code = LevelExit.OK if coverage["ratio"] == 1.0 and unchanged and not diagnostics else LevelExit.VALIDATION_FAILED
    return _envelope(code, "ok" if code == LevelExit.OK else "failed", diagnostics=diagnostics, repos=report,
                     coverage=coverage, sourcesUnchanged=unchanged, dryRun=True)


# --- Import -------------------------------------------------------------------------------------------------------

def _license(source_read, declared, evidence, texts=None):
    from tools.external.licenses import LicenseEvaluator

    if not declared:
        return {"status": "unknown", "spdx": "unknown", "evidence": "aucune licence déclarée par la source"}
    if texts is None:
        content = source_read(evidence) if evidence else None
        texts = {evidence: content.decode("utf-8", errors="replace")} if content else {}
    return LicenseEvaluator().verify(declared, texts)


def import_levels(root, args):
    if args.source in {"github", "forgejo"}:
        return _envelope(LevelExit.INVALID_INPUT, "failed", diagnostics=[{
            "code": "remote-source", "severity": "error",
            "message": "import distant : cloner d'abord (scan-repos tient le miroir), puis --source local --ref <sha>"}])
    if args.source == "archive":
        return _import_archive(root, args)
    source = Source(args.repo, args.ref)
    files = args.path or [n for n in source.files() if PurePosixPath(n).suffix.lower() in LEVEL_EXTENSIONS]
    verdict = _license(source.read, args.license, args.license_evidence)
    provider = "local"
    repo_name = args.repo
    if source.git:
        remote = subprocess.run(["git", "-C", str(source.path), "config", "--get", "remote.origin.url"],
                                capture_output=True, text=True).stdout.strip()
        repo_name = re.sub(r"^(https?://)[^@/]+@", r"\1", remote) or source.path.name
    candidates = []
    for name in files:
        raw = source.read(name)
        if raw is None:
            continue
        try:
            levels = parse(name, raw, source.reader(name))
        except (Unsupported, ValueError, KeyError, TypeError):
            continue
        for level in levels:
            candidates.append((name, raw, level))
    return _store(root, args, candidates, {"provider": provider, "repo": repo_name, "commit": source.commit},
                  verdict)


def _import_archive(root, args):
    from tools.external.archive import inspect_archive, quarantine

    data = Path(args.archive).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    report = inspect_archive(args.archive)
    if not report["ok"]:
        place = None if args.dry_run else quarantine(root, args.archive, digest, {"problems": report["problems"]})
        return _envelope(LevelExit.INVALID_INPUT, "blocked", diagnostics=[{"code": "unsafe-archive", "severity": "error",
                                                                   "message": p} for p in report["problems"]],
                         quarantine=place)
    import zipfile

    candidates = []
    with zipfile.ZipFile(args.archive) as archive:
        names = {i.filename for i in archive.infolist() if not i.is_dir()}

        def reader(base):
            folder = PurePosixPath(base).parent

            def read(relative):
                target = (folder / relative).as_posix()
                return archive.read(target) if target in names and ".." not in PurePosixPath(target).parts else None
            return read
        for name in sorted(names):
            if PurePosixPath(name).suffix.lower() in LEVEL_EXTENSIONS:
                raw = archive.read(name)
                try:
                    levels = parse(name, raw, reader(name))
                except (Unsupported, ValueError, KeyError, TypeError):
                    continue
                candidates += [(name, raw, level) for level in levels]
    verdict = _license(None, args.license, None, report["texts"])
    return _store(root, args, candidates, {"provider": "archive", "repo": args.source_url or f"sha256:{digest}",
                                           "commit": digest}, verdict)


def _store(root, args, candidates, origin, verdict):
    existing = _load_all(root)
    from tools.core.schemas import schemas

    created, observed, unchanged, artifacts, diagnostics = [], [], [], [], []
    pending, originals = {}, []
    game = args.game or Path(str(origin["repo"])).name
    with directory_lock(Path(root) / "catalog") if not args.dry_run else _null():
        for name, raw, level in candidates:
            content = _content(level)
            content_sha = _sha(raw)
            key = {"provider": origin["provider"], "repo": origin["repo"], "commit": origin["commit"], "path": name,
                   "contentSha256": content_sha}
            match = next((r for r in existing.values() if r["origin"]["sourceRepo"] == origin["repo"]
                          and r["origin"]["sourcePath"] == name and r["content"]["name"] == level["name"]), None)
            if match and any({k: o.get(k) for k in key} == key for o in match["observations"]):
                unchanged.append(match["id"])
                continue
            if match and match["contentSha256"] == content_sha:
                match["observations"].append({**key, "observedAt": _now()})
                observed.append(match["id"])
                record = match
            elif match:
                diagnostics.append({"code": "source-changed", "severity": "warning", "message":
                                    f"{name} a changé depuis {match['origin']['sourceCommit']} : nouvelle version "
                                    "importée, les versions publiées restent immuables"})
                match.update(content=content, contentSha256=content_sha, losses=level["losses"],
                             validation={"structure": "pending", "solvability": "pending", "simulation": "pending"})
                match["origin"]["sourceCommit"] = origin["commit"]
                match["observations"].append({**key, "observedAt": _now()})
                observed.append(match["id"])
                record = match
            else:
                base = f"level-{_slug(game)}-{_slug(level['name'])}"
                level_id, n = base, 2
                while level_id in existing:
                    level_id, n = f"{base}-{n}", n + 1
                sem = semantics(level)
                record = {
                    "schemaVersion": "1.0.0", "id": level_id, "kind": args.kind or _guess_kind(level),
                    "name": level["name"],
                    "origin": {"game": game, "universe": args.universe, "sourceRepo": origin["repo"],
                               "sourceCommit": origin["commit"], "sourcePath": name,
                               "licenseStatus": verdict["status"], "license": verdict["spdx"],
                               "licenseEvidence": verdict["evidence"], "provider": origin["provider"],
                               "sourceUrl": args.source_url, "author": args.author,
                               "attribution": None if verdict["spdx"] in ("CC0-1.0", "unknown") else
                               f"{level['name']} — {args.author or 'auteur inconnu'} ({verdict['spdx']})"},
                    "format": level["format"],
                    "geometry": {"width": level["width"], "height": level["height"], "tileWidth": level["tileWidth"],
                                 "tileHeight": level["tileHeight"]},
                    "mechanics": _mechanics(level),
                    "dependencies": {"assets": sem["assets"],
                                     "tilesets": [t.get("source") or t.get("name") for t in level["tilesets"]]},
                    "validation": {"structure": "pending", "solvability": "pending", "simulation": "pending"},
                    "usage": [], "content": content, "contentSha256": content_sha, "losses": level["losses"],
                    "observations": [{**key, "observedAt": _now()}], "transformations": [], "versions": []}
                existing[level_id] = record
                created.append(level_id)
                originals.append((Path(root) / "originals" / "sha256" / f"{content_sha}{PurePosixPath(name).suffix}",
                                  raw))
            diagnostics += level["diagnostics"]
            pending[record["id"]] = record
        # Transactionnel : chaque fiche est contrôlée contre le schéma AVANT la première écriture ; une seule
        # invalide et rien n'est écrit (ni fiche, ni original).
        invalid = [(r["id"], e.message) for r in pending.values()
                   for e in [next(schemas().validator("level").iter_errors(r), None)] if e is not None]
        if invalid:
            return _envelope(LevelExit.INVALID_INPUT, "failed", diagnostics=[
                {"code": "invalid-record", "severity": "error", "message": f"fiche {i} invalide : {m}"}
                for i, m in invalid] + diagnostics, created=[], observed=[], unchanged=unchanged,
                licenseStatus=verdict["status"], dryRun=args.dry_run)
        if not args.dry_run:
            for original, raw in originals:
                original.parent.mkdir(parents=True, exist_ok=True)
                if not original.exists():
                    original.write_bytes(raw)
            for record in pending.values():
                path = _dir(root) / f"{record['id']}.json"
                _write(path, record)
                artifacts.append(path.relative_to(root).as_posix())
    return _envelope(LevelExit.OK, "ok", artifacts, diagnostics, created=created, observed=observed,
                     unchanged=unchanged, licenseStatus=verdict["status"], dryRun=args.dry_run)


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --- Recherche, inspection ----------------------------------------------------------------------------------------

def search(root, args):
    records = _load_all(root)
    rows = [r for r in records.values() if not args.type or r["kind"] == args.type]
    terms = [t for t in re.findall(r"\w+", args.query.lower()) if t]
    if not terms:
        results = sorted(rows, key=lambda r: r["id"])
    else:
        db = sqlite3.connect(":memory:")
        db.execute("CREATE VIRTUAL TABLE levels USING fts5(id UNINDEXED, text, tokenize='unicode61 remove_diacritics 2')")
        for record in rows:
            text = " ".join([record["id"], record["name"], record["kind"], *record["mechanics"],
                             record["origin"]["game"], record["origin"]["universe"], record["format"],
                             *(e["type"] for e in semantics(record["content"])["entities"])])
            db.execute("INSERT INTO levels VALUES (?, ?)", (record["id"], text.replace("-", " ")))
        query = " OR ".join(f'"{t}"' for t in terms)
        found = [row[0] for row in db.execute("SELECT id FROM levels WHERE levels MATCH ? ORDER BY bm25(levels), id",
                                              (query,))]
        results = [records[i] for i in found]
    return _envelope(LevelExit.OK, "ok", results=[{"id": r["id"], "kind": r["kind"], "name": r["name"],
                                                  "game": r["origin"]["game"], "mechanics": r["mechanics"],
                                                  "licenseStatus": r["origin"]["licenseStatus"]} for r in results])


def _get(root, level_id):
    path = _dir(root) / f"{level_id}.json"
    return read_json(path) if re.fullmatch(r"level-[a-z0-9-]+", level_id) and path.is_file() else None


def _missing(level_id):
    return _envelope(LevelExit.MISSING_REFERENCE, "failed", diagnostics=[{"code": "level-not-found", "severity": "error",
                                                                   "message": f"niveau introuvable : {level_id}"}])


# --- Dérivation et génération ----------------------------------------------------------------------------------

def _save_new(root, args, record):
    existing = _load_all(root)
    if record["id"] in existing and existing[record["id"]]["contentSha256"] == record["contentSha256"]:
        return [], "unchanged"
    if record["id"] in existing:
        return None, "conflict"
    if not args.dry_run:
        path = _dir(root) / f"{record['id']}.json"
        _write(path, record)
        return [path.relative_to(root).as_posix()], "created"
    return [], "dry-run"


def derive(root, args):
    parent = _get(root, args.level_id)
    if parent is None:
        return _missing(args.level_id)
    constraints = read_json(args.constraints)
    unknown = sorted(set(constraints.get("transforms", [])) - set(TRANSFORMS))
    if unknown or not constraints.get("transforms"):
        return _envelope(LevelExit.INVALID_INPUT, "failed", diagnostics=[{"code": "transform", "severity": "error",
                                                                "message": f"transformations inconnues : {unknown}"}])
    content = parent["content"]
    for name in constraints["transforms"]:
        content = TRANSFORMS[name]({**content, "losses": [], "diagnostics": []})
        content = _content(content)
    sha = _sha(content)
    record = {**json.loads(json_text(parent)), "id": f"{parent['id']}-{'-'.join(constraints['transforms'])}",
              "content": content, "contentSha256": sha, "derivedFrom": {"id": parent["id"],
                                                                         "contentSha256": parent["contentSha256"]},
              "transformations": [*parent.get("transformations", []), {"transforms": constraints["transforms"],
                                                                       "seed": args.seed}],
              "validation": {"structure": "pending", "solvability": "pending", "simulation": "pending"},
              "versions": [], "usage": []}
    artifacts, state = _save_new(root, args, record)
    if artifacts is None:
        return _envelope(LevelExit.INVALID_INPUT, "failed", diagnostics=[{"code": "id-taken", "severity": "error",
                                                                           "message": record["id"]}])
    return _envelope(LevelExit.OK, state, artifacts, id=record["id"], contentSha256=sha, derivedFrom=parent["id"])


def generate(root, args):
    generator = GENERATORS.get(args.genre)
    if generator is None:
        return _envelope(LevelExit.INVALID_INPUT, "failed", diagnostics=[{
            "code": "no-generator", "severity": "error",
            "message": f"aucun générateur pour {args.genre} : réutiliser une bibliothèque existante (ADR requis)"}])
    constraints = read_json(args.constraints)
    level, generation = generator(constraints, args.seed)
    content = _content(level)
    sha = _sha(content)
    generation["constraintsSha256"] = _sha(constraints)
    record = {"schemaVersion": "1.0.0", "id": f"level-{_slug(args.game)}-{args.genre}-{args.seed}-{sha[:8]}",
              "kind": args.genre, "name": level["name"],
              "origin": {"game": args.game, "universe": constraints.get("universe", "unknown"),
                         "sourceRepo": "opencade-asset-registry", "sourceCommit": "generated",
                         "sourcePath": f"generator:{generation['algorithm']}@{generation['algorithmVersion']}",
                         "licenseStatus": "verified", "license": constraints.get("license", "CC0-1.0"),
                         "licenseEvidence": "généré par le registre", "provider": "generator"},
              "format": "generated", "geometry": {"width": level["width"], "height": level["height"],
                                                 "tileWidth": level["tileWidth"], "tileHeight": level["tileHeight"]},
              "mechanics": _mechanics(level), "dependencies": {"assets": [], "tilesets": []},
              "validation": {"structure": "pending", "solvability": "pending", "simulation": "pending"},
              "usage": [], "generation": generation, "content": content, "contentSha256": sha, "losses": [],
              "observations": [], "transformations": [], "versions": []}
    report = run_validators(record, constraints.get("profile"))
    artifacts, state = _save_new(root, args, record) if report["status"] == "pass" else ([], "rejected")
    code = status_code(report["status"], report["diagnostics"])
    return _envelope(code, state, artifacts or [], report["diagnostics"], id=record["id"], contentSha256=sha,
                     generation=generation, validation=report["status"])


# --- Validation, simulation, usages, publication -------------------------------------------------------------

def _profile(args):
    return read_json(args.profile) if getattr(args, "profile", None) else None


def validate(root, args):
    record = _get(root, args.level_id)
    if record is None:
        return _missing(args.level_id)
    report = run_validators(record, _profile(args), _known_assets(root), _load_all(root))
    code = status_code(report["status"], report["diagnostics"])
    return _envelope(code, report["status"], diagnostics=report["diagnostics"], checks=report["checks"])


def simulate(root, args):
    record = _get(root, args.level_id)
    if record is None:
        return _missing(args.level_id)
    kind = AGENTS[args.agent]
    if record["kind"] != kind:
        return _envelope(LevelExit.INVALID_INPUT, "failed", diagnostics=[{"code": "agent-kind", "severity": "error",
                                                                "message": f"{args.agent} simule un {kind}"}])
    profile = _profile(args) or {}
    result = VALIDATORS[kind](record["content"], profile, Budget(profile.get("budget")))
    code = status_code(result["status"], result["diagnostics"])
    return _envelope(code, result["status"], diagnostics=result["diagnostics"], metrics=result["metrics"],
                     agent=args.agent)


def usages(root, args):
    if not args.scope:
        return _envelope(LevelExit.INVALID_INPUT, "failed", diagnostics=[{"code": "scope", "severity": "error",
                                                                "message": "--scope requis"}])
    scope = read_json(args.scope)
    base = Path(args.scope).parent
    current, history = [], []
    for repo in scope.get("repos", []):
        source = Source((base / repo["path"]).resolve(), repo.get("ref"))
        for name in (n for n in source.files() if PurePosixPath(n).name == "level.lock.json"):
            game = _game_for(repo, name)
            lock = json.loads(source.read(name))
            current += [{"game": game, "repo": repo["name"], "commit": source.commit, "lockFile": name, **entry}
                        for entry in lock.get("levels", []) if entry.get("id") == args.level_id]
            if source.git:
                commits = source._git("log", "--format=%H %cI", source.commit, "--", name).decode().split("\n")
                for line in filter(None, commits):
                    sha, when = line.split(" ", 1)
                    old = json.loads(source._git("show", f"{sha}:{name}"))
                    history += [{"game": game, "repo": repo["name"], "commit": sha, "date": when,
                                 "version": e.get("version"), "sha256": e.get("sha256")}
                                for e in old.get("levels", []) if e.get("id") == args.level_id]
    return _envelope(LevelExit.OK, "ok", levelId=args.level_id, usages=current,
                     games=sorted({u["game"] for u in current}), history=history)


def publish(root, args):
    record = _get(root, args.level_id)
    if record is None:
        return _missing(args.level_id)
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        return _envelope(LevelExit.INVALID_INPUT, "failed", diagnostics=[{"code": "version", "severity": "error",
                                                                "message": "version semver attendue (1.2.0)"}])
    if record["origin"]["licenseStatus"] != "verified":
        return _envelope(LevelExit.RIGHTS_BLOCKED, "blocked", diagnostics=[{
            "code": "license-unknown", "severity": "error",
            "message": f"licence {record['origin']['licenseStatus']} : publication refusée"}])
    report = run_validators(record, _profile(args), _known_assets(root), _load_all(root))
    if report["status"] != "pass":
        return _envelope(status_code(report["status"], report["diagnostics"]), report["status"], diagnostics=report["diagnostics"])
    sha = record["contentSha256"] if record["format"] == "generated" else _sha(record["content"])
    previous = next((v for v in record["versions"] if v["version"] == args.version), None)
    lock = {"id": record["id"], "version": args.version, "sha256": sha,
            "transform": record.get("transformations") or None}
    if previous and previous["sha256"] != sha:
        return _envelope(LevelExit.INVALID_INPUT, "failed", diagnostics=[{
            "code": "version-immutable", "severity": "error",
            "message": f"{record['id']}@{args.version} est déjà publiée avec un autre contenu"}])
    if previous:
        return _envelope(LevelExit.OK, "unchanged", lock=lock)
    artifacts = []
    if not args.dry_run:
        with directory_lock(Path(root) / "catalog"):
            target = Path(root) / "published" / "levels" / record["id"] / f"{args.version}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            write_json(target, {"id": record["id"], "version": args.version, "kind": record["kind"],
                                "origin": record["origin"], "dependencies": record["dependencies"],
                                "content": record["content"], "sha256": sha})
            record["versions"].append({"version": args.version, "sha256": sha})
            record["validation"] = {k: "pass" for k in ("structure", "solvability", "simulation")}
            _write(_dir(root) / f"{record['id']}.json", record)
            artifacts = [target.relative_to(root).as_posix()]
    return _envelope(LevelExit.OK, "published" if not args.dry_run else "dry-run", artifacts, lock=lock)


def run(root, args):
    if not enabled():
        return LevelExit.INFRASTRUCTURE, {"ok": False, "error": "levels-disabled",
                                "message": "Module EXT-002 désactivé (ASSETCTL_LEVELS=off)."}
    handlers = {"discover": discover, "import": import_levels, "search": search, "derive": derive,
                "generate": generate, "validate": validate, "simulate": simulate, "usages": usages,
                "publish": publish}
    if args.level_command == "inspect":
        record = _get(root, args.level_id)
        return _missing(args.level_id) if record is None else _envelope(LevelExit.OK, "ok", level=record)
    try:
        return handlers[args.level_command](root, args)
    except subprocess.CalledProcessError as exc:
        return _envelope(LevelExit.INFRASTRUCTURE, "failed", diagnostics=[{"code": "git", "severity": "error",
                                                              "message": f"git a échoué ({exc.returncode})"}])
