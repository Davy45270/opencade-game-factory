"""Rapport en lecture seule des doublons entre dépôts."""

import hashlib
from collections import defaultdict
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

from tools.core.catalog import CatalogueScopeError

from .search import read_graph

NAME_SEPARATORS = str.maketrans("", "", "_-()")


def add_group(groups, reason, nodes, evidence):
    repos = sorted({node["repo"] for node in nodes})
    if len(repos) >= 2:
        groups.append({
            "reason": reason,
            "members": sorted({node["id"] for node in nodes}),
            "repos": repos,
            "evidence": evidence,
        })


def source_hash(root, source_file):
    relative = Path(source_file)
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root):
        raise CatalogueScopeError("Fichier source graphify hors de la racine déclarée.")
    if path.is_file():
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()
    return None


def duplicates(graph_path, roots, min_similarity):
    nodes, graph_digest = read_graph(graph_path)
    roots = {repo: root.resolve() for repo, root in roots.items()}
    hashes, names = defaultdict(list), defaultdict(list)
    file_hashes = {}
    for node in nodes:
        name = node["label"].casefold().translate(NAME_SEPARATORS).strip()
        if name:
            names[name].append(node)
        repo = node["repo"]
        if repo in roots:
            key = (repo, node["source_file"])
            if key not in file_hashes:
                file_hashes[key] = source_hash(roots[repo], node["source_file"])
            if file_hashes[key] is not None:
                hashes[file_hashes[key]].append(node)

    groups = []
    for digest, members in sorted(hashes.items()):
        add_group(groups, "same-hash", members, {"sha256": digest})
    for name, members in sorted(names.items()):
        add_group(groups, "similar-name", members, {"names": [name], "similarity": 1.0})

    if min_similarity < 1:
        # Un rapprochement par paire évite de regrouper des noms par transitivité.
        for first, second in combinations(sorted(names), 2):
            matcher = SequenceMatcher(None, first, second, autojunk=False)
            if matcher.real_quick_ratio() < min_similarity or matcher.quick_ratio() < min_similarity:
                continue
            similarity = matcher.ratio()
            if similarity >= min_similarity:
                add_group(groups, "similar-name", names[first] + names[second],
                          {"names": [first, second], "similarity": similarity})
    return {"groups": groups, "graphSha256": graph_digest}
