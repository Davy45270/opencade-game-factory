"""Liste de souhaits des catalogues fermés aux agents (décision de David, HL-538, 22/11).

« Ouvertes uniquement en automatique et liste de souhaits à récupérer en manuel » :
- kenney.nl et opengameart.org refusent les agents IA dans leur robots.txt : aucun agent n'y lit ni n'y télécharge.
- Un agent qui juge un de leurs packs utile l'AJOUTE à `external/souhaits.json` (versionné) : URL de la page, licence
  annoncée, raison, jeu demandeur. Aucun accès réseau (`assetctl external souhait ajouter`).
- David, et lui seul, lance la récupération depuis Zalman : `./regctl souhaits recuperer [ID…|--tous] [--oui]`. La
  commande refuse de tourner hors d'un terminal interactif (ni agent, ni tâche planifiée), affiche ce qu'elle va faire
  et demande confirmation, télécharge (lien direct qu'il fournit) ou lit l'archive qu'il a téléchargée dans son
  navigateur, vérifie la licence DANS l'archive, importe, puis ouvre la PR.
"""

import json
import re
import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from tools.core.catalog import read_json, write_json

FERMES = {"kenney": "kenney.nl", "opengameart": "opengameart.org"}
STATUTS = ("a-recuperer", "importe", "licence-non-prouvee", "abandonne")


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def chemin(root):
    return Path(root) / "external" / "souhaits.json"


def lire(root):
    path = chemin(root)
    return read_json(path) if path.is_file() else {"schemaVersion": "1.0", "souhaits": []}


def ajouter(root, provider, page, licence, raison, jeu, telechargement=None, dry_run=False):
    """Ajoute un souhait sans aucun accès réseau. Rend (code, résultat)."""
    from tools.core.exit_codes import ExitCode

    hote = FERMES.get(provider)
    parts = urllib.parse.urlsplit(page or "")
    if hote is None:
        return ExitCode.USAGE, {"ok": False, "error": "usage", "message": f"fournisseur fermé aux agents attendu : "
                                f"{', '.join(FERMES)} (les sources ouvertes s'importent en automatique)"}
    if parts.scheme != "https" or not (parts.netloc == hote or parts.netloc.endswith("." + hote)):
        return ExitCode.USAGE, {"ok": False, "error": "usage", "message": f"page https://{hote}/… attendue"}
    if not str(raison or "").strip() or not str(jeu or "").strip():
        return ExitCode.USAGE, {"ok": False, "error": "usage", "message": "raison et jeu demandeur obligatoires"}
    if telechargement and urllib.parse.urlsplit(telechargement).scheme != "https":
        return ExitCode.USAGE, {"ok": False, "error": "usage", "message": "lien de téléchargement https attendu"}
    data = lire(root)
    slug = re.sub(r"[^a-z0-9]+", "-", parts.path.lower()).strip("-").rsplit("-", 6)
    ident = f"{provider}-" + "-".join(slug)[-60:].strip("-")
    existant = next((s for s in data["souhaits"] if s["page"] == page), None)
    if existant:
        jeux = sorted({*existant.get("jeux", []), jeu})
        if jeux == existant.get("jeux"):
            return ExitCode.OK, {"ok": True, "status": "unchanged", "souhait": existant}
        existant["jeux"] = jeux
        existant.setdefault("raisons", []).append({"jeu": jeu, "raison": raison, "date": _now()})
        souhait, status = existant, "updated"
    else:
        souhait = {"id": ident, "provider": provider, "page": page, "licenceAnnoncee": licence or "inconnue",
                   "jeux": [jeu], "raisons": [{"jeu": jeu, "raison": raison, "date": _now()}],
                   "statut": "a-recuperer", "ajouteLe": _now()}
        if telechargement:
            souhait["telechargement"] = telechargement
        data["souhaits"].append(souhait)
        status = "created"
    if not dry_run:
        chemin(root).parent.mkdir(parents=True, exist_ok=True)
        write_json(chemin(root), data)
    return ExitCode.OK, {"ok": True, "status": status, "souhait": souhait, "dryRun": bool(dry_run)}


