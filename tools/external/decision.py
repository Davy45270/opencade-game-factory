"""Moteur de décision reuse / import / derive / create / block (EXT-001 § 3, EXT-04).

Ordre imposé : interne d'abord, puis externe ; chaque décision porte sa justification, les candidats
consultés et la raison de chaque rejet. Une recherche externe indisponible ne vaut jamais « rien n'existe » :
la décision le dit (externalSearchStatus) et ne choisit pas « create » sur cette seule base.
"""


def decide(internal, external, external_status, target="private", evaluate=None, wanted=None):
    """`internal` : résultats de `assetctl search` (dicts) ; `external` : ExternalAssetCandidate ;
    `evaluate(candidate)` rend le verdict licence pour la destination ; `wanted` : critères exacts
    (orientation, state, license…) qu'un candidat interne doit respecter."""
    wanted = wanted or {}
    consulted, rejected = [], []
    for row in internal:
        consulted.append({"source": "internal", "id": row["id"]})
        mismatch = sorted(key for key, value in wanted.items() if row.get(key) != value)
        if mismatch:
            rejected.append({"id": row["id"], "reason": "critères différents : " + ", ".join(mismatch)})
            continue
        return {"action": "reuse", "candidateId": row["id"], "licenseStatus": "verified" if row.get("license") not in
                (None, "unknown") else "unknown", "rationale": "asset interne compatible : aucune création ni import",
                "consulted": consulted, "rejected": rejected, "externalSearchStatus": "not-needed"}
    for row in internal:
        mismatch = {key for key, value in wanted.items() if row.get(key) != value}
        if mismatch and mismatch <= {"orientation", "facing"}:
            return {"action": "derive", "candidateId": row["id"], "licenseStatus": "verified" if row.get("license")
                    not in (None, "unknown") else "unknown", "consulted": consulted, "rejected": rejected,
                    "externalSearchStatus": "not-needed",
                    "rationale": "asset interne compatible sauf l'orientation : dériver une variante liée (derive)"}
    blocked = None
    for candidate in external:
        key = f"{candidate.provider}:{candidate.externalId}"
        consulted.append({"source": "external", "id": key})
        verdict = evaluate(candidate) if evaluate else {"allowed": False, "licenseStatus": "unknown",
                                                         "reason": "licence non évaluée"}
        if verdict["allowed"]:
            return {"action": "import", "candidateId": key, "licenseStatus": "verified",
                    "rationale": f"aucun asset interne compatible ; {verdict['reason']}", "consulted": consulted,
                    "rejected": rejected, "externalSearchStatus": external_status}
        rejected.append({"id": key, "reason": verdict["reason"]})
        blocked = blocked or {"candidateId": key, "licenseStatus": verdict["licenseStatus"], "reason": verdict["reason"]}
    if external_status != "available":
        return {"action": "block", "licenseStatus": "unknown", "consulted": consulted, "rejected": rejected,
                "externalSearchStatus": external_status,
                "rationale": "recherche externe indisponible : aucune absence n'est affirmée ; "
                             "réessayer ou décider à la main"}
    if blocked:
        return {"action": "block", "candidateId": blocked["candidateId"], "licenseStatus": blocked["licenseStatus"],
                "rationale": f"candidat externe trouvé mais {blocked['reason']}", "consulted": consulted,
                "rejected": rejected, "externalSearchStatus": external_status}
    return {"action": "create", "licenseStatus": "unknown", "consulted": consulted, "rejected": rejected,
            "externalSearchStatus": external_status,
            "rationale": "aucun candidat interne ni externe : création documentée avec les rejets ci-dessus"}
