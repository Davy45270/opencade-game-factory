"""Gates éliminatoires et matrice BB-001."""

import re
from datetime import date
from decimal import Decimal

from tools.core.catalog import InvalidJSON, read_json

from .registry import check_path

WEIGHTS = {"adequation": 25, "integration": 20, "maintenance": 15,
           "licence": 15, "securite": 15, "cout": 10}


def nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def evaluate(directory, block):
    check_path(directory, directory=True)
    candidate = block["id"]
    path = directory / f"{candidate}.json"
    check_path(path)
    if not path.is_file():
        raise InvalidJSON(f"Évaluation absente : {candidate}.")
    record = read_json(path)
    if not isinstance(record, dict) or record.get("candidate") != candidate:
        raise InvalidJSON("Identifiant de candidat incohérent dans l'évaluation.")
    evaluated_at = record.get("date")
    try:
        if not isinstance(evaluated_at, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", evaluated_at):
            raise ValueError
        date.fromisoformat(evaluated_at)
    except ValueError as exc:
        raise InvalidJSON("Une date d'évaluation valide est requise (AAAA-MM-JJ).") from exc

    gates = record.get("gates")
    if not isinstance(gates, dict):
        raise InvalidJSON("Gates d'évaluation absents ou invalides.")
    security = gates.get("security")
    if (not isinstance(security, dict) or type(security.get("critical")) is not int
            or security["critical"] < 0 or type(security.get("accepted")) is not bool):
        raise InvalidJSON("Gate security invalide : critical et accepted sont requis.")

    rejected = {}
    license_id = block["origin"]["licenseSpdx"]
    compatibility = gates.get("license")
    if compatibility not in (None, "compatible", "incompatible", "unknown"):
        raise InvalidJSON("Gate license invalide.")
    if license_id == "UNKNOWN" or compatibility == "unknown":
        rejected["license"] = "unknown"
    elif compatibility == "incompatible":
        rejected["license"] = "incompatible"
    if security["critical"] and not security["accepted"]:
        rejected["security"] = "critical-not-accepted"
    if gates.get("provenance") != "known":
        rejected["provenance"] = "unknown"
    if gates.get("technical") != "ok":
        rejected["technical"] = "blocked"

    return {
        "candidate": candidate, "date": evaluated_at, "gates": rejected,
        "eliminated": bool(rejected),
        "score": None if rejected else weighted_score(record.get("scores")),
    }


def weighted_score(scores):
    if not isinstance(scores, dict) or scores.keys() != WEIGHTS.keys():
        raise InvalidJSON("Les six critères pondérés sont requis.")
    total = Decimal(0)
    for criterion, weight in WEIGHTS.items():
        entry = scores[criterion]
        if not isinstance(entry, dict) or not nonblank(entry.get("preuve")):
            raise InvalidJSON(f"Preuve requise pour le critère {criterion}.")
        score = entry.get("score")
        if type(score) not in (int, float) or not 0 <= score <= 5:
            raise InvalidJSON(f"Score hors échelle (0–5) pour le critère {criterion}.")
        total += Decimal(str(score)) * weight
    return float(round(total / 100, 2))
