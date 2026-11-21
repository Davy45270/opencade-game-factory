"""LicenseEvaluator (EXT-001 § 2, § 6, EXT-06).

« Gratuit » n'est pas CC0 : une licence n'est `verified` que si le texte de licence lu DANS l'archive du pack
confirme l'identifiant SPDX déclaré par l'index. Sinon `unknown` (publication bloquée). Les licences à
attribution ou copyleft sont évaluées par pack et par destination : un export public d'une licence copyleft
est `incompatible` tant qu'aucune revue n'est enregistrée.
"""

import re

LICENSE_FILES = re.compile(r"(?i)(?:^|/)(license|licence|copying|readme)[^/]*\.(?:txt|md)$")
# Texte qui CONFIRME l'identifiant ; aucune déduction depuis le nom du fournisseur.
PROOFS = {
    "CC0-1.0": re.compile(r"(?i)(creative\s+commons\s+zero|\bCC0\b|publicdomain/zero/1\.0)"),
    "CC-BY-4.0": re.compile(r"(?i)(attribution\s+4\.0|licenses/by/4\.0)"),
    "CC-BY-3.0": re.compile(r"(?i)(attribution\s+3\.0|licenses/by/3\.0)"),
    "CC-BY-SA-4.0": re.compile(r"(?i)(attribution-sharealike\s+4\.0|licenses/by-sa/4\.0)"),
    "CC-BY-SA-3.0": re.compile(r"(?i)(attribution-sharealike\s+3\.0|licenses/by-sa/3\.0)"),
    "OFL-1.1": re.compile(r"(?i)SIL\s+OPEN\s+FONT\s+LICENSE"),
}
POLICY = {
    "CC0-1.0": {"attribution": False, "copyleft": False},
    "CC-BY-4.0": {"attribution": True, "copyleft": False},
    "CC-BY-3.0": {"attribution": True, "copyleft": False},
    "CC-BY-SA-4.0": {"attribution": True, "copyleft": True},
    "CC-BY-SA-3.0": {"attribution": True, "copyleft": True},
    "OFL-1.1": {"attribution": True, "copyleft": True},
}


class LicenseEvaluator:
    def verify(self, declared, texts):
        """`texts` : {chemin dans l'archive: texte}. Rend status verified|unknown, spdx, evidence."""
        if declared not in PROOFS:
            return {"status": "unknown", "spdx": "unknown",
                    "evidence": f"licence déclarée « {declared} » non prise en charge ou absente"}
        for path, text in sorted(texts.items()):
            if LICENSE_FILES.search(path) and PROOFS[declared].search(text):
                return {"status": "verified", "spdx": declared, "evidence": path}
        return {"status": "unknown", "spdx": "unknown",
                "evidence": f"aucun texte de licence de l'archive ne confirme {declared}"}

    def for_target(self, verdict, target, review=None):
        """Décision par destination (EXT-T04) : public exige verified et, pour un copyleft, une revue écrite."""
        if verdict["status"] != "verified":
            return {"allowed": False, "licenseStatus": "unknown",
                    "reason": "licence non vérifiée : publication bloquée"}
        rules = POLICY[verdict["spdx"]]
        if target == "public" and rules["copyleft"] and not review:
            return {"allowed": False, "licenseStatus": "incompatible",
                    "reason": f"{verdict['spdx']} est copyleft : redistribution publique soumise à revue de compatibilité"}
        return {"allowed": True, "licenseStatus": "verified", "attribution": rules["attribution"],
                "reason": f"{verdict['spdx']} vérifiée ({verdict['evidence']})"}
