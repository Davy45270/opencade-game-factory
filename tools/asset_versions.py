"""Historique de contenu des fiches d’assets, y compris les fiches L1–L3."""

from copy import deepcopy


def version_number(asset):
    return int(asset.get("version", 1))


def history(asset):
    if "versions" in asset:
        return asset["versions"]
    return [{"version": 1, "sha256": asset["sha256"], "previousVersion": None, "nextVersion": None}]


def initialize(asset):
    if "version" not in asset and "versions" not in asset:
        asset.update(version=1, versions=history(asset))
        return True
    return False


def publication_proof(asset, registry=None):
    fields = ("status", "license", "licenseEvidence", "publicExport", "provenance")
    publication = {field: deepcopy(asset[field]) for field in fields if field in asset}
    if registry:
        publication["registry"] = registry
    return publication


def archive_publication(asset):
    if asset["status"] == "published":
        entry = asset["versions"][version_number(asset) - 1]
        entry.setdefault("publication", publication_proof(asset))


def append(asset, digest, *, current, commit, date):
    versions = asset["versions"]
    number = len(versions) + 1
    versions[-1]["nextVersion"] = number
    versions.append({"version": number, "sha256": digest, "previousVersion": number - 1,
                     "nextVersion": None, "commit": commit, "date": date})
    if current:
        asset.update(version=number, sha256=digest)
    return number


def set_causality(versions, precedes):
    entries = {entry["version"]: entry for entry in versions}
    previous = {number: set() for number in entries}
    following = {number: set() for number in entries}
    states = {}
    for left, entry in entries.items():
        for right in range(left + 1, len(entries) + 1):
            a, b = entry.get("commit"), entries[right].get("commit")
            relation = precedes(a, b) if a and b and a != b else None
            if relation == -1:
                previous[right].add(left)
                following[left].add(right)
            elif relation == 1:
                previous[left].add(right)
                following[right].add(left)
            elif relation == 0:
                states[left] = states[right] = "incomparable"

    changed = False
    for number, entry in entries.items():
        before = previous[number] - set().union(*(previous[col] for col in previous[number]))
        after = following[number] - set().union(*(following[col] for col in following[number]))
        state = states.get(number)
        if state is None and (len(before) > 1 or len(after) > 1):
            state = "ambiguous"
        links = {"causalPrevious": next(iter(before)) if len(before) == 1 and not state else None,
                 "causalNext": next(iter(after)) if len(after) == 1 and not state else None}
        if state:
            links["causalOrder"] = state
        if any(entry.get(key) != value or key not in entry for key, value in links.items()):
            entry.update(links)
            changed = True
        if state is None and "causalOrder" in entry:
            del entry["causalOrder"]
            changed = True
    return changed


def problems(asset):
    versions = history(asset)
    current = version_number(asset)
    if current > len(versions) or versions[current - 1]["sha256"].lower() != asset["sha256"].lower():
        yield "La version courante doit désigner une entrée portant le SHA-256 de la fiche."
    for number, entry in enumerate(versions, 1):
        if (entry["version"], entry["previousVersion"], entry["nextVersion"]) != (
                number, number - 1 or None, number + 1 if number < len(versions) else None):
            yield f"Numéro ou liens incohérents pour l’entrée {number}."
        for field in ("causalPrevious", "causalNext"):
            if (linked := entry.get(field)) is not None and (linked == number or linked > len(versions)):
                yield f"Lien causal invalide pour l’entrée {number}."
        if entry.get("causalOrder") in {"incomparable", "ambiguous"} and any(
                entry.get(field) is not None for field in ("causalPrevious", "causalNext")):
            yield f"Liens causaux non nuls sur une entrée {number} sans ordre unique."
    for record in (*asset["files"]["locations"], *asset["usages"]):
        if record.get("assetVersion", 1) > len(versions):
            yield "Un emplacement ou un usage désigne une version inconnue."
