"""SBOM CycloneDX 1.5 du catalogue BB-001 (BB-09, § 9 ; matrice E210, E222).

Un composant par brique (bom-ref = identifiant BB), avec sa version et son purl SEULEMENT quand la version est connue,
sa licence SPDX quand elle l'est ; un composant `application` par dépôt consommateur, dont les dépendances sont les
briques qu'il utilise. Ce qui n'est pas résolu est listé au rapport (unversioned, licenseUnknown), jamais inventé.
Déterministe : même catalogue, mêmes octets (numéro de série dérivé du contenu). Le scan de vulnérabilités est fait par
trivy sur ce fichier, dans la CI de l'usine (.woodpecker/modules.yml, étape scan-briques).
"""

import uuid
from urllib.parse import quote

from tools.core.catalog import json_text, write_json

from .index import statuts

PURL = {"npm": "npm", "pypi": "pypi", "cargo": "cargo", "go": "golang", "docker": "docker"}


def purl(ecosystem, name, version):
    kind = PURL.get(ecosystem)
    if not kind or not version:
        return None
    if ecosystem == "npm" and name.startswith("@"):
        scope, _, base = name.partition("/")
        return f"pkg:npm/{quote(scope, safe='')}/{quote(base, safe='')}@{quote(version, safe='')}"
    return f"pkg:{kind}/{quote(name, safe='/')}@{quote(version, safe='')}"


def sbom(records, out):
    components, users, unversioned, unknown = [], {}, [], []
    for block_id, (_, block) in sorted(records.items()):
        origin = block["origin"]
        ecosystem = (block.get("discovery") or {}).get("ecosystem")
        version = origin.get("version")
        externe = ecosystem in PURL
        component = {"type": "container" if ecosystem == "docker" else "library", "bom-ref": block_id,
                     "name": block["name"]}
        if version:
            component["version"] = version
        p = purl(ecosystem, block["name"], version)
        if p:
            component["purl"] = p
        if origin["licenseSpdx"] != "UNKNOWN":
            component["licenses"] = [{"license": {"id": origin["licenseSpdx"]}}]
        else:
            unknown.append(block_id)
        if externe and not version:
            unversioned.append(block_id)
        s = statuts(block)
        component["properties"] = [{"name": "bbctl:kind", "value": block["kind"]},
                                   {"name": "bbctl:validation", "value": s["validation"]},
                                   {"name": "bbctl:consumption", "value": s["consumption"]}]
        components.append(component)
        for user in block["usedBy"]:
            users.setdefault(user.split("/")[0], set()).add(block_id)
    applications = [{"type": "application", "bom-ref": f"repo:{repo}", "name": repo} for repo in sorted(users)]
    document = {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
                "metadata": {"component": {"type": "application", "bom-ref": "opencade-blocks",
                                           "name": "opencade-blocks"}},
                "components": components + applications,
                "dependencies": [{"ref": "opencade-blocks", "dependsOn": [a["bom-ref"] for a in applications]}]
                + [{"ref": f"repo:{repo}", "dependsOn": sorted(ids)} for repo, ids in sorted(users.items())]}
    document["serialNumber"] = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, json_text(document))}"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, document)
    return {"path": str(out), "components": len(components), "consumers": len(applications),
            "unversioned": unversioned, "licenseUnknown": unknown}
