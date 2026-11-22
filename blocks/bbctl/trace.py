"""Graphe et traçabilité brique → exigences → code → tests → SBOM → releases (matrice E179, E100).

Les releases d'un dépôt sont ses tags atteignables depuis le commit lu par `bbctl discover` (blocks/discovery.json) ;
le SBOM des briques (`bbctl sbom`) porte un composant par brique, de bom-ref égal à son identifiant. Un maillon absent
est DIT dans `missing`, jamais inventé.
"""

import subprocess

from tools.core.catalog import InvalidJSON, read_json


def releases(directory, commit):
    """Tags atteignables depuis `commit`, triés par nom, avec le commit qu'ils désignent."""
    out = subprocess.run(["git", "-C", str(directory), "for-each-ref", "--merged", commit, "refs/tags",
                          "--format=%(refname:short) %(objectname) %(*objectname)"], capture_output=True, text=True)
    if out.returncode:
        return []
    rows = []
    for line in out.stdout.splitlines():
        tag, obj, peeled = (line.split(" ") + ["", ""])[:3]
        rows.append({"tag": tag, "commitSha": peeled or obj})
    return sorted(rows, key=lambda r: r["tag"])


def etat_releases(blocks):
    path = blocks / "discovery.json"
    state = read_json(path) if path.is_file() else {}
    return {repo: v.get("releases") or [] for repo, v in sorted(state.items()) if isinstance(v, dict)}


def aretes(records, rels):
    edges = []
    for block_id, (_, block) in sorted(records.items()):
        repo = block["origin"].get("repo")
        tests = (block.get("analysis") or {}).get("tests") or []
        edges += [{"from": block_id, "to": f"test:{repo}/{t}", "type": "tested-by"} for t in tests]
        edges.append({"from": block_id, "to": f"sbom:{block_id}", "type": "in-sbom"})
    for repo, rows in rels.items():
        edges += [{"from": repo, "to": f"release:{repo}@{r['tag']}", "type": "released-as", "commitSha": r["commitSha"]}
                  for r in rows]
    return edges


def trace(records, blocks, block_id):
    if block_id not in records:
        raise InvalidJSON(f"Brique absente du catalogue : {block_id}.")
    block = records[block_id][1]
    origin = block["origin"]
    specs = sorted(block.get("specIds") or [])
    requirements = []
    for spec in specs:
        path = blocks.parent / "specs" / "registry" / f"{spec}.json"
        if path.is_file():
            requirements += [r["id"] for r in read_json(path).get("requirements") or []]
    repo = origin.get("repo")
    tests = [f"{repo}/{t}" for t in (block.get("analysis") or {}).get("tests") or []]
    rels = etat_releases(blocks)
    repos = sorted({str(u).split("/", 1)[0] for u in block.get("usedBy") or []} | ({repo} if repo else set()))
    releases_ = [{"release": f"{r}@{x['tag']}", "commitSha": x["commitSha"]} for r in repos for x in rels.get(r, [])]
    code = {"repo": repo, "path": origin.get("path"), "commitSha": origin.get("commitSha")} if repo else None
    chaine = {"requirements": sorted(requirements), "specs": specs, "code": code, "tests": tests,
              "sbom": {"bomRef": block_id}, "consumers": sorted(block.get("usedBy") or []), "releases": releases_}
    missing = [k for k in ("requirements", "specs", "code", "tests", "consumers", "releases") if not chaine[k]]
    return {"block": block_id, **chaine, "missing": missing}
