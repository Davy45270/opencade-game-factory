"""Contrat de la CLI `assetctl` tel que l'oracle d'acceptation le suppose.

Les tests d'acceptation AT-01…AT-15 appellent la CLI en boîte noire : sous-processus
`./assetctl … --json`, code de retour, JSON de sortie, fichiers produits. Aucune fonction interne
n'est importée. Tout détail que les briefs de lots (L1, L2a, L2b, L3) ne fixent pas est isolé ICI,
dans une constante : si l'implémentation choisit autrement, c'est ce fichier qu'on corrige, et le
désaccord se discute — on ne contourne pas un test.

Sources du contrat : spec v1.0 §6, §7, §11 ; briefs `.codex-logs/run-{1,2,3,4}-prompt.md`.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

# --------------------------------------------------------------------------------------------
# Constantes du contrat
# --------------------------------------------------------------------------------------------

#: Racine du registre testé (le dépôt qui contient ce fichier).
RACINE_REGISTRE = Path(__file__).resolve().parents[2]

#: Exécutable à la racine du registre (brief L1 §« Architecture »).
ASSETCTL = "assetctl"

#: Codes de retour documentés (brief L1 §2).
OK, ECHEC, USAGE, REFUS, ERREUR_ES = 0, 1, 2, 3, 4

#: Préfixes jamais copiés dans le registre de fixture (environnement virtuel de la CI, caches, base dérivée).
EXCLUS_COPIE = (".venv/", "venv/", ".cache/", "build/", "node_modules/")

#: Délai d'une commande (secondes). Généreux : un délai trop court ment en « absence ».
DELAI = 600

# Catalogue (brief L1 : source de vérité = catalog/).
SOURCES = "catalog/sources.json"
DOSSIER_ASSETS = "catalog/assets"
DOSSIER_PLANCHES = "catalog/sheets"
FICHIER_IDS = "catalog/ids.json"
DOSSIER_JOBS = "catalog/import-jobs"

# Sorties dérivées (briefs L2a §6, L2b §1, L3 §1).
DOSSIER_RAPPORTS = "generated/reports"
#: Rapports exigés en JSON **et** Markdown (brief L2a §6). `exceptions` : nom imposé par la spec §6.
RAPPORTS = ("migration", "exceptions", "coverage", "licenses-unknown", "orphans", "scan-limits")
RAPPORT_VERIFY = "generated/reports/verify.json"
RAPPORT_REFS_DYNAMIQUES = "generated/reports/dynamic-refs.json"
RAPPORT_SUPPRESSIONS = "generated/reports/removed-in-use.json"
#: Fichiers produits par `assetctl index` depuis catalog/ seul (brief L3 §1).
FICHIERS_INDEX = ("generated/catalog.json", "generated/usage-index.json", "generated/search-index.json")
BASE_SQLITE = "build/registry.sqlite"
MANIFESTE_LICENCES = "generated/licenses.json"

#: Lock d'un jeu, à la racine du dépôt de jeu passé en `--repo-dir` (brief L3 §2) — NON FIXÉ par le brief.
LOCK_JEU = "assets.lock.json"

#: Clé de la liste d'autorisation dans sources.json quand aucun sources.json n'existe encore
#: (forme NON FIXÉE par le brief L2a : on reprend celle du fichier réel s'il existe, voir `ecrire_sources`).
CLE_SOURCES = "sources"
CLE_EXCLUS = "excluded"

#: Miroirs : défaut du brief L2a, sous un HOME de fixture (voir `environnement`).
SOUS_CHEMIN_CACHE = ".cache/opencade-asset-registry/mirrors"

#: Option qui autorise la matérialisation d'un asset à export public interdit (brief L3 §2).
OPTION_CIBLE_PRIVEE = "--private-target"

#: Clés possibles de la liste de résultats dans la sortie JSON de `search` — NON FIXÉ par le brief L3.
CLES_RESULTATS = ("results", "resultats", "items", "assets", "candidates")

#: Préfixe d'un cadre d'atlas issu d'une table de découpe (brief L2b §2 : `sprite-<id>` ou `<id>`).
PREFIXE_CADRE = "sprite-"

#: Seuil de vérification d'une région (brief L2b §2, comme verifier-decoupe.py).
SEUIL_RMSE = 0.02


# --------------------------------------------------------------------------------------------
# Commandes du contrat (une fonction = une ligne des briefs)
# --------------------------------------------------------------------------------------------

def cmd_scan(cache: Path, *extra: str) -> list[str]:
    """L2a §2 : découverte + import idempotent + rapports."""
    return ["scan-repos", "--cache", str(cache), *extra, "--json"]


def cmd_verify(cache: Path, *extra: str) -> list[str]:
    """L2a §7 : second scan de contrôle."""
    return ["scan-repos", "--verify", "--cache", str(cache), *extra, "--json"]


def cmd_validate(*extra: str) -> list[str]:
    return ["validate", *extra, "--json"]


def cmd_index() -> list[str]:
    return ["index", "--json"]


def cmd_search(texte: str, *extra: str) -> list[str]:
    return ["search", texte, *extra, "--json"]


def cmd_publish(ids: Iterable[str], cible: str, dest: Path) -> list[str]:
    return ["publish", *ids, "--target", cible, "--dest", str(dest), "--json"]


def cmd_register(fichier: Path, nom: str, categorie: str, *extra: str) -> list[str]:
    return ["register", str(fichier), "--name", nom, "--category", categorie, *extra, "--json"]


def cmd_usage_add(asset_id: str, jeu: str, scene: str, role: str, depot: Path, chemin: str,
                  *extra: str) -> list[str]:
    return ["usage", "add", asset_id, "--game", jeu, "--scene", scene, "--role", role,
            "--repo-dir", str(depot), "--path", chemin, *extra, "--json"]


def cmd_materialize(asset_id: str, dest: Path, *extra: str) -> list[str]:
    return ["materialize", asset_id, "--to", str(dest), *extra, "--json"]


def cmd_check_lock(lock: Path, *extra: str) -> list[str]:
    return ["check-lock", str(lock), *extra, "--json"]


def cmd_sync(branche: str, *extra: str) -> list[str]:
    return ["sync", "--branch", branche, *extra, "--json"]


def cmd_export_atlas(ids: Iterable[str], sortie: str) -> list[str]:
    return ["export-atlas", *ids, "--out", sortie, "--json"]


def cmd_validate_atlas(json_atlas: Path) -> list[str]:
    return ["validate-atlas", str(json_atlas), "--json"]


# --------------------------------------------------------------------------------------------
# Exécution
# --------------------------------------------------------------------------------------------

@dataclass
class Resultat:
    code: int
    stdout: str
    stderr: str
    commande: list[str]

    @property
    def json(self) -> Any:
        try:
            return json.loads(self.stdout)
        except ValueError:
            return None

    def __str__(self) -> str:  # message d'échec lisible
        return (f"$ assetctl {' '.join(self.commande)}\n→ code {self.code}\n"
                f"--- stdout (2000 car.) ---\n{self.stdout[:2000]}\n"
                f"--- stderr (2000 car.) ---\n{self.stderr[-2000:]}")


def environnement(home: Path) -> dict[str, str]:
    """HOME de fixture : le cache par défaut et la config git globale restent dans le dossier
    temporaire ; aucun jeton, aucune adresse personnelle ; aucun affichage (headless, AT-14)."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("ASSETCTL_", "GIT_")) and k not in ("XDG_CACHE_HOME", "XDG_CONFIG_HOME", "DISPLAY", "WAYLAND_DISPLAY")}
    env.update({
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LC_ALL": "C.UTF-8",
    })
    return env


