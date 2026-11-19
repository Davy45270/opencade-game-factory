"""Périmètre de lecture et accès aux objets Git des miroirs nus."""

import base64
import os
import re
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tools.core.catalog import Catalogue, CatalogueScopeError, read_json
from tools.core.schemas import schemas

OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
HOSTS = {"github": "github.com", "forgejo": "forgejo.pingfr.duckdns.org"}
PROVIDERS = (*HOSTS, "local")


@dataclass(frozen=True)
class Copy:
    name: str
    role: str
    games: tuple
    provider: str
    address: str
    visibility: str
    default_branch: str | None

    @property
    def key(self):
        return self.name, self.provider

    @property
    def url(self):
        return Path(self.address).as_uri() if self.provider == "local" else self.address


def source_problems(document):
    """Contrôle partagé avec validate, y compris les collisions de cache."""
    error = next(schemas().validator("sources").iter_errors(document), None)
    if error:
        yield "Liste d’autorisation invalide."
        return
    names = [source["name"] for source in document["sources"]]
    excluded = [source["name"] for source in document["excluded"]]
    if len(set(names + excluded)) != len(names + excluded):
        yield "Nom canonique répété parmi les sources et les exclusions."
    for source in document["sources"]:
        seen = set()
        for copy in source["copies"]:
            provider = copy["provider"]
            if provider in seen:
                yield f"Fournisseur répété pour {source['name']}."
            seen.add(provider)
            if provider in HOSTS:
                prefix = f"https://{HOSTS[provider]}/"
                if not copy["url"].startswith(prefix) or not re.fullmatch(
                    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", copy["url"][len(prefix):]
                ) or any(part in {".", ".."} for part in copy["url"][len(prefix):].split("/")):
                    yield f"Adresse HTTPS hors périmètre pour {source['name']} ({provider})."


def _copies(path):
    value = read_json(path)
    if value == []:  # Catalogue initial du lot L1.
        return {}
    if next(source_problems(value), None):
        raise CatalogueScopeError("Liste d’autorisation invalide.")
    result = {}
    for source in value["sources"]:
        for item in source["copies"]:
            copy = Copy(source["name"], source["role"], tuple(source["games"]), item["provider"],
                        item.get("path", item.get("url")), item.get("visibility", "unknown"),
                        item.get("defaultBranch"))
            result[copy.key] = copy
    return result


def select(root, args):
    catalogue = Catalogue(root)
    authority = _copies(catalogue._regular_path(catalogue.path / "sources.json"))
    proposal = _copies(args.sources) if args.sources is not None else authority
    for key, copy in proposal.items():
        if key not in authority or copy.address != authority[key].address:
            raise CatalogueScopeError("URL ou chemin absent de catalog/sources.json.")
    names = {name for name, _ in proposal}
    wanted = set(args.only or names)
    if wanted - names:
        raise CatalogueScopeError("Dépôt demandé absent de la liste d’autorisation.")
    selected = [authority[key] for key in sorted(proposal)
                if key[0] in wanted and (args.provider is None or key[1] == args.provider)]
    for copy in selected:
        if copy.provider == "local" and Path(copy.address) != Path(copy.address).resolve():
            raise CatalogueScopeError("Le chemin d’une copie locale doit être absolu et canonique.")
    return selected, tuple(copy for copy in authority.values() if copy.provider == "local")


def check_destinations(root, cache, log, local_copies):
    registry = root.resolve()
    cache = cache.resolve()
    logfile = log.resolve() if log is not None else None
    outputs = (registry, cache) if logfile is None else (registry, cache, logfile)
    for copy in local_copies:
        source = Path(copy.address)
        if (any(path.is_relative_to(source) for path in outputs)
                or source.is_relative_to(cache)):
            raise CatalogueScopeError("Destination en conflit avec un dépôt source.")
    if cache.is_relative_to(registry / "catalog") or cache.is_relative_to(registry / ".git"):
        raise CatalogueScopeError("Le cache doit être extérieur au catalogue et à .git.")


