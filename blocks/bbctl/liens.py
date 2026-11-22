"""Lien brique → spécifications REG-003 (BB-001 E179, graphe brique → spécifications → dépôts consommateurs).

Chaque dépôt consommateur (premier segment de `usedBy`) dont la spec existe au registre de l'usine donne
`SPEC-<PROJET>` ; un lien déjà présent (posé à la main) n'est jamais retiré ; un dépôt sans spec est signalé.
"""

from tools.core.catalog import InvalidJSON, read_json

from .adoption import write_block


def spec_projects(root):
    projects = {}
    for path in sorted((root / "specs" / "registry").glob("SPEC-*.json")):
        record = read_json(path)
        if isinstance(record, dict) and isinstance(record.get("project"), str):
            projects[record["project"]] = record["id"]
    return projects


def link_specs(blocks, records, dry_run):
    projects = spec_projects(blocks.parent)
    linked, without = 0, set()
    for block_id, (path, block) in sorted(records.items()):
        wanted = set(block.get("specIds") or [])
        for consumer in block.get("usedBy") or []:
            repo = str(consumer).split("/", 1)[0]
            if repo in projects:
                wanted.add(projects[repo])
            else:
                without.add(repo)
        if sorted(wanted) == list(block.get("specIds") or []):
            continue
        linked += 1
        if not dry_run:
            write_block(blocks, path, {**block, "specIds": sorted(wanted)}, "link-specs", None)
    return {"dryRun": dry_run, "linked": linked, "specs": sorted(set(projects.values())), "withoutSpec": sorted(without)}


# --- E209 : lien par identifiant vers le module assets (catalogues Asset et EXT-001 niveaux de l'usine) -------------

def _repo_of(url):
    return str(url or "").rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") or None


def catalogue_assets(root):
    """{identifiant: {catalog, repo, path, category, format, license}} relu dans catalog/assets et catalog/levels."""
    out = {}
    for path in sorted((root / "catalog" / "assets").glob("*.json")):
        record = read_json(path)
        for loc in (record.get("files") or {}).get("locations") or []:
            if loc.get("status", "active") == "active" and loc.get("repo") and loc.get("path"):
                out[record["id"]] = {"id": record["id"], "catalog": "assets", "repo": loc["repo"], "path": loc["path"],
                                     "category": record.get("category"), "format": record.get("format"),
                                     "license": record.get("license")}
                break
        else:
            out.setdefault(record["id"], {"id": record["id"], "catalog": "assets", "repo": None, "path": None,
                                          "category": record.get("category"), "format": record.get("format"),
                                          "license": record.get("license")})
    for path in sorted((root / "catalog" / "levels").glob("*.json")):
        record = read_json(path)
        origin = record.get("origin") or {}
        out[record["id"]] = {"id": record["id"], "catalog": "levels", "repo": _repo_of(origin.get("sourceRepo")),
                             "path": origin.get("sourcePath"), "category": record.get("kind"),
                             "format": record.get("format"), "license": origin.get("license")}
    return out


def link_assets(blocks, records, dry_run):
    catalogue = catalogue_assets(blocks.parent)
    par_depot = {}
    for asset in catalogue.values():
        if asset["repo"] and asset["path"]:
            par_depot.setdefault(asset["repo"], []).append(asset)
    linked, total = 0, 0
    for block_id, (path, block) in sorted(records.items()):
        origin = block["origin"]
        wanted = set(block.get("assetIds") or [])                 # un lien posé à la main n'est jamais retiré
        if origin.get("repo") and origin.get("path"):
            prefix = origin["path"].rstrip("/") + "/"
            wanted |= {a["id"] for a in par_depot.get(origin["repo"], []) if a["path"].startswith(prefix)}
        total += len(wanted)
        if sorted(wanted) == list(block.get("assetIds") or []):
            continue
        linked += 1
        if not dry_run:
            write_block(blocks, path, {**block, "assetIds": sorted(wanted)}, "link-assets", None)
    return {"dryRun": dry_run, "linked": linked, "links": total, "catalogued": len(catalogue)}


def assets_of(blocks, records, block_id):
    if block_id not in records:
        raise InvalidJSON(f"Brique absente du catalogue : {block_id}.")
    catalogue = catalogue_assets(blocks.parent)
    ids = records[block_id][1].get("assetIds") or []
    return {"block": block_id, "assets": [catalogue[i] for i in ids if i in catalogue],
            "unresolved": [i for i in ids if i not in catalogue]}


def check_asset_links(root, records):
    wanted = [(b, a) for b, (_, block) in sorted(records.items()) for a in block.get("assetIds") or ()]
    if not wanted:
        return "aucun"
    known = catalogue_assets(root)
    broken = [f"{b} -> {a}" for b, a in wanted if a not in known]
    if broken:
        raise InvalidJSON("Lien d'asset non résolu : " + ", ".join(broken))
    return "verifies"
