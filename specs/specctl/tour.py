"""Événements de résolution pour la Control Tower (FactoryEvent v1.1) : `spec.resolved` et `spec.conflict`.

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
    tr = trace()
    brut = ":".join(["specctl", typ, project, fait, tr or ""])
    event_id = "specctl:" + hashlib.sha256(brut.encode("utf-8")).hexdigest()[:32]
    ev = {"schemaVersion": 1.1, "eventId": event_id, "occurredAt": utc(), "source": "specctl",
          "portfolioId": "homelab", "projectId": project[:128] or "inconnu", "workflowId": "specctl",
          "workflowVersion": "resolve", "runId": event_id, "eventType": typ, "status": etat,
          "evidence": [], "metadata": meta}
    refs = [r for r in refs if RE_ID.fullmatch(r)]
    if refs:
        ev["specRefs"] = refs[:64]
    if tr:
        ev["traceId"] = tr
    return ev


def emettre_resolution(project: str, code: int, payload: dict) -> bool:
    """Rend True si l'événement a été écrit. N'échoue jamais."""
    try:
        d = dossier()
        if d is None or not d.is_dir():
            return False
        ev = evenement(project, int(code), payload)
        if ev is None:
            return False
        ligne = (json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(d / "inbox.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK, 0o644)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return False
            return os.write(fd, ligne) == len(ligne)
        finally:
            os.close(fd)
    except Exception:
        return False