def git_environment(environ=None):
    original = os.environ if environ is None else environ
    env = {key: value for key, value in original.items()
           if not key.startswith(("GIT_", "ASSETCTL_"))}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1",
               GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_LFS_SKIP_SMUDGE="1", LC_ALL="C")
    if "GIT_CONFIG_COUNT" in original:
        env.update({key: value for key, value in original.items()
                    if re.fullmatch(r"GIT_CONFIG_(?:COUNT|(?:KEY|VALUE)_\d+)", key)})
        return env
    headers = []
    if token := original.get("ASSETCTL_GITHUB_TOKEN"):
        encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        headers.append(("github", f"Authorization: Basic {encoded}"))
    if token := original.get("ASSETCTL_FORGEJO_TOKEN"):
        headers.append(("forgejo", f"Authorization: token {token}"))
    env["GIT_CONFIG_COUNT"] = str(len(headers))
    for n, (provider, value) in enumerate(headers):
        env[f"GIT_CONFIG_KEY_{n}"] = f"http.https://{HOSTS[provider]}/.extraheader"
        env[f"GIT_CONFIG_VALUE_{n}"] = value
    return env


class GitError(OSError):
    pass


class Git:
    def __init__(self, root):
        self.root = root
        self.env = git_environment()

    def command(self, args, mirror=None):
        command = ["git", "-C", str(self.root), "-c", "http.followRedirects=false",
                   "-c", "credential.helper=", "-c", "protocol.allow=never",
                   "-c", "protocol.file.allow=always", "-c", "protocol.https.allow=always",
                   "-c", "maintenance.auto=false", "-c", "gc.auto=0", "-c", "core.hooksPath=/dev/null",
                   "-c", "core.fsmonitor=false"]
        if mirror is not None:
            command.extend(("--git-dir", str(mirror)))
        return [*command, *args]

    def run(self, *args, mirror=None, ok=(0,)):
        try:
            process = subprocess.run(self.command(args, mirror), env=self.env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=180)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise GitError(f"Git {args[0]} indisponible ou délai dépassé.") from None
        if process.returncode not in ok:
            raise GitError(f"Git {args[0]} a échoué (code {process.returncode}).")
        return process.stdout

    def transport(self, copy):
        url = copy.url
        if self.run("ls-remote", "--get-url", "--", url).rstrip(b"\n") != url.encode():
            raise CatalogueScopeError("Réécriture Git de l’adresse autorisée refusée.")
        return url

    def remote_head(self, copy):
        url = self.transport(copy)
        ref = f"refs/heads/{copy.default_branch}" if copy.default_branch else "HEAD"
        values = self.run("ls-remote", "--symref", "--exit-code", "--", url, ref).splitlines()
        branch = copy.default_branch
        commit = None
        for value in values:
            target, _, name = value.partition(b"\t")
            if name.decode() != ref:
                continue
            if target.startswith(b"ref: refs/heads/"):
                branch = target[len(b"ref: refs/heads/"):].decode("utf-8", "replace")
            elif OID.fullmatch(target.decode()):
                commit = target.decode()
        if commit is None:
            raise GitError("Tête distante absente.")
        return commit, branch

    def prepare(self, copy, cache, fetch):
        provider_path = cache / copy.provider
        mirror = provider_path / f"{copy.name}.git"
        if mirror.is_symlink() or provider_path.is_symlink():
            raise CatalogueScopeError("Lien symbolique interdit dans le cache des miroirs.")
        if not mirror.exists():
            if not fetch:
                raise GitError("Miroir absent avec --no-fetch.")
            url = self.transport(copy)
            provider_path.mkdir(parents=True, exist_ok=True)
            self.run("clone", "--mirror", "--no-local", "--template=", "--", url, str(mirror))
            if copy.default_branch:
                self.run("symbolic-ref", "HEAD", f"refs/heads/{copy.default_branch}", mirror=mirror)
        else:
            self.check_mirror(copy, mirror)
            if fetch:
                url = self.transport(copy)
                _, branch = self.remote_head(copy)
                self.run("fetch", "--prune", "--no-recurse-submodules", "--", url,
                         "+refs/*:refs/*", mirror=mirror)
                if branch:
                    self.run("symbolic-ref", "HEAD", f"refs/heads/{branch}", mirror=mirror)
        return mirror

    def check_mirror(self, copy, mirror):
        for relative in ("config", "objects", "objects/info", "objects/pack", "refs", "HEAD", "packed-refs"):
            if (mirror / relative).is_symlink():
                raise CatalogueScopeError("Lien symbolique interdit dans le miroir.")
        if any((mirror / "objects" / "info" / name).exists()
               for name in ("alternates", "http-alternates")):
            raise CatalogueScopeError("Magasin d’objets externe interdit dans le miroir.")
        keys = self.run("config", "--file", str(mirror / "config"), "--no-includes",
                        "--name-only", "--list").splitlines()
        external = (b"include.", b"includeif.", b"url.", b"core.worktree", b"core.hookspath",
                    b"extensions.partialclone", b"core.alternaterefscommand")
        if any(key.startswith(external) or key.endswith(b".promisor") for key in keys):
            raise CatalogueScopeError("Configuration externe interdite dans le miroir.")
        if (self.run("rev-parse", "--is-bare-repository", mirror=mirror).strip() != b"true" or
                self.run("config", "--local", "--no-includes", "--get", "remote.origin.url",
                         mirror=mirror).rstrip(b"\n") != copy.url.encode()):
            raise CatalogueScopeError("Origine du miroir différente de la copie autorisée.")

    def reference(self, mirror):
        commit = self.run("rev-parse", "--verify", "HEAD^{commit}", mirror=mirror).decode().strip()
        symbolic = self.run("symbolic-ref", "--quiet", "--short", "HEAD", mirror=mirror, ok=(0, 1))
        branch = symbolic.decode("utf-8", "backslashreplace").strip()
        return {"branch": branch or None, "commit": commit,
                "date": self.run("show", "-s", "--format=%cI", commit, mirror=mirror).decode().strip(),
                "tags": self.tags(mirror)}

    def tags(self, mirror):
        tags = []
        lines = self.run("for-each-ref", "--format=%(refname:strip=2)%00%(objecttype)%00%(objectname)",
                         "refs/tags", mirror=mirror).splitlines()
        for line in lines:
            name, kind, oid = line.split(b"\0")
            if kind == b"tag":
                oid = self.run("rev-parse", "--verify", oid.decode() + "^{commit}",
                               mirror=mirror, ok=(0, 128)).strip()
            tags.append({"name": name.decode("utf-8", "backslashreplace"),
                         "commit": oid.decode() if oid and kind in {b"tag", b"commit"} else None})
        return tags

    def tree(self, mirror, commit, *, sizes):
        flags = "-rlz" if sizes else "-rz"
        for entry in self.run("ls-tree", flags, commit, mirror=mirror).split(b"\0"):
            if not entry:
                continue
            header, path = entry.split(b"\t", 1)
            mode, kind, oid, *size = header.split()
            if kind == b"blob":
                yield Blob(path.decode("utf-8", "backslashreplace"), oid.decode(),
                           int(size[0]) if size else None, mode == b"120000")

    def history_dates(self, mirror, commit, oids):
        """Date du premier ajout en parcourant les parents avant leurs descendants."""
        if not oids:
            return {}
        data = self.run("log", "-m", "--root", "--raw", "-z", "--no-abbrev", "--no-renames",
                        "--topo-order", "--reverse", "--format=%x00%ct", commit, mirror=mirror)
        dates = {}
        fields = iter(data.split(b"\0"))
        current = None
        for field in fields:
            entry = field.lstrip(b"\n")
            if entry.isdigit():
                current = int(entry)
            elif entry.startswith(b":"):
                oid = entry.split()[3].decode("ascii")
                next(fields, None)  # --raw -z enregistre toujours le chemin après l'en-tête.
                if oid in oids and current is not None:
                    dates.setdefault(oid, current)
        return dates

    @contextmanager
    def batch(self, mirror):
        with subprocess.Popen(self.command(["cat-file", "--batch"], mirror), env=self.env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            try:
                yield Batch(process)
                process.stdin.close()
                if process.wait(timeout=30) != 0:
                    raise GitError("Lecture Git cat-file indisponible.")
            except (BrokenPipeError, subprocess.TimeoutExpired):
                raise GitError("Lecture Git cat-file interrompue.") from None
            finally:
                if process.poll() is None:
                    process.kill()


@dataclass(frozen=True)
class Blob:
    path: str
    oid: str
    size: int | None
    symlink: bool


class Batch:
    def __init__(self, process):
        self.process = process

    def read(self, blob, limit):
        process = self.process
        process.stdin.write(blob.oid.encode("ascii") + b"\n")
        process.stdin.flush()
        fields = process.stdout.readline().split()
        if len(fields) != 3 or fields[1] != b"blob":
            raise GitError("Objet Git absent ou de type inattendu.")
        size = int(fields[2])
        data = process.stdout.read(min(size, limit))
        remaining = size - len(data)
        while remaining:
            block = process.stdout.read(min(remaining, 1024 * 1024))
            if not block:
                raise GitError("Objet Git tronqué.")
            remaining -= len(block)
        if process.stdout.read(1) != b"\n":
            raise GitError("Objet Git tronqué.")
        return data if size <= limit else None


def is_earlier(left, right):
    return datetime.fromisoformat(left) < datetime.fromisoformat(right)
