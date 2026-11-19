"""Preuves des images dont la génération est déclarée dans le registre."""

import hashlib
import re
from collections import defaultdict

from tools.core.catalog import InvalidJSON, parse_json
from tools.discovery import formats, references
from tools.discovery.importer import MAX_BLOB
from tools.extract.sheets import link_region
from tools.publish import licenses

IMAGE_FORMATS = formats.RASTER.keys() | {"svg"}
SPDX_LINE = re.compile(rb"(?m)^\s*SPDX-License-Identifier:[ \t]*([^\r\n]+)")


def declarations(tree, entries):
    if not entries:
        return {}
    return {path: matches for path in tree if formats.extension(path) in IMAGE_FORMATS
            if (matches := [(generator, tuple(sorted(set(mentions)))) for pattern, generator, mentions in entries
                            if references.match_path_pattern(pattern, path)])}


def _read(snapshot, batch, path):
    blob = snapshot.tree.get(path)
    if blob is not None and not blob.symlink and blob.size <= MAX_BLOB:
        return batch.read(blob, MAX_BLOB)
    return None


def _repository_license(snapshot, batch):
    raw = _read(snapshot, batch, "LICENSE")
    from_text = licenses.from_text(raw)
    declared = {match.decode("utf-8", errors="replace").strip()
                for match in SPDX_LINE.findall(raw or b"")}
    if from_text:
        declared.add(from_text)
    from_file = next(iter(declared)) if len(declared) == 1 else None
    if declared and not licenses.explicit_spdx(from_file):
        return None
    raw = _read(snapshot, batch, "package.json")
    try:
        package = parse_json(raw) if raw is not None else None
    except InvalidJSON:
        package = None
    from_package = package.get("license") if isinstance(package, dict) else None
    if from_file:
        if from_package is not None and from_package != from_file:
            return None
        return from_file, "LICENSE"
    if licenses.explicit_spdx(from_package):
        return from_package, "package.json"
    return None


def _prove(snapshot, batch, entries, repository_license, generators):
    if len(set(entries)) != 1:
        return None, "generated-resource-ambiguous-declaration"
    generator, mentions = entries[0]
    if generator not in generators:
        raw = _read(snapshot, batch, generator)
        generators[generator] = (raw, hashlib.sha256(raw).hexdigest()) if raw is not None else (None, None)
    raw, digest = generators[generator]
    if raw is None:
        return None, "generated-resource-generator-unavailable"
    if not all(fragment.encode("utf-8", errors="surrogatepass") in raw for fragment in mentions):
        return None, "generated-resource-mention-missing"
    if repository_license is None:
        return None, "generated-resource-repository-license-unknown"
    return {"path": generator, "commit": snapshot.commit, "sha256": digest}, None


def apply(snapshots, target, git):
    observations = defaultdict(list)
    limits = []
    for snapshot in snapshots:
        paths = snapshot.generated_paths.keys() & snapshot.indexed.keys()
        proofs = {}
        repository_license = None
        if paths:
            with git.batch(snapshot.mirror) as batch:
                repository_license = _repository_license(snapshot, batch)
                generators = {}
                for path in sorted(paths):
                    proof, reason = _prove(snapshot, batch, snapshot.generated_paths[path], repository_license,
                                           generators)
                    proofs[path] = proof
                    if reason:
                        limits.append({"repo": snapshot.repo, "commit": snapshot.commit,
                                       "path": path, "reason": reason})
        release = all(member[2] for member in snapshot.members)
        for path, ids in snapshot.indexed.items():
            for asset_id in ids:
                if (path in paths or "generator" in target.assets[asset_id]["provenance"]) and (
                        target.version_at(asset_id, snapshot, path) == target.assets[asset_id]["version"]):
                    observations[asset_id].append((release, snapshot, path, proofs.get(path), repository_license))

    for asset_id, entries in observations.items():
        asset = target.assets[asset_id]
        if asset["status"] == "published":
            continue
        _, snapshot, path, proof, repository_license = min(
            entries, key=lambda entry: (entry[0], entry[2] not in entry[1].generated_paths, entry[1].repo, entry[2]))
        if proof is None:
            asset["license"] = "unknown"
            asset.pop("licenseEvidence", None)
            if asset.get("publicExport") == "allowed":
                asset.pop("publicExport")
            asset["status"] = "needs-review"
        else:
            value, license_path = repository_license
            licenses.assign(asset, value, "license-file", f"{license_path}@{snapshot.commit}",
                            "Licence du dépôt identifiée au commit importé.")
            if asset["status"] == "needs-review":
                asset["status"] = "active"
        asset["provenance"] = {"type": "repo-file", "author": "unknown",
                               "evidence": [f"{snapshot.repo}@{snapshot.commit}:{path}"]}
        if proof is not None:
            asset["provenance"].update(type="code-generated", generator=proof)
        link_region(target, asset, None, None, False, None)
        target.changed.add(asset_id)
    return limits
