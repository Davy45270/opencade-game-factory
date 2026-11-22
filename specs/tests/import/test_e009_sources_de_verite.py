"""ARCH-001 E009 : la registry relie les sources de vérité sans dupliquer les documents (scripts/sources_de_verite.py).

Le magasin d'assets de l'usine (originaux de niveaux et planches) n'est conforme que si chaque fichier est cité par
une fiche qui porte son empreinte et son origine ; le registre des specs ne tient que des références. Chaque oracle
part d'un magasin conforme et y introduit UN défaut : l'écart attendu doit apparaître, et lui seul.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts"))
import sources_de_verite as sdv  # noqa: E402

NIVEAU = b'{"terrain": ["#.#"]}\n'
PLANCHE = b"\x89PNG planche de David\n"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _ecrire(p: pathlib.Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), encoding="utf-8")


def magasin(racine: pathlib.Path) -> None:
    """Un magasin minimal conforme : un niveau, une planche, une spec par référence."""
    h = _sha(NIVEAU)
    (racine / "originals" / "sha256").mkdir(parents=True)
    (racine / "originals" / "sha256" / f"{h}.json").write_bytes(NIVEAU)
    _ecrire(racine / "catalog" / "levels" / "level-a.json", {"id": "level-a", "contentSha256": h, "observations": [
        {"contentSha256": h, "repo": "https://forge/david/jeu.git", "commit": "a" * 40, "path": "niveaux/a.json"}]})
    (racine / "sources" / "original-sheets").mkdir(parents=True)
    (racine / "sources" / "original-sheets" / "sheet-a-0001.png").write_bytes(PLANCHE)
    _ecrire(racine / "catalog" / "sheets" / "sheet-a-0001.json", {
        "id": "sheet-a-0001", "sha256": _sha(PLANCHE),
        "files": {"registry": "sources/original-sheets/sheet-a-0001.png", "locations": []},
        "provenance": {"type": "repo-file", "evidence": ["Dessin fourni par David : a.png · SHA-256 " + _sha(PLANCHE)]}})
    _ecrire(racine / "specs" / "registry" / "SPEC-A.json", {"id": "SPEC-A", "versions": [{"version": "1.0.0", "documents": [
        {"sha256": "b" * 64, "provenances": [{"repo": "homelab-docs", "path": "specs/a.md", "commitSha": "c" * 40}]}]}]})


class E009SourcesDeVerite(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.r = pathlib.Path(self._tmp.name)
        magasin(self.r)

    def tearDown(self):
        self._tmp.cleanup()

    def types(self):
        return sorted(e["type"] for e in sdv.mesurer(self.r)["ecarts"])

    def test_magasin_conforme(self):
        res = sdv.mesurer(self.r)
        self.assertEqual(res["ecarts"], [])
        self.assertEqual(res["compte"], {"originauxNiveaux": 1, "originauxPlanches": 1, "referencesSpecs": 1})

    def test_original_de_niveau_non_reference(self):
        autre = b'{"terrain": ["##"]}\n'
        (self.r / "originals" / "sha256" / f"{_sha(autre)}.json").write_bytes(autre)
        self.assertEqual(self.types(), ["original-orphelin"])

    def test_original_de_niveau_altere(self):
        f = next((self.r / "originals" / "sha256").glob("*.json"))
        f.write_bytes(NIVEAU + b" ")
        self.assertEqual(self.types(), ["empreinte-differente"])

    def test_niveau_sans_origine(self):
        p = self.r / "catalog" / "levels" / "level-a.json"
        d = json.loads(p.read_text())
        d["observations"][0]["commit"] = ""
        _ecrire(p, d)
        self.assertEqual(self.types(), ["origine-absente"])

    def test_planche_orpheline(self):
        (self.r / "sources" / "original-sheets" / "sheet-b-0001.png").write_bytes(b"autre")
        self.assertEqual(self.types(), ["original-orphelin"])

    def test_planche_dont_l_empreinte_differe(self):
        (self.r / "sources" / "original-sheets" / "sheet-a-0001.png").write_bytes(PLANCHE + b"x")
        self.assertEqual(self.types(), ["empreinte-differente"])

    def test_planche_sans_origine(self):
        p = self.r / "catalog" / "sheets" / "sheet-a-0001.json"
        d = json.loads(p.read_text())
        d["provenance"] = {"type": "repo-file", "evidence": []}
        _ecrire(p, d)
        self.assertEqual(self.types(), ["origine-absente"])

    def test_reference_de_spec_sans_commit(self):
        p = self.r / "specs" / "registry" / "SPEC-A.json"
        d = json.loads(p.read_text())
        d["versions"][0]["documents"][0]["provenances"][0]["commitSha"] = ""
        _ecrire(p, d)
        self.assertEqual(self.types(), ["reference-incomplete"])

    def test_copie_d_un_document_de_spec(self):
        (self.r / "specs" / "registry" / "a.md").write_text("# copie\n")
        self.assertEqual(self.types(), ["copie-de-document"])

    def test_cli_rend_1_sur_ecart(self):
        (self.r / "specs" / "registry" / "a.md").write_text("# copie\n")
        rc = subprocess.run([sys.executable, str(RACINE / "scripts" / "sources_de_verite.py"), "--racine", str(self.r)],
                            capture_output=True).returncode
        self.assertEqual(rc, 1)


class E009DepotReel(unittest.TestCase):
    """Le dépôt lui-même : chaque original du magasin est référencé, chaque spec est une référence."""

    def test_depot_conforme(self):
        res = sdv.mesurer(RACINE)
        self.assertEqual(res["ecarts"], [], res["ecarts"][:5])
        self.assertGreater(res["compte"]["originauxNiveaux"] + res["compte"]["originauxPlanches"], 0)
        self.assertGreater(res["compte"]["referencesSpecs"], 0)


if __name__ == "__main__":
    unittest.main()
