"""Recherche en lecture seule dans un export node-link de graphify."""

import hashlib
from collections import defaultdict
from datetime import datetime, timezone

from tools.core.catalog import CatalogueScopeError, InvalidJSON, parse_json, write_json

from .registry import read_catalogue


class GraphUnavailable(ValueError):
    pass


def _texte(node, key):
    return isinstance(node.get(key), str) and node[key]


def read_graph(path, skipped=None):
    """Nœuds localisés (id, label, repo, source_file). Un nœud sans id ou sans label rend le graphe indisponible ;
    un nœud sans source_file (ou sans repo) est une référence externe — un import, `FastMCP`, `Any` : 519 nœuds sur
    57 732 dans le graphe réel du 22/11 —, pas une brique candidate : il est écarté et compté dans `skipped`."""
    try:
        raw = path.read_bytes()
        graph = parse_json(raw)
        if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
            raise InvalidJSON("Liste nodes absente.")
        nodes = []
        for node in graph["nodes"]:
            if not isinstance(node, dict) or not (_texte(node, "id") and _texte(node, "label")):
                raise InvalidJSON("Nœud graphify mal formé.")
            if _texte(node, "repo") and _texte(node, "source_file"):
                nodes.append(node)
            elif skipped is not None:
                skipped.append(node["id"])
        return nodes, hashlib.sha256(raw).hexdigest()
    except (OSError, InvalidJSON) as exc:
        raise GraphUnavailable(f"Graphe graphify indisponible : {exc}") from exc


def search(blocks, args, graph_path):
    skipped = []
    nodes, digest = read_graph(graph_path, skipped)
    by_origin = defaultdict(list)
    for _, block in read_catalogue(blocks / "catalog").values():
        origin = block["origin"]
        if "repo" in origin:
            by_origin[origin["repo"], origin["path"]].append(block)

    terms = args.query.casefold().split()
    results = []
    for node in nodes:
        repo = node["repo"]
        source_file = node["source_file"]
        if args.repo and repo != args.repo:
            continue
        searchable = " ".join((node["id"], node["label"], repo, source_file)).casefold()
        if not all(term in searchable for term in terms):
            continue
        matching = by_origin[repo, source_file] or [None]
        for block in matching:
            if args.kind and (block is None or block["kind"] != args.kind):
                continue
            results.append({
                "graphNode": node["id"],
                "label": node["label"],
                "repo": repo,
                "sourceFile": source_file,
                "location": node.get("source_location"),
                "block": block["id"] if block else None,
            })

    if args.receipt:
        receipt = args.receipt
        target = receipt.resolve()
        if target == graph_path.resolve() or (
            receipt.exists() and receipt.samefile(graph_path)
        ):
            raise CatalogueScopeError("Le reçu ne peut pas remplacer le graphe.")
        data_directories = ("catalog", "decisions", "evaluations")
        if any(target.is_relative_to((blocks / name).resolve()) for name in data_directories):
            raise CatalogueScopeError("Le reçu doit être placé hors des dossiers de données du registre.")
        write_json(receipt, {
            "query": args.query, "scope": args.scope, "repo": args.repo, "kind": args.kind,
            "graphSha256": digest,
            "results": list(dict.fromkeys(result["graphNode"] for result in results)),
            "at": datetime.now(timezone.utc).isoformat(),
        })
    return {"results": results, "externalReferencesSkipped": len(skipped)}