def assetctl(registre: Path, home: Path, args: list[str]) -> Resultat:
    p = subprocess.run([sys.executable, str(registre / ASSETCTL), *args], cwd=registre,
                       env=environnement(home), capture_output=True, text=True, timeout=DELAI)
    return Resultat(p.returncode, p.stdout, p.stderr, args)


def git(depot: Path, home: Path, *args: str, date: str | None = None) -> str:
    env = environnement(home)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    p = subprocess.run(["git", "-C", str(depot), *args], env=env, capture_output=True, text=True,
                       timeout=DELAI)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args)} dans {depot} : {p.stderr}")
    return p.stdout.strip()


# --------------------------------------------------------------------------------------------
# Copie du registre (jamais le catalogue réel)
# --------------------------------------------------------------------------------------------

def copier_registre(dest: Path, home: Path) -> Path:
    """Copie l'arbre suivi (et non ignoré) du registre testé, vide le catalogue et les sorties
    dérivées, puis en fait un dépôt git neuf (une branche `main`, un commit)."""
    fichiers = subprocess.run(
        ["git", "-C", str(RACINE_REGISTRE), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True, check=True).stdout.decode().split("\0")
    for rel in filter(None, fichiers):
        if rel.startswith(EXCLUS_COPIE):
            continue
        src = RACINE_REGISTRE / rel
        if not src.is_file():
            continue
        cible = dest / rel
        cible.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, cible)
    # Catalogue vidé : seules restent les universes et la liste d'autorisation (réécrite ensuite).
    for dossier in (DOSSIER_ASSETS, DOSSIER_PLANCHES, DOSSIER_JOBS, "generated", "thumbnails",
                    "atlases", "sprites", "sources", "build"):
        racine = dest / dossier
        if racine.is_dir():
            for f in sorted(racine.rglob("*"), reverse=True):
                if f.is_file() and f.name != ".gitkeep":
                    f.unlink()
    # Les têtes importées du vrai catalogue n'existent pas dans les dépôts du monde : les garder bloquerait tout
    # scan (« aucune continuité prouvée »), comme sur un catalogue qui n'aurait jamais rien importé.
    (dest / "catalog" / "scan-references.json").unlink(missing_ok=True)
    ids = dest / FICHIER_IDS
    ids.parent.mkdir(parents=True, exist_ok=True)
    ids.write_text("{}\n", encoding="utf-8")
    git(dest, home, "init", "-q", "-b", "main")
    return dest


