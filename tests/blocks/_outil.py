"""Outils communs des oracles du module blocks/ (BB-001 au-dessus de graphify).

Contrat d'appel (fixé par ces oracles) :
  - exécutable `./bbctl` à la racine de l'usine, aussi `python3 -m blocks.bbctl` ;
  - `USINE_RACINE=<dossier>` : où `bbctl` lit et écrit SES données (`blocks/catalog/`, `blocks/decisions/`,
    `blocks/evaluations/`) ; défaut = la racine du dépôt. Les tests pointent toujours un dossier temporaire ;
  - `--graph <graph.json>` (ou `BBCTL_GRAPH`) : le graphe graphify, LU SEULEMENT (format networkx node-link : `nodes`
    avec `id` `<dépôt>::…`, `label`, `repo`, `source_file`, `source_location` ; `links`) ;
  - codes communs de l'usine : 0 succès, 1 contrôle en échec, 2 usage, 3 refus de sécurité, 4 source indisponible,
    5 conflit de versions.
Ce que graphify sait déjà (code, imports, appels) ne se recopie pas dans les fiches : une fiche porte SEULEMENT licence,
version adoptée, statut d'adoption, décision et justification, TCO, usedBy (analyse des écarts § 4).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

RACINE = pathlib.Path(__file__).resolve().parents[2]
BBCTL = RACINE / "bbctl"
DECISIONS = RACINE / "tests" / "fixtures" / "blocks" / "reuse-decisions"
COMMIT_PESTOUILLE = "dba3957a72c53557df94f8dde306b6cae028062f"

NOEUDS = [
    {"id": "six-de-chaque::packages_engine_src_pathfinding_findpath", "label": "findPath()", "norm_label": "findpath()",
     "repo": "six-de-chaque", "source_file": "packages/engine/src/pathfinding.ts", "source_location": "L12", "file_type": "code"},
    {"id": "capsule-panic::src_game_grid_path_gridpath", "label": "gridPath()", "norm_label": "gridpath()",
     "repo": "capsule-panic", "source_file": "src/game/grid-path.ts", "source_location": "L3", "file_type": "code"},
    {"id": "pestouille-rpg::src_save_checksum", "label": "checksum()", "norm_label": "checksum()",
     "repo": "pestouille-rpg", "source_file": "src/save/checksum.ts", "source_location": "L1", "file_type": "code"},
]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fiche(id_: str = "BB-SIX-PATHFINDING-001", **change) -> dict:
    """Fiche conforme au contrat BB-001 § 7, plus `origin.repo`/`origin.path` pour une brique interne."""
    f = {"schemaVersion": "1.0", "id": id_, "name": "Pathfinding sur grille", "kind": "game-local-module",
         "origin": {"repositoryUrl": None, "repo": "six-de-chaque", "path": "packages/engine/src/pathfinding.ts",
                    "licenseSpdx": "MIT", "commitSha": None},
         "capabilities": ["grid-pathfinding"], "interfaces": [{"language": "typescript", "runtime": "browser"}],
         "specIds": [], "usedBy": ["six-de-chaque"],
         "quality": {"status": "adopted", "sbomRef": None, "securityReportRef": None},
         "decision": {"status": "pending", "rationale": None},
         "provenance": {"discoveredBy": "agent", "verifiedAt": None}}
    for k, v in change.items():
        f[k] = v
    return f


class Usine:
    def __init__(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bbctl-"))
        self.usine = self.tmp / "usine"
        (self.usine / "blocks" / "catalog").mkdir(parents=True)
        self.graphe = self.tmp / "graph.json"
        self.graphe.write_text(json.dumps({"directed": True, "multigraph": False, "graph": {}, "nodes": NOEUDS, "links": []}))
        self.poser(fiche())

    def poser(self, f: dict, nom: str | None = None) -> pathlib.Path:
        p = self.usine / "blocks" / "catalog" / f"{nom or f['id']}.json"
        p.write_text(json.dumps(f, ensure_ascii=False, indent=1))
        return p

    def bbctl(self, *args: str) -> "Resultat":
        env = {**os.environ, "USINE_RACINE": str(self.usine)}
        env.pop("BBCTL_GRAPH", None)
        r = subprocess.run([str(BBCTL), *args], capture_output=True, text=True, env=env, timeout=120, cwd=str(self.tmp))
        return Resultat(r.returncode, r.stdout, r.stderr)

    def empreinte(self, d: pathlib.Path) -> str:
        h = hashlib.sha256()
        for p in sorted(d.rglob("*")):
            if p.is_file():
                h.update(str(p.relative_to(d)).encode() + b"\0" + p.read_bytes())
        return h.hexdigest()

    def nettoyer(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class Resultat:
    def __init__(self, rc: int, stdout: str, stderr: str) -> None:
        self.rc, self.stdout, self.stderr = rc, stdout, stderr

    @property
    def json(self) -> dict:
        return json.loads(self.stdout)

    def __repr__(self) -> str:
        return f"rc={self.rc} stdout={self.stdout[:300]!r} stderr={self.stderr[-300:]!r}"
