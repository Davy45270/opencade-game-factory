"""Lien brique → spécifications REG-003 (BB-001 E179, graphe brique → spécifications → dépôts consommateurs).

Chaque dépôt consommateur (premier segment de `usedBy`) dont la spec existe au registre de l'usine donne
`SPEC-<PROJET>` ; un lien déjà présent (posé à la main) n'est jamais retiré ; un dépôt sans spec est signalé.
"""

from tools.core.catalog import read_json

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
