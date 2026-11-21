"""Événements de specctl pour la Control Tower (FactoryEvent v1.1) : `spec.resolved`, `spec.conflict` (resolve),
`spec.approved` (arbitrer) et `spec.outdated` (verify --from).

Émission OPT-IN et silencieuse :
  - seulement si `TOWER_DIR` ou `TOWER_TRACE_ID` est posé ; `TOWER_DESACTIVE=1` coupe tout ;
  - dossier = `TOWER_DIR`, sinon `$XDG_STATE_HOME/tower` (défaut `~/.local/state/tower`) ; il doit EXISTER : rien n'est créé ;
  - une ligne JSON ajoutée en une seule écriture O_APPEND à `inbox.jsonl` (fichier ordinaire seulement) ;
  - toute erreur est avalée : l'émission ne change jamais le code de sortie ni la sortie de `specctl`.
La Tower valide, déduplique (eventId déterministe) et range à l'ingestion."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

RE_ID = re.compile(r"[A-Za-z0-9._:/@+-]{1,128}")


def dossier() -> Path | None:
    if os.environ.get("TOWER_DESACTIVE") == "1":
        return None
    if os.environ.get("TOWER_DIR"):
        return Path(os.environ["TOWER_DIR"])
    if not os.environ.get("TOWER_TRACE_ID"):
        return None
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "tower"


def trace() -> str | None:
    t = os.environ.get("TOWER_TRACE_ID") or ""
    return t if RE_ID.fullmatch(t) else None


def utc() -> str:
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def evenement(project: str, code: int, payload: dict) -> dict | None:
    """FactoryEvent d'une résolution, ou None quand il n'y a rien à dire (projet inconnu, version absente)."""
    status = payload.get("status")
    if code == 0 and status == "ok":
        refs = sorted(f"{s['specId']}@{s['version']}" for s in payload.get("specs", []))
        typ, etat = "spec.resolved", "success"
        meta = {"registryDigest": payload.get("registryDigest"), "specs": len(refs)}
        fait = payload.get("registryDigest") or ""
    elif status == "arbitration-required":
        refs = [payload.get("specId")] if payload.get("specId") else []
        typ, etat = "spec.conflict", "blocked"
        meta = {"specId": payload.get("specId"), "versions": list(payload.get("versions") or [])}
        fait = json.dumps(meta, sort_keys=True)
    else:
        return None
    return fabriquer(typ, etat, project, refs, meta, fait, "resolve")


def fabriquer(typ: str, etat: str, project: str, refs: list, meta: dict, fait: str, commande: str) -> dict:
    """FactoryEvent v1.1. eventId déterministe : le même fait rejoué sous la même trace donne le même identifiant."""
    tr = trace()
    brut = ":".join(["specctl", typ, project, fait, tr or ""])
    event_id = "specctl:" + hashlib.sha256(brut.encode("utf-8")).hexdigest()[:32]
    ev = {"schemaVersion": 1.1, "eventId": event_id, "occurredAt": utc(), "source": "specctl",
          "portfolioId": "homelab", "projectId": str(project or "")[:128] or "inconnu", "workflowId": "specctl",
          "workflowVersion": commande, "runId": event_id, "eventType": typ, "status": etat,
          "evidence": [], "metadata": meta,
          "agentId": (os.environ.get("TOWER_AGENT_ID") or "specctl")[:128]}
    refs = [r for r in refs if isinstance(r, str) and RE_ID.fullmatch(r)]
    if refs:
        ev["specRefs"] = refs[:64]
    if tr:
        ev["traceId"] = tr
    return ev


def approbation(records: dict, code: int, payload: dict) -> list[dict]:
    """`spec.approved` : un arbitrage de version, ou un lifecycle passé à approved (refus et inconnus ne disent rien)."""
    if code != 0 or payload.get("status") != "ok" or "arbitration" not in payload:
        return []
    if payload["arbitration"] is None:
        spec_id = payload["specId"]
        record = records.get(spec_id) or {}
        meta = {"specId": spec_id, "lifecycle": "approved", "ref": payload.get("lifecycleRef")}
        return [fabriquer("spec.approved", "success", record.get("project"), [spec_id], meta,
                          json.dumps(meta, sort_keys=True), "statuer")]
    spec_id, arb = payload["specId"], payload["arbitration"]
    project = (records.get(spec_id) or {}).get("project")
    meta = {"specId": spec_id, "version": arb["version"], "ref": arb["ref"]}
    return [fabriquer("spec.approved", "success", project, [f"{spec_id}@{arb['version']}"], meta,
                      json.dumps(meta, sort_keys=True), "arbitrer")]


def peremptions(records: dict, payload: dict) -> list[dict]:
    """`spec.outdated` : une spec dont l'archive a changé depuis l'import, un événement par spec."""
    par_spec: dict[str, list[str]] = {}
    for o in payload.get("outdated") or []:
        par_spec.setdefault(o["specId"], []).append(o["path"])
    out = []
    for spec_id, paths in sorted(par_spec.items()):
        project = (records.get(spec_id) or {}).get("project")
        meta = {"specId": spec_id, "paths": sorted(paths)}
        out.append(fabriquer("spec.outdated", "failure", project, [spec_id], meta,
                             json.dumps(meta, sort_keys=True), "verify"))
    return out


def deposer(evs: list) -> bool:
    """Écrit les événements dans la boîte d'arrivée. Rend True si tout a été écrit. N'échoue jamais."""
    try:
        d = dossier()
        if d is None or not d.is_dir() or not evs:
            return False
        lignes = "".join(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n" for ev in evs)
        donnees = lignes.encode("utf-8")
        fd = os.open(d / "inbox.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK, 0o644)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return False
            return os.write(fd, donnees) == len(donnees)
        finally:
            os.close(fd)
    except Exception:
        return False


def emettre_resolution(project: str, code: int, payload: dict) -> bool:
    try:
        ev = evenement(project, int(code), payload)
    except Exception:
        return False
    return deposer([ev] if ev else [])


def emettre_approbation(records: dict, code: int, payload: dict) -> bool:
    try:
        return deposer(approbation(records, int(code), payload))
    except Exception:
        return False


def emettre_peremptions(records: dict, payload: dict) -> bool:
    try:
        return deposer(peremptions(records, payload))
    except Exception:
        return False


def verifications(records: dict, project: str, payload: dict) -> list[dict]:
    """`requirement.verified` : une exigence « faite » avec sa preuve (coverage), un événement par exigence."""
    record = next((r for r in records.values() if r.get("project") == project), None)
    if record is None:
        return []
    version = (record.get("arbitration") or {}).get("version") or (
        record["versions"][0]["version"] if len(record.get("versions", [])) == 1 else None)
    ref = f"{record['id']}@{version}" if version else record["id"]
    out = []
    for row in payload.get("requirements") or []:
        if row.get("status") != "faite" or not row.get("evidence"):
            continue
        meta = {"specId": record["id"], "requirementId": row["id"]}
        ev = fabriquer("requirement.verified", "success", project, [ref], meta,
                       json.dumps({**meta, **row["evidence"]}, sort_keys=True), "coverage")
        ev["evidence"] = [{"type": str(row["evidence"]["type"])[:64], "uri": str(row["evidence"]["ref"])[:512]}]
        out.append(ev)
    return out


def impact(records: dict, code: int, payload: dict) -> list[dict]:
    """`spec.impact-detected` : une spec a des projets consommateurs à prévenir."""
    if code != 0 or not payload.get("projects"):
        return []
    spec_id = payload["specId"]
    ref = f"{spec_id}@{payload['version']}" if payload.get("version") else spec_id
    meta = {"specId": spec_id, "projects": payload["projects"],
            "consumers": sorted(c["specId"] for c in payload["consumers"])}
    project = (records.get(spec_id) or {}).get("project")
    return [fabriquer("spec.impact-detected", "success", project, [ref], meta, json.dumps(meta, sort_keys=True),
                      "impact")]


def verrou(records: dict, code: int, payload: dict) -> list[dict]:
    """`spec.outdated` : le verrou d'une PR ne correspond plus à la résolution courante (T03)."""
    if payload.get("status") != "outdated":
        return []
    meta = {"reasons": payload["reasons"], "locked": {k: payload["locked"].get(k) for k in ("specId", "version")}}
    ev = fabriquer("spec.outdated", "failure", payload["project"],
                   [f"{s['specId']}@{s['version']}" for s in payload["current"]], meta,
                   json.dumps({**meta, "commit": payload["commitSha"]}, sort_keys=True), "verify")
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", payload["commitSha"]):
        ev["commitSha"] = payload["commitSha"]
    return [ev]


def _sur(fonction, *args) -> bool:
    try:
        return deposer(fonction(*args))
    except Exception:
        return False


def emettre_verifications(records: dict, project: str, payload: dict) -> bool:
    return _sur(verifications, records, project, payload)


def emettre_impact(records: dict, code: int, payload: dict) -> bool:
    return _sur(impact, records, int(code), payload)


def emettre_verrou(records: dict, code: int, payload: dict) -> bool:
    return _sur(verrou, records, int(code), payload)
