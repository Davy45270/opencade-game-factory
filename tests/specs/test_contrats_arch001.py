"""Oracles ARCH-001 E052 et E053 (contrats de spécification et de solution), écrits AVANT le code.

`schemas/contrats-arch001.json` relie chaque champ des contrats d'ARCH-001 (liste mot pour mot de la spec) à un
chemin des schémas de l'usine. Les tests prouvent : aucun champ oublié, chaque chemin existe dans le schéma, et
chaque fiche réelle (registre des specs, catalogue des briques) porte les champs obligatoires du contrat."""
from __future__ import annotations

import json
import pathlib
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[2]
CONTRATS = RACINE / "schemas" / "contrats-arch001.json"
SPEC = ["specId", "version", "status", "sourceRepo", "sourcePath", "commitSha", "requirements", "dependencies",
        "implementationRefs", "testRefs", "decisionRefs"]
SOLUTION = ["componentId", "type", "sourceRepo", "version", "capabilities", "interfaces", "license", "sbomRef",
            "specRefs", "consumers", "validationEvidence", "lifecycle"]


def contrats() -> dict:
    return json.loads(CONTRATS.read_text(encoding="utf-8"))


def schema_a(chemin_schema: str, chemin: str) -> bool:
    noeud = json.loads((RACINE / chemin_schema).read_text(encoding="utf-8"))
    for part in chemin.split("."):
        tableau = part.endswith("[]")
        props = noeud.get("properties") or {}
        if part.removesuffix("[]") not in props:
            return False
        noeud = props[part.removesuffix("[]")]
        if tableau:
            noeud = noeud.get("items") or {}
    return True


def valeur(fiche: dict, chemin: str):
    v = fiche
    for part in chemin.split("."):
        if isinstance(v, list):
            v = v[0] if v else None
        if not isinstance(v, dict) or part.removesuffix("[]") not in v:
            return KeyError
        v = v[part.removesuffix("[]")]
    return v


class Contrats(unittest.TestCase):
    def test_aucun_champ_oublie(self) -> None:
        c = contrats()
        self.assertEqual(list(c["specification"]["champs"]), SPEC)
        self.assertEqual(list(c["solution"]["champs"]), SOLUTION)

    def test_chaque_chemin_existe_dans_le_schema(self) -> None:
        fautes = []
        for nom in ("specification", "solution"):
            c = contrats()[nom]
            for champ, m in c["champs"].items():
                if not schema_a(c["schema"], m["chemin"]):
                    fautes.append((nom, champ, m["chemin"]))
        self.assertEqual(fautes, [])

    def test_fiches_reelles_portent_les_champs_obligatoires(self) -> None:
        fautes = []
        for nom, motif in (("specification", "specs/registry/SPEC-*.json"), ("solution", "blocks/catalog/*.json")):
            c = contrats()[nom]
            fichiers = sorted(RACINE.glob(motif))
            self.assertTrue(fichiers, motif)
            for f in fichiers:
                fiche = json.loads(f.read_text(encoding="utf-8"))
                for champ, m in c["champs"].items():
                    if m["obligatoire"] and valeur(fiche, m["chemin"]) is KeyError:
                        fautes.append((f.name, champ))
        self.assertEqual(fautes[:10], [])


if __name__ == "__main__":
    unittest.main()
