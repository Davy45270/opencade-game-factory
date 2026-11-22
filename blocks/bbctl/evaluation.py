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
    runtime = gates.get("runtime")
    if runtime not in (None, "compatible", "incompatible", "unknown"):
        raise InvalidJSON("Gate runtime invalide.")
    if runtime in ("incompatible", "unknown"):
        rejected["runtime"] = runtime                      # E181 : incompatibilité technique éliminatoire

    tco = cout_complet(record, block)
    return {
        "candidate": candidate, "date": evaluated_at, "gates": rejected,
        "eliminated": bool(rejected),
        "score": None if rejected else weighted_score(record.get("scores")),
        "verifications": verifications(block, record, gates, tco),
        "tco": tco,
    }


VERIFICATIONS = ("canonicalUrl", "license", "maintenance", "vulnerabilities", "runtime", "tests", "integrationCost")
LOCAL_ECOSYSTEMS = ("local", "workflow", "script")


def prouve_h(entry):
    return isinstance(entry, dict) and nonblank(entry.get("hypothese"))


def prouve(entry):
    return isinstance(entry, dict) and nonblank(entry.get("preuve"))


def verifications(block, record, gates, tco):
    """E181 (BB-001 § 4) : les sept vérifications avant adoption, « verified » ou « missing » (jamais devinées)."""
    origin = block["origin"]
    scores = record.get("scores") if isinstance(record.get("scores"), dict) else {}
    checks = record.get("checks") if isinstance(record.get("checks"), dict) else {}
    faits = {
        "canonicalUrl": nonblank(origin.get("repositoryUrl")) or bool(origin.get("repo") and origin.get("path")),
        "license": origin.get("licenseSpdx") not in (None, "UNKNOWN"),
        "maintenance": prouve(scores.get("maintenance")),
        "vulnerabilities": isinstance(gates.get("security"), dict),
        "runtime": gates.get("runtime") == "compatible",
        "tests": prouve(checks.get("tests")),
        "integrationCost": isinstance(record.get("tco"), dict) and prouve_h(record["tco"].get("integration")),
    }
    return {k: "verified" if faits[k] else "missing" for k in VERIFICATIONS}


def externe(block):
    return (block.get("discovery") or {}).get("ecosystem") not in LOCAL_ECOSYSTEMS and not block["origin"].get("repo")


POSTES = ("integration", "adaptation", "maintenance", "misesAJour", "tests", "detteSecurite", "sortie")


def cout_complet(record, block):
    """E226 (BB-13, § 6) : hypothèses par poste (`tco`, format de `bbctl adopt`), puis MESURE après adoption
    (`tcoMesure` : date et, par poste, mesure et preuve) comparée poste par poste ; None si aucun TCO."""
    tco = record.get("tco")
    if tco is None:
        return None
    tco = tco if isinstance(tco, dict) else {}
    complet = all(isinstance(tco.get(k), dict) and nonblank(tco[k].get("hypothese")) for k in POSTES)
    mesure = record.get("tcoMesure")
    comparaison = None
    if mesure is not None:
        if not isinstance(mesure, dict) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(mesure.get("date", ""))):
            raise InvalidJSON("TCO mesuré : date (AAAA-MM-JJ) requise.")
        postes = mesure.get("postes") if isinstance(mesure.get("postes"), dict) else {}
        manque = [k for k in POSTES if not (prouve(postes.get(k)) and nonblank(postes[k].get("mesure")))]
        if manque:
            raise InvalidJSON("TCO mesuré : mesure et preuve requises pour " + ", ".join(manque) + ".")
        comparaison = [{"poste": k, "estimation": (tco.get(k) or {}).get("estimation"), "mesure": postes[k]["mesure"]}
                       for k in POSTES]
    return {"hypotheses": "complete" if complet else "incomplete",
            "measuredAt": mesure["date"] if mesure is not None else None, "comparison": comparaison,
            "measurementDue": block["quality"]["status"] == "adopted" and mesure is None}


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
