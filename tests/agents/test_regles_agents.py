"""Oracles ARCH-001 (AGENTS_ADDENDUM, 10 règles) et REG-003/BB-001 (AGENTS.md, 6 règles), écrits AVANT le code.

Preuve attendue par la matrice : « AGENTS.md de l'usine + gabarit de brief d'agent + garde ».
- `agents/regles.json` porte les 16 règles mot pour mot, chacune avec sa section de brief et son mécanisme (fichier
  existant et motif qui doit s'y trouver) ;
- AGENTS.md cite chaque règle mot pour mot ;
- `agents/gabarit-brief.md` a une section par règle ; `agents/brief.py verifier` refuse un brief à qui il en manque
  une, ou qui garde un champ « À REMPLIR », et accepte un brief complet ;
- le gabarit de PR exige ce que la règle « Toute PR doit fournir … » énumère.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[2]
REGLES = RACINE / "agents" / "regles.json"
BRIEF = RACINE / "agents" / "brief.py"
GABARIT = RACINE / "agents" / "gabarit-brief.md"


def regles() -> list[dict]:
    return json.loads(REGLES.read_text(encoding="utf-8"))["regles"]


def verifier(texte: str) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(texte)
    try:
        return subprocess.run([sys.executable, str(BRIEF), "verifier", f.name, "--json"], capture_output=True, text=True,
                              timeout=60)
    finally:
        pathlib.Path(f.name).unlink()


def brief_complet() -> str:
    t = GABARIT.read_text(encoding="utf-8")
    return t.replace("À REMPLIR", "fait : voir le rapport")


class Regles(unittest.TestCase):
    def test_seize_regles_identifiees(self) -> None:
        r = regles()
        self.assertEqual([x["id"] for x in r], [f"ADD-{i}" for i in range(1, 11)] + [f"AG-{i}" for i in range(1, 7)])
        self.assertEqual(len({x["section"] for x in r}), len({x["section"] for x in r}))

    def test_agents_md_cite_chaque_regle_mot_pour_mot(self) -> None:
        agents = (RACINE / "AGENTS.md").read_text(encoding="utf-8")
        manquantes = [x["id"] for x in regles() if x["texte"] not in agents]
        self.assertEqual(manquantes, [])

    def test_chaque_mecanisme_existe_et_porte_son_motif(self) -> None:
        fautes = []
        for x in regles():
            for m in x["mecanismes"]:
                f = RACINE / m["chemin"]
                if not f.is_file() or m["motif"] not in f.read_text(encoding="utf-8"):
                    fautes.append((x["id"], m["chemin"]))
        self.assertEqual(fautes, [])

    def test_le_gabarit_a_une_section_par_regle(self) -> None:
        g = GABARIT.read_text(encoding="utf-8")
        self.assertEqual([x["id"] for x in regles() if f"## {x['section']}" not in g], [])


class Garde(unittest.TestCase):
    def test_brief_complet_accepte(self) -> None:
        r = verifier(brief_complet())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(json.loads(r.stdout)["ok"])

    def test_section_manquante_refusee(self) -> None:
        sec = regles()[4]["section"]
        texte = brief_complet().replace(f"## {sec}", "## autre chose")
        r = verifier(texte)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn(sec, json.loads(r.stdout)["manquantes"])

    def test_champ_a_remplir_refuse(self) -> None:
        r = verifier(GABARIT.read_text(encoding="utf-8"))
        self.assertEqual(r.returncode, 1)
        self.assertTrue(json.loads(r.stdout)["a_remplir"])

    def test_section_vide_refusee(self) -> None:
        secs = [x["section"] for x in regles()]
        lignes, out, sauter = brief_complet().splitlines(), [], False
        for l in lignes:
            if l.startswith("## "):
                sauter = l == f"## {secs[0]}"
                out.append(l)
                continue
            if not sauter:
                out.append(l)
        r = verifier("\n".join(out))
        self.assertEqual(r.returncode, 1)
        self.assertIn(secs[0], json.loads(r.stdout)["vides"])

    def test_rendre_produit_le_gabarit(self) -> None:
        r = subprocess.run([sys.executable, str(BRIEF), "rendre", "--tache", "essai"], capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("essai", r.stdout)
        self.assertTrue(all(f"## {x['section']}" in r.stdout for x in regles()))


class GabaritPR(unittest.TestCase):
    def test_le_gabarit_de_pr_demande_ce_que_la_regle_enumere(self) -> None:
        pr = (RACINE / ".forgejo" / "pull_request_template.md").read_text(encoding="utf-8")
        for rubrique in ("Exigences", "Building blocks évalués", "Justification", "Tests", "SBOM", "Provenance",
                         "Événements OPS-001"):
            self.assertIn(f"## {rubrique}", pr)


if __name__ == "__main__":
    unittest.main()
