"""Adoption tracée (BB-001 § 11), écritures sûres et journalisées, contrôle « reuse before build » (§ 5, BB-08).

- adopt : décision reuse/adapt/wrap/fork, TCO complet (§ 6), SBOM obligatoire (T11), verrou de version, PR, rapport
  de tests et usedBy écrits dans la fiche ;
- --expect : une fiche modifiée depuis sa lecture n'est jamais écrasée (T13) ;
- journal `blocks/journal.jsonl` : une ligne par écriture, empreintes avant/après ;
- gate : toute brique NOUVELLE entre deux commits d'un dépôt de jeu doit être décidée au catalogue ou couverte par une
  dérogation approuvée (référence HL-n 7-n) ; la dérogation utilisée est journalisée (T09).
"""

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from tools.core.catalog import CatalogueScopeError, InvalidJSON, json_text, read_json, write_json

from . import evenements
from .discover import Repo, observe

REUSE = {"reuse", "adapt", "wrap", "fork"}
TCO = ("integration", "adaptation", "maintenance", "misesAJour", "tests", "detteSecurite", "sortie")
REF = re.compile(r"HL-[0-9]+ 7-[0-9]+")


class Conflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def journal(blocks, line):
    with open(blocks / "journal.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": now(), **line}, sort_keys=True, ensure_ascii=False) + "\n")


def write_block(blocks, path, block, command, expect):
    """Écrit une fiche si elle a changé ; refuse si elle n'est plus celle que l'appelant a lue (T13)."""
    before = sha_file(path)
    if expect is not None and expect != before:
        raise Conflict(f"{block['id']} : la fiche a changé depuis sa lecture (attendu {expect[:12]}…, "
                       f"trouvé {(before or 'absente')[:12]}…) ; relire avant d'écrire.")
    if path.is_file() and path.read_text(encoding="utf-8") == json_text(block):
        return False
    write_json(path, block)
    journal(blocks, {"command": command, "blockId": block["id"], "sha256Before": before, "sha256After": sha_file(path)})
    return True


def check_tco(evaluations, block_id):
    path = evaluations / f"{block_id}.json"
    record = read_json(path) if path.is_file() else {}
    tco = record.get("tco")
    missing = [k for k in TCO if not (isinstance(tco, dict) and isinstance(tco.get(k), dict)
                                      and str(tco[k].get("hypothese") or "").strip())]
    if missing:
        raise InvalidJSON(f"{block_id} : TCO incomplet (hypothèse manquante) : {', '.join(missing)}.")
    return tco


def adopt(blocks, records, args):
    if args.candidate not in records:
        raise InvalidJSON(f"Candidat absent du catalogue : {args.candidate}.")
    path, block = records[args.candidate]
    decision = block["decision"]
    if decision.get("status") != "decided" or decision.get("choice") not in REUSE:
        raise CatalogueScopeError(f"{block['id']} : adoption sans décision reuse/adapt/wrap/fork enregistrée.")
    check_tco(blocks / "evaluations", block["id"])
    if not (args.sbom or "").strip():
        raise CatalogueScopeError(f"{block['id']} : SBOM absent, adoption bloquée (BB-001 T11).")
    updated = json.loads(json.dumps(block))
    updated["origin"]["version"] = args.version
    updated["quality"] = {**updated["quality"], "status": "adopted", "sbomRef": args.sbom}
    updated["usedBy"] = sorted(set(updated["usedBy"]) | {args.used_by})
    entry = {"usedBy": args.used_by, "version": args.version, "pr": args.pr, "tests": args.tests, "sbom": args.sbom}
    updated["adoptions"] = [a for a in updated.get("adoptions", []) if a != entry] + [entry]
    changed = write_block(blocks, path, updated, "adopt", args.expect)
    if changed:
        evenements.emettre("bb.adopted", "success", args.used_by, [block["id"]],
                           {"choice": decision["choice"], "version": args.version, "sbom": args.sbom}, args.pr,
                           specs=block.get("specIds") or ())
    return {"candidate": block["id"], "adopted": entry, "changed": changed}


def gate(blocks, records, repo_dir, base, head, name):
    repo_dir = Path(repo_dir).expanduser()
    name = name or repo_dir.name
    commits = []
    for ref in (base, head):
        result = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
                                capture_output=True, text=True)
        if result.returncode:
            raise ValueError(f"Révision Git introuvable : {ref}")
        commits.append(result.stdout.strip())
    before = {row["key"] for row in observe(Repo(name, repo_dir, commits[0]))}
    after = {row["key"]: row for row in observe(Repo(name, repo_dir, commits[1]))}
    new = sorted(set(after) - before)
    decided = {b.get("discovery", {}).get("key") for _, b in records.values() if b["decision"].get("status") == "decided"}
    derogation_file = blocks / "derogations.json"
    derogations = read_json(derogation_file) if derogation_file.is_file() else {}
    covered, used, uncovered = [], [], []
    for key in new:
        entry = derogations.get(key) if isinstance(derogations, dict) else None
        if key in decided:
            covered.append(key)
        elif isinstance(entry, dict) and REF.fullmatch(str(entry.get("ref", ""))) and str(entry.get("reason", "")).strip():
            used.append({"key": key, "ref": entry["ref"], "reason": entry["reason"]})
        else:
            uncovered.append(key)
    if used:
        journal(blocks, {"command": "gate", "repo": name, "base": commits[0], "head": commits[1],
                         "derogations": [u["key"] for u in used]})
    if uncovered:
        evenements.emettre("bb.blocked", "blocked", name, [], {"uncovered": uncovered, "head": commits[1]}, commits[1],
                           commit=commits[1])
    return {"repo": name, "base": commits[0], "head": commits[1], "new": new, "decided": covered,
            "derogations": used, "uncovered": uncovered}