def terminal_interactif(stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    return bool(stdin.isatty() and stdout.isatty())


def importer_archive(root, souhait, archive):
    """Vérifie la licence dans l'archive, puis importe (même écriture transactionnelle que `external import`)."""
    from tools.discovery.scan import directory_lock
    from tools.external.adapters import ExternalAssetCandidate
    from tools.external.archive import inspect_archive
    from tools.external.importer import _check_contract, _write
    from tools.external.licenses import LicenseEvaluator
    import hashlib

    raw = Path(archive).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    report = inspect_archive(Path(archive))
    if not report["ok"]:
        return {"ok": False, "statut": "a-recuperer", "motif": "archive dangereuse", "problemes": report["problems"]}
    verdict = LicenseEvaluator().verify(souhait["licenceAnnoncee"], report["texts"])
    if verdict["status"] != "verified":
        return {"ok": False, "statut": "licence-non-prouvee", "motif": verdict["evidence"]}
    pack = re.sub(r"[^A-Za-z0-9._-]+", "-", souhait["id"])[:128]
    candidat = ExternalAssetCandidate(provider=souhait["provider"], externalId=pack, title=souhait["id"],
                                      sourceUrl=souhait["page"], licenseSpdx=verdict["spdx"],
                                      licenseEvidenceUrl=souhait["page"], metadataConfidence="verified",
                                      sourceVersion=f"sha256:{digest[:16]}")
    contrat = {"schemaVersion": "1.0", "jobType": "external-library-import", "provider": souhait["provider"],
               "externalPackId": pack, "sourceUrl": souhait["page"], "downloadUrl": souhait.get("telechargement"),
               "sourceVersion": f"sha256:{digest[:16]}", "archiveSha256": digest, "observedAt": _now(),
               "license": {"spdxId": verdict["spdx"], "verification": "verified", "evidenceUrl": souhait["page"],
                           "evidence": verdict["evidence"]},
               "policy": {"allowDownload": True, "publishOnlyVerified": True, "preserveOriginalArchive": True,
                          "detectDuplicates": True, "dryRun": False},
               "files": [{"path": r["path"], "sha256": r["sha256"], "format": r["format"]} for r in report["media"]],
               "decision": {"action": "import", "rationale": "souhait récupéré par David : " + "; ".join(
                   f"{r['jeu']} — {r['raison']}" for r in souhait["raisons"]), "licenseStatus": "verified",
                            "consulted": [souhait["page"]], "rejected": []}}
    _check_contract(contrat)
    import zipfile
    with zipfile.ZipFile(archive) as z:
        payloads = {r["path"]: z.read(r["path"]) for r in report["media"]}
    with directory_lock(Path(root) / "catalog"):
        code, resultat = _write(Path(root), contrat, candidat, verdict, report, raw, payloads, False)
    return {"ok": code == 0, "statut": "importe" if code == 0 else "a-recuperer", "ids": resultat.get("ids", []),
            "licence": verdict["spdx"], "preuve": verdict["evidence"]}


def recuperer(root, ids, tous, oui, demander=input, afficher=print, terminal=None, ouvrir_pr=None):
    """Cœur de `regctl souhaits recuperer`. `terminal` (bool) vient de terminal_interactif() : faux = refus net."""
    if not (terminal_interactif() if terminal is None else terminal):
        afficher("refus : `regctl souhaits recuperer` se lance par David depuis un terminal interactif de Zalman "
                 "(jamais un agent, jamais une tâche planifiée).")
        return 2
    data = lire(root)
    choix = [s for s in data["souhaits"] if s["statut"] == "a-recuperer" and (tous or s["id"] in ids)]
    if not choix:
        afficher("aucun souhait à récupérer pour cette sélection.")
        return 1
    afficher(f"{len(choix)} souhait(s) à récupérer :")
    for s in choix:
        afficher(f"- {s['id']} : {s['page']} (licence annoncée {s['licenceAnnoncee']}, jeux {', '.join(s['jeux'])})")
    afficher("Pour chacun : téléchargement (lien direct du souhait) ou archive téléchargée par toi, licence vérifiée "
             "dans l'archive, import dans le registre, puis PR sur la forge.")
    if not oui and demander("Continuer ? [o/N] ").strip().lower() not in {"o", "oui", "y", "yes"}:
        afficher("abandon : rien n'a été fait.")
        return 1
    bilan = []
    with tempfile.TemporaryDirectory(prefix="souhaits-") as dossier:
        for s in choix:
            archive = None
            if s.get("telechargement"):
                from tools.external.download import DownloadManager

                archive = Path(dossier) / f"{s['id']}.zip"
                DownloadManager().fetch(s["telechargement"], archive)
            else:
                reponse = demander(f"Chemin du zip téléchargé depuis {s['page']} (vide = passer) : ").strip()
                archive = Path(reponse).expanduser() if reponse else None
            if archive is None or not archive.is_file():
                afficher(f"- {s['id']} : passé (aucune archive)")
                continue
            r = importer_archive(root, s, archive)
            s["statut"] = r["statut"]
            s["recupereLe"] = _now()
            s["resultat"] = {k: v for k, v in r.items() if k != "ok"}
            bilan.append((s["id"], r))
            afficher(f"- {s['id']} : {r['statut']} ({r.get('licence') or r.get('motif')})")
    write_json(chemin(root), data)
    if any(r["ok"] for _, r in bilan) and ouvrir_pr:
        ouvrir_pr(bilan)
    return 0 if all(r["ok"] for _, r in bilan) and bilan else 1
