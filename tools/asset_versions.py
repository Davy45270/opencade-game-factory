"""Historique de contenu des fiches d’assets, y compris les fiches L1–L3."""


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


def archive_publication(asset):
    registry = asset["files"].get("registry")
    if asset["status"] == "published" or registry:
        fields = ("status", "license", "licenseEvidence", "publicExport", "provenance")
        publication = {field: asset[field] for field in fields if field in asset}
        if registry:
            publication["registry"] = registry
        asset["versions"][version_number(asset) - 1].setdefault("publication", publication)


def append(asset, digest, *, current, commit, date):
    versions = asset["versions"]
    number = len(versions) + 1
    versions[-1]["nextVersion"] = number
    versions.append({"version": number, "sha256": digest, "previousVersion": number - 1,
                     "nextVersion": None, "commit": commit, "date": date})
    if current:
        asset.update(version=number, sha256=digest)
    return number


def problems(asset):
    versions = history(asset)
    current = version_number(asset)
    if current > len(versions) or versions[current - 1]["sha256"].lower() != asset["sha256"].lower():
        yield "La version courante doit désigner une entrée portant le SHA-256 de la fiche."
    for number, entry in enumerate(versions, 1):
        if (entry["version"], entry["previousVersion"], entry["nextVersion"]) != (
                number, number - 1 or None, number + 1 if number < len(versions) else None):
            yield f"Numéro ou liens incohérents pour l’entrée {number}."
    for record in (*asset["files"]["locations"], *asset["usages"]):
        if record.get("assetVersion", 1) > len(versions):
            yield "Un emplacement ou un usage désigne une version inconnue."
