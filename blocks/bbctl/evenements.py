"""Événements FactoryEvent v1.1 de bbctl vers la Tour (OPS-001, BB-001 T14).

Même dépôt opt-in que specctl (specs/specctl/tour.py) : rien sans TOWER_DIR ou TOWER_TRACE_ID, TOWER_DESACTIVE=1 coupe
tout, une erreur n'interrompt jamais la commande. Corrélation par traceId et buildingBlockRefs.
"""

import hashlib
import json
import os

from specs.specctl import tour


def fabriquer(typ, etat, project, blocks, meta, fait, commit=None, specs=()):
    tr = tour.trace()
    brut = ":".join(["bbctl", typ, project, json.dumps(blocks), fait or "", tr or ""])
    event_id = "bbctl:" + hashlib.sha256(brut.encode("utf-8")).hexdigest()[:32]
    ev = {"schemaVersion": 1.1, "eventId": event_id, "occurredAt": tour.utc(), "source": "bbctl",
          "portfolioId": "homelab", "projectId": str(project or "")[:128] or "inconnu", "workflowId": "bbctl",
          "workflowVersion": typ.split(".", 1)[1], "runId": event_id, "eventType": typ, "status": etat,
          "evidence": [], "metadata": meta, "agentId": (os.environ.get("TOWER_AGENT_ID") or "bbctl")[:128]}
    if blocks:
        ev["buildingBlockRefs"] = list(blocks)[:64]
    if specs:
        ev["specRefs"] = sorted(set(specs))[:64]                 # lien REG-003 (BB-10)
    if commit:
        ev["commitSha"] = commit
    if tr:
        ev["traceId"] = tr
    return ev


def emettre(typ, etat, project, blocks, meta, fait, commit=None, specs=()):
    try:
        return tour.deposer([fabriquer(typ, etat, project, blocks, meta, fait, commit, specs)])
    except Exception:
        return False
