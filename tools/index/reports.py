"""Rapports de découverte déterministes."""

from collections import Counter, defaultdict
from html import escape

from tools.core.catalog import write_json, write_text

TITLES = {
    "migration": "Migration des dépôts",
    "exceptions": "Fichiers illisibles",
    "coverage": "Couverture des formats",
    "licenses-unknown": "Licences inconnues",
    "orphans": "Assets orphelins",
    "scan-limits": "Limites du scan",
}


def _table(headers, rows):
    def cell(value):
        if value is None:
            return "—"
        return escape(str(value), quote=False).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(map(cell, row)) + " |" for row in rows),
    ])


def _file_rows(entries):
    return [(entry["repo"], entry["commit"], entry["path"], entry["reason"]) for entry in entries]


def _files(entries):
    return _table(("Dépôt", "Commit", "Chemin", "Motif"), _file_rows(entries))


def coverage(rows):
    counts = defaultdict(Counter)
    excluded = defaultdict(Counter)
    for row in rows:
        kind, status = row["format"], row["status"]
        counts[kind][status] += 1
        counts[kind]["found"] += 1
        if status == "excluded":
            excluded[kind][row["reason"]] += 1
    return [{"format": kind, **{key: counter[key] for key in
             ("found", "imported", "exception", "excluded", "unsupported", "examined")},
             "exclusionReasons": dict(sorted(excluded[kind].items()))}
            for kind, counter in sorted(counts.items())]


def _repo_markdown(repositories):
    parts = []
    for repo in repositories:
        copies = repo["copies"]
        parts.extend([
            f"## {repo['name']}",
            "Copies divergentes." if repo["divergent"] else "",
            _table(("Fournisseur", "Branche", "Commit", "Date", "Erreur"),
                   [(copy["provider"], copy.get("branch"), copy.get("commit"),
                     copy.get("date"), copy.get("error")) for copy in copies]),
        ])
        tags = [(copy["provider"], tag["name"], tag["commit"]) for copy in copies for tag in copy.get("tags", [])]
        if tags:
            parts.append(_table(("Fournisseur", "Tag", "Commit"), tags))
    return "\n\n".join(filter(None, parts))


def emit(root, repositories, rows, exceptions, assets, exclusions, manifests, sheet_limits=(), sheets=()):
    reports = root / "generated" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    formats = coverage(rows)
    unsupported = [row for row in rows if row["status"] == "unsupported"]
    excluded = [row for row in rows if row["status"] == "excluded"]
    missing_licenses = [{"id": asset["id"], "locations": asset["files"]["locations"]}
                        for asset in assets if asset["license"] == "unknown"]
    missing_sheets = [{"id": sheet["id"], "locations": sheet["files"]["locations"]}
                      for sheet in sorted(sheets, key=lambda item: item["id"]) if sheet["license"] == "unknown"]
    audio = [row for row in rows if row.get("durationUnknown")]
    family_counts = Counter(row["family"] for row in rows if row["status"] == "imported")
    orphan_ids = sorted(asset["id"] for asset in assets
                        if not any(usage["status"] == "active" for usage in asset["usages"]))
    limits = [
        "Seuls les blobs des commits Git de référence et des releases demandées sont lus. "
        "Les fichiers et modifications non commités sont invisibles.",
        "Les blobs de plus de 64 Mio figurent en exception avec le motif too-large.",
        "Aseprite est lu par en-tête. Les polices WOFF/WOFF2 et les conteneurs audio sont lus "
        "partiellement. Les shaders sont reconnus comme texte, sans compilation.",
        "Les vignettes et empreintes concernent les images matricielles lisibles par Pillow "
        "et représentent le premier cadre des animations.",
        "La couverture des modules de dessin utilise des motifs textuels. Les appels dynamiques "
        "et la sémantique des chaînes JavaScript ne sont pas interprétés.",
    ]
    outputs = {
        "migration": (
            {"repositories": repositories, "byFamily": dict(sorted(family_counts.items())),
             "buildManifests": manifests},
            _repo_markdown(repositories) + "\n\n" + _table(
                ("Famille", "Fichiers importés"), sorted(family_counts.items()))
            + "\n\n## Manifests de build\n\n" + _table(
                ("Dépôt", "Commit", "Chemin"), [(m["repo"], m["commit"], m["path"]) for m in manifests]),
        ),
        "exceptions": (exceptions, _files(exceptions)),
        "coverage": (
            {"formats": formats, "unsupported": unsupported, "excluded": excluded},
            _table(("Format", "Trouvés", "Importés", "Exceptions", "Exclus", "Non couverts", "Examinés sans asset", "Motifs"),
                   [(row["format"], row["found"], row["imported"], row["exception"], row["excluded"],
                     row["unsupported"], row["examined"], ", ".join(f"{reason} ({n})" for reason, n in row["exclusionReasons"].items()))
                    for row in formats]) + "\n\n## Non couverts\n\n" + _files(unsupported)
            + "\n\n## Exclus\n\n" + _files(excluded),
        ),
        "licenses-unknown": (
            {"assets": missing_licenses, "sheets": missing_sheets},
            _table(("Asset", "Dépôt", "Chemin"), [(asset["id"], loc.get("repo"), loc.get("path"))
                   for asset in missing_licenses for loc in asset["locations"] or [{}]])
            + "\n\n## Planches\n\n" + _table(("Planche",), [(item["id"],) for item in missing_sheets]),
        ),
        "orphans": ({"assets": orphan_ids}, _table(("Asset",), [(asset_id,) for asset_id in orphan_ids])),
        "scan-limits": (
            {"exclusions": [{"reason": reason, "count": sum(row["reason"] == reason for row in excluded)}
                            for reason in exclusions], "excluded": excluded, "unsupported": unsupported,
             "audioDurationUnknown": audio, "limits": limits, "sheets": list(sheet_limits)},
            "\n".join(f"- {limit}" for limit in limits)
            + "\n\n" + _table(("Exclusion", "Fichiers"), [(reason, sum(row["reason"] == reason for row in excluded))
                                                          for reason in exclusions])
            + "\n\n## Fichiers exclus\n\n" + _files(excluded)
            + "\n\n## Formats non couverts\n\n" + _files(unsupported)
            + "\n\n## Planches\n\n" + _files(sheet_limits)
            + "\n\n## Durées audio inconnues\n\n" + _files(audio),
        ),
    }
    for name, (data, markdown) in outputs.items():
        write_json(reports / f"{name}.json", data)
        write_text(reports / f"{name}.md", f"# {TITLES[name]}\n\n{markdown.strip()}\n")