def ecrire_sources(registre: Path, entrees: list[dict], exclus: list[dict]) -> None:
    """Écrit la liste d'autorisation de fixture en reprenant la forme du sources.json réel
    (brief L2a §1 : entrées `{name, role, games, copies:[{provider, path}]}`, `excluded:[{name, reason}]`)."""
    chemin = registre / SOURCES
    forme: Any = None
    if chemin.is_file():
        try:
            forme = json.loads(chemin.read_text(encoding="utf-8"))
        except ValueError:
            forme = None
    if isinstance(forme, list):
        sortie: Any = entrees  # forme liste : pas de place pour les exclus
    elif isinstance(forme, dict):
        sortie = dict(forme)
        cle = next((k for k, v in forme.items() if isinstance(v, list) and v and isinstance(v[0], dict)
                    and "copies" in v[0]), CLE_SOURCES)
        sortie[cle] = entrees
        cle_ex = next((k for k in forme if k.lower().startswith("exclu")), CLE_EXCLUS)
        sortie[cle_ex] = exclus
    else:
        sortie = {"schemaVersion": "1.0", CLE_SOURCES: entrees, CLE_EXCLUS: exclus}
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(sortie, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_locale(nom: str, chemin: Path, role: str = "game", jeux: list[str] | None = None) -> dict:
    return {"name": nom, "role": role, "games": jeux if jeux is not None else [nom],
            "copies": [{"provider": "local", "path": str(chemin), "defaultBranch": "main"}]}


# --------------------------------------------------------------------------------------------
# Lecture du catalogue et des rapports
# --------------------------------------------------------------------------------------------

def lire_json(chemin: Path) -> Any:
    return json.loads(chemin.read_text(encoding="utf-8"))


def assets(registre: Path) -> dict[str, dict]:
    d = registre / DOSSIER_ASSETS
    return {f.stem: lire_json(f) for f in sorted(d.glob("*.json"))} if d.is_dir() else {}


def planches(registre: Path) -> dict[str, dict]:
    d = registre / DOSSIER_PLANCHES
    return {f.stem: lire_json(f) for f in sorted(d.glob("*.json"))} if d.is_dir() else {}


def parcourir(obj: Any) -> Iterator[Any]:
    """Tous les nœuds d'un JSON, en profondeur."""
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from parcourir(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from parcourir(v)


def dicts(obj: Any, predicat: Callable[[dict], bool] = lambda d: True) -> list[dict]:
    return [n for n in parcourir(obj) if isinstance(n, dict) and predicat(n)]


def contient_valeur(obj: Any, valeur: Any) -> bool:
    return any(n == valeur for n in parcourir(obj) if not isinstance(n, (dict, list)))


def contient_texte(obj: Any, texte: str) -> bool:
    return any(isinstance(n, str) and texte in n for n in parcourir(obj))


def emplacements(obj: Any) -> list[dict]:
    """Emplacements `{repo, commit, path}` (brief L1 : `files.locations`)."""
    return dicts(obj, lambda d: "path" in d and "commit" in d)


def asset_par_chemin(registre: Path, depot: str, chemin: str) -> tuple[str, dict]:
    trouves = [(i, a) for i, a in assets(registre).items()
               if any(e.get("path") == chemin and e.get("repo") in (depot, None) for e in emplacements(a.get("files")))]
    if len(trouves) != 1:
        raise AssertionError(f"{len(trouves)} asset(s) pour {depot}:{chemin} (1 attendu) : {[i for i, _ in trouves]}")
    return trouves[0]


def assets_citant(registre: Path, texte: str) -> list[tuple[str, dict]]:
    return [(i, a) for i, a in assets(registre).items() if contient_texte(a, texte)]


def resultats_recherche(sortie: Any) -> list[dict]:
    if isinstance(sortie, list):
        return [r if isinstance(r, dict) else {"id": r} for r in sortie]
    if isinstance(sortie, dict):
        for cle in CLES_RESULTATS:
            if isinstance(sortie.get(cle), list):
                return [r if isinstance(r, dict) else {"id": r} for r in sortie[cle]]
    raise AssertionError(f"aucune liste de résultats ({CLES_RESULTATS}) dans : {str(sortie)[:500]}")


def rapport(registre: Path, nom: str, ext: str = "json") -> Path:
    return registre / DOSSIER_RAPPORTS / f"{nom}.{ext}"


# --------------------------------------------------------------------------------------------
# Empreintes
# --------------------------------------------------------------------------------------------

def sha256_fichier(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def empreinte_arbre(racine: Path, avec_dates: bool = True, exclure: tuple[str, ...] = ()) -> str:
    """Empreinte d'un arbre : chemins, type, mode, contenu (et date de modification). Couvre `.git`."""
    h = hashlib.sha256()
    if not racine.exists():
        return "absent"
    for chemin in sorted(racine.rglob("*")):
        rel = chemin.relative_to(racine).as_posix()
        if any(rel == e or rel.startswith(e + "/") for e in exclure):
            continue
        st = chemin.lstat()
        h.update(rel.encode() + b"\0" + oct(st.st_mode).encode() + b"\0")
        if chemin.is_symlink():
            h.update(os.readlink(chemin).encode())
        elif chemin.is_file():
            h.update(hashlib.sha256(chemin.read_bytes()).digest())
            if avec_dates:
                h.update(str(st.st_mtime_ns).encode())
        h.update(b"\n")
    return h.hexdigest()
