"""Recommandations de mutualisation (BB-001 § 9 et BB-12 ; matrice E213, E225).

Un groupe = les modules locaux de même nom dans au moins deux dépôts. Gains : dépôts concernés, exports communs à tous
les modules (lus par `bbctl discover`, champ analysis). Risques : couplage (le module importe d'autres modules locaux
de son dépôt : l'extraire les entraînerait), modules sans tests, licences divergentes. « extract » seulement si les
gains existent (≥ 2 dépôts, ≥ 1 export commun) ET qu'aucun risque n'est relevé ; sinon « keep-local », avec ses raisons.
"""

from collections import defaultdict


def groupes(records):
    par_nom = defaultdict(list)
    for block_id, (_, block) in sorted(records.items()):
        if (block.get("discovery") or {}).get("ecosystem") == "local" and block["origin"].get("repo"):
            par_nom[block["name"].casefold()].append((block_id, block))
    out = []
    for nom, membres in sorted(par_nom.items()):
        repos = sorted({b["origin"]["repo"] for _, b in membres})
        if len(repos) < 2:
            continue
        analyses = {i: b.get("analysis") or {} for i, b in membres}
        exports = [set(a.get("exports") or []) for a in analyses.values()]
        communs = sorted(set.intersection(*exports)) if exports else []
        couplage = sorted(f"{i} -> {imp}" for i, a in analyses.items() for imp in a.get("imports") or []
                          if imp.startswith("local:"))
        sans_tests = sorted(i for i, a in analyses.items() if not a.get("tests"))
        licences = sorted({b["origin"]["licenseSpdx"] for _, b in membres})
        raisons = []
        if not communs:
            raisons.append("aucun export commun : rien de partagé à extraire")
        if couplage:
            raisons.append("couplage : l'extraction entraînerait d'autres modules locaux")
        if sans_tests:
            raisons.append("modules sans tests : comportement commun non prouvé")
        if len(licences) > 1 or "UNKNOWN" in licences:
            raisons.append("licences divergentes ou inconnues")
        out.append({"name": membres[0][1]["name"], "recommendation": "keep-local" if raisons else "extract",
                    "gains": {"repos": repos, "sharedExports": communs, "modules": [i for i, _ in membres]},
                    "risks": {"coupling": couplage, "untested": sans_tests, "licenses": licences},
                    "reasons": raisons})
    return out


def mutualiser(records):
    gs = groupes(records)
    return {"groups": gs, "extract": [g["name"] for g in gs if g["recommendation"] == "extract"]}


def justifiee(records, block):
    """E213 : une brique partagée (shared-library) ne se décide que si son groupe est recommandé à l'extraction."""
    nom = block["name"].casefold()
    return any(g["name"].casefold() == nom and g["recommendation"] == "extract" for g in groupes(records))
