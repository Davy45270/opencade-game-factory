"""SBOM CycloneDX 1.5 des dépendances Python déclarées."""

import re
import uuid
from urllib.parse import quote

from tools.core.catalog import InvalidJSON, json_text, write_json
from tools.core.exit_codes import ExitCode
from tools.publish.delivery import output_path


PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([A-Za-z0-9][A-Za-z0-9.!+_-]*)")


def sbom(root, args):
    components = {}
    requirements = root / "requirements.txt"
    for number, line in enumerate(requirements.read_text(encoding="utf-8").splitlines(), 1):
        entry = line.partition("#")[0].strip()
        if not entry:
            continue
        match = PIN.fullmatch(entry)
        if not match:
            raise InvalidJSON(f"Dépendance non épinglée ou illisible à la ligne {number}.")
        name, version = match.groups()
        normalized = re.sub(r"[-_.]+", "-", name.lower())
        purl = f"pkg:pypi/{normalized}@{quote(version, safe='')}"
        if normalized in components and components[normalized]["version"] != version:
            raise InvalidJSON(f"Plusieurs versions déclarées pour {normalized}.")
        components[normalized] = {"type": "library", "name": name, "version": version,
                                  "purl": purl, "bom-ref": purl}
    project = "opencade-asset-registry"
    document = {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
                "metadata": {"component": {"name": project, "type": "application", "bom-ref": project}},
                "components": [components[name] for name in sorted(components)],
                "dependencies": [{"ref": project, "dependsOn": sorted(row["bom-ref"] for row in components.values())}]}
    document["serialNumber"] = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, json_text(document))}"
    destination = output_path(root, args.out, kind="sbom")
    if not args.dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_json(destination, document)
    return ExitCode.OK, {"ok": True, "path": str(destination), "components": len(components),
                         "serialNumber": document["serialNumber"]}
