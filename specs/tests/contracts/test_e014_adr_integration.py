"""ARCH-001 E014 : livrables `integration-decisions/ADR-*.md`, une ADR par arbitrage de David (HL-525 7-2955, HL-538 7-2949).

Chaque ADR est approuvée, cite son arbitrage, et porte un contexte, une décision, des alternatives et un retour
arrière non vides. L'index les liste toutes. `controle()` rend les défauts ; les oracles le vérifient sur le dossier
réel puis sur des copies où UN défaut est introduit (témoins).
"""
from __future__ import annotations

import pathlib
import re
import shutil
import tempfile
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[3]
DOSSIER = RACINE / "docs" / "integration-decisions"
# Arbitrages de David couverts : 3 dans HL-525 7-2955, 4 dans HL-538 7-2949, 1 dans HL-538 7-3320 (ADR-0008).
ATTENDU = {"HL-525 7-2955": 3, "HL-538 7-2949": 4, "HL-538 7-3320": 1}
SECTIONS = ("Contexte", "Décision", "Alternatives", "Retour arrière")


def _section(texte: str, titre: str) -> str:
    m = re.search(rf"^## {re.escape(titre)}\n(.*?)(?=^## |\Z)", texte, re.M | re.S)
    return m.group(1).strip() if m else ""


def controle(dossier: pathlib.Path) -> list[str]:
    defauts: list[str] = []
    adrs = sorted(dossier.glob("ADR-*.md"))
    par_source: dict[str, int] = {}
    index = (dossier / "README.md").read_text(encoding="utf-8") if (dossier / "README.md").exists() else ""
    for f in adrs:
        t = f.read_text(encoding="utf-8")
        if not re.search(r"^- \*\*Statut :\*\* approuvée$", t, re.M):
            defauts.append(f"{f.name} : statut non approuvé")
        m = re.search(r"^- \*\*Approuvée par :\*\* David, (HL-\d+ 7-\d+)$", t, re.M)
        if not m:
            defauts.append(f"{f.name} : arbitrage de David non cité")
        else:
            par_source[m.group(1)] = par_source.get(m.group(1), 0) + 1
        for s in SECTIONS:
            if not _section(t, s):
                defauts.append(f"{f.name} : section « {s} » absente ou vide")
        if f.name not in index:
            defauts.append(f"{f.name} : absente de l'index")
    if par_source != ATTENDU:
        defauts.append(f"couverture des arbitrages {par_source} ≠ {ATTENDU}")
    return defauts


class E014AdrIntegration(unittest.TestCase):
    def test_dossier_reel_conforme(self):
        self.assertEqual(controle(DOSSIER), [])

    def _copie(self) -> pathlib.Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = pathlib.Path(tmp.name) / "d"
        shutil.copytree(DOSSIER, d)
        return d

    def test_temoin_retour_arriere_absent(self):
        d = self._copie()
        f = next(d.glob("ADR-0001-*.md"))
        f.write_text(re.sub(r"## Retour arrière\n.*?(?=## )", "", f.read_text(), flags=re.S))
        self.assertTrue(any("Retour arrière" in x for x in controle(d)))

    def test_temoin_alternatives_vides(self):
        d = self._copie()
        f = next(d.glob("ADR-0004-*.md"))
        f.write_text(re.sub(r"(## Alternatives\n).*?(?=## )", r"\1\n", f.read_text(), flags=re.S))
        self.assertTrue(any("Alternatives" in x for x in controle(d)))

    def test_temoin_adr_manquante(self):
        d = self._copie()
        next(d.glob("ADR-0007-*.md")).unlink()
        self.assertTrue(any("couverture" in x for x in controle(d)))

    def test_temoin_statut_propose(self):
        d = self._copie()
        f = next(d.glob("ADR-0003-*.md"))
        f.write_text(f.read_text().replace("**Statut :** approuvée", "**Statut :** proposée"))
        self.assertTrue(any("statut" in x for x in controle(d)))


if __name__ == "__main__":
    unittest.main()
