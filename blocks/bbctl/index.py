"""Index générés du catalogue BB-001 (§ 9 « source de vérité ») : SQLite FTS5 et graphe de dépendances.

Les manifestes JSON de `blocks/catalog/` font foi ; ces fichiers se reconstruisent depuis eux seuls, à l'identique
(lignes de l'index et octets du graphe), et `--check` compare sans rien écrire : absent ou différent = contrôle en échec.
"""

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from tools.core.catalog import InvalidJSON, json_text

from .search import GraphUnavailable

BASE = "blocks-fts.sqlite"
GRAPHE = "dependency-graph.json"
COLONNES = ("id", "name", "kind", "capabilities", "specIds", "usedBy", "repo", "path")


class IndexStale(InvalidJSON):
    """Index absent ou périmé (code 1, contrôle en échec)."""


def statuts(block):
    """E183 : statut de VALIDATION (qualité de la brique) séparé du statut de CONSOMMATION (qui l'utilise).
    `adopted` des fiches = approuvée ET consommée : il se décompose."""
    quality = block["quality"]["status"]
    return {"validation": "approved" if quality == "adopted" else quality,
            "consumption": "consumed" if block.get("usedBy") else "unused"}


def incoherences(records):
    """Une brique `adopted` sans consommateur mélange les deux axes : refusée par `validate`."""
    return sorted(block_id for block_id, (_, block) in records.items()
                  if block["quality"]["status"] == "adopted" and not block.get("usedBy"))


def lignes(records):
    out = []
    for block_id, (_, block) in sorted(records.items()):
        origin = block["origin"]
        out.append((block_id, block["name"], block["kind"], " ".join(block["capabilities"]),
                    " ".join(block["specIds"]), " ".join(block["usedBy"]), origin.get("repo") or "",
                    origin.get("path") or ""))
    return out


def graphe(records):
    edges = []
    for block_id, (_, block) in sorted(records.items()):
        edges += [{"from": block_id, "to": spec, "type": "specified-by"} for spec in sorted(block["specIds"])]
        edges += [{"from": block_id, "to": user, "type": "used-by"} for user in sorted(block["usedBy"])]
        edges += [{"from": block_id, "to": o["repo"], "type": "observed-in", "commitSha": o.get("commitSha")}
                  for o in block.get("observedIn") or [] if isinstance(o, dict) and o.get("repo")]
    nodes = [{"id": block_id, "kind": block["kind"], **statuts(block)} for block_id, (_, block) in sorted(records.items())]
    return {"nodes": nodes, "edges": edges}


def ecrire(records, out):
    out.mkdir(parents=True, exist_ok=True)
    base = out / BASE
    temp = out / (BASE + ".tmp")
    temp.unlink(missing_ok=True)
    with sqlite3.connect(temp) as c:
        c.execute(f"create virtual table blocks using fts5({', '.join(COLONNES)}, tokenize='unicode61 remove_diacritics 2')")
        c.executemany(f"insert into blocks values ({', '.join('?' * len(COLONNES))})", lignes(records))
    c.close()
    temp.replace(base)
    (out / GRAPHE).write_text(json_text(graphe(records)), encoding="utf-8")


def contenu(base):
    try:
        with sqlite3.connect(f"file:{base}?mode=ro", uri=True) as c:
            rows = c.execute(f"select {', '.join(COLONNES)} from blocks order by id").fetchall()
        c.close()
    except sqlite3.Error as exc:
        raise IndexStale(f"Index illisible : {base.name} ({exc}).") from exc
    return [tuple(r) for r in rows]


def index(records, out, check):
    out = Path(out)
    attendu_graphe = json_text(graphe(records))
    if check:
        ecarts = []
        if not (out / BASE).is_file():
            ecarts.append(f"{BASE} absent")
        elif contenu(out / BASE) != lignes(records):
            ecarts.append(f"{BASE} périmé")
        if not (out / GRAPHE).is_file():
            ecarts.append(f"{GRAPHE} absent")
        elif (out / GRAPHE).read_text(encoding="utf-8") != attendu_graphe:
            ecarts.append(f"{GRAPHE} périmé")
        if ecarts:
            raise IndexStale("Index du catalogue à reconstruire (bbctl index) : " + ", ".join(ecarts) + ".")
    else:
        ecrire(records, out)
    return {"blocks": len(records), "out": str(out), "check": check,
            "graphSha256": hashlib.sha256(attendu_graphe.encode()).hexdigest()}


def chercher(out, query, limit=20):
    base = Path(out) / BASE
    if not base.is_file():
        raise GraphUnavailable(f"Index du catalogue indisponible : {base} (bbctl index --out).")
    termes = [t for t in query.replace('"', " ").split() if t]
    expression = " ".join(f'"{t}"*' for t in termes)
    with sqlite3.connect(f"file:{base}?mode=ro", uri=True) as c:
        rows = c.execute("select id, name, kind, repo, path from blocks where blocks match ? order by rank, id limit ?",
                         (expression, limit)).fetchall()
    c.close()
    return {"results": [{"block": r[0], "name": r[1], "kind": r[2], "repo": r[3] or None, "path": r[4] or None}
                        for r in rows]}


def lire_recu(path):
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
        if isinstance(data, dict):
            return data
    return {}
