"""Preuves de conformité à la spec v1.0 qui n'avaient pas encore de test (HL-538, matrice asset-registry-conformite).

Chaque test nomme l'exigence de la matrice qu'il prouve. Chacun échoue si l'implémentation ou la règle disparaît.
"""
import copy
import re
import sqlite3
import unittest
from pathlib import Path

from tests.unit.test_oracles import ASSET, ASSET_ID, CatalogueFixture

ROOT = Path(__file__).resolve().parents[2]
AUTRE_ID = "asset-ui-bouton-0001"


class RechercheParFiltre(CatalogueFixture, unittest.TestCase):
    """E013 : recherche textuelle, tags, univers, orientation, état, licence, usage."""

    def setUp(self):
        super().setUp()
        self.asset.update(tags=["whisk", "clean"], originUniverse="cozy-room-sort", orientation="three-quarter",
                          state="clean", license="CC0-1.0",
                          usages=[{"game": "cozy-room-sort", "status": "active", "scene": "Cuisine"}])
        self.write_asset()
        autre = copy.deepcopy(ASSET)
        autre.update(id=AUTRE_ID, name="Bouton", category="ui", tags=["button"], originUniverse="opencade",
                     orientation="front", state="dirty", license="unknown", sha256="c" * 64,
                     usages=[{"game": "opencade", "status": "removed", "scene": "Menu"}])
        self.write(f"assets/{AUTRE_ID}.json", autre)

    def ids(self, *args):
        code, payload = self.cli("search", *args)
        self.assertEqual(code, 0, payload)
        return [row["id"] for row in payload["results"]]

    def test_chaque_filtre_de_la_spec_departage_les_deux_assets(self):
        cas = {
            ("fouet",): [ASSET_ID], ("bouton",): [AUTRE_ID],
            ("--tag", "whisk"): [ASSET_ID], ("--tag", "button"): [AUTRE_ID],
            ("--universe", "cozy-room-sort"): [ASSET_ID], ("--universe", "opencade"): [AUTRE_ID],
            ("--orientation", "three-quarter"): [ASSET_ID], ("--orientation", "front"): [AUTRE_ID],
            ("--state", "clean"): [ASSET_ID], ("--state", "dirty"): [AUTRE_ID],
            ("--license", "CC0-1.0"): [ASSET_ID], ("--license", "unknown"): [AUTRE_ID],
            ("--used-by", "cozy-room-sort"): [ASSET_ID],
            # Un usage retiré ne compte pas comme usage actif.
            ("--used-by", "opencade"): [],
        }
        for args, attendu in cas.items():
            with self.subTest(args=args):
                self.assertEqual(self.ids(*args), attendu)

    def test_recherche_textuelle_par_fts5(self):
        """E070 : la recherche textuelle P0 passe par une table virtuelle SQLite FTS5."""
        self.assertEqual(self.ids("fouet"), [ASSET_ID])
        base = self.root / "build" / "registry.sqlite"
        with sqlite3.connect(base) as connexion:
            sql = connexion.execute("SELECT sql FROM sqlite_master WHERE name = 'assets'").fetchone()[0]
            self.assertIn("USING fts5", sql)
            trouves = connexion.execute("SELECT id FROM assets WHERE assets MATCH 'whisk'").fetchall()
        self.assertEqual(trouves, [(ASSET_ID,)])


class OrganisationDuDepot(unittest.TestCase):
    """E025, E027 : arborescence du § 3 de la spec, suivie dans Git (pas seulement sur un poste)."""

    ARBORESCENCE = (
        "schemas/asset.schema.json", "schemas/sheet.schema.json", "schemas/usage.schema.json",
        "schemas/import-job.schema.json", "catalog/assets", "catalog/sheets", "catalog/universes",
        "sources/original-sheets", "sources/editable", "sprites/characters", "sprites/kitchen",
        "sprites/environments", "sprites/ui", "atlases", "thumbnails", "generated/catalog.json",
        "generated/usage-index.json", "generated/search-index.json", "tools/cli", "tools/discovery",
        "tools/extract", "tools/validate", "tools/index", "tools/publish", "tests/fixtures", "tests/unit",
        "tests/integration", "tests/e2e", "docs/AGENTS.md", "docs/ARCHITECTURE.md", "docs/CONTRIBUTING.md",
        "docs/MIGRATION.md", ".gitattributes", "README.md",
        # Écart validé par David (HL-538, condition 2) : Woodpecker au lieu de .github/workflows.
        ".woodpecker/scan.yml", ".woodpecker/validate.yml", ".woodpecker/build-index.yml", ".woodpecker/release.yml",
    )

    def test_chaque_chemin_du_paragraphe_3_est_suivi_par_git(self):
        import subprocess
        suivis = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True,
                                check=True).stdout.splitlines()
        for chemin in self.ARBORESCENCE:
            with self.subTest(chemin=chemin):
                self.assertTrue(any(f == chemin or f.startswith(chemin + "/") for f in suivis), chemin)


class DocumentationImperative(unittest.TestCase):
    """E126 à E135 (§ 12 AGENTS.md, les 10 règles mot pour mot), E029 (Git LFS), E064 (codes de retour)."""

    REGLES = (
        "SEARCH BEFORE CREATE ; REUSE BEFORE REINVENT.",
        "Scanner l'existant avant tout nouvel asset ; ne jamais réimplémenter sans justification une fonction "
        "déjà disponible dans les outils ou bibliothèques libres.",
        "Toute nouvelle ressource reçoit ID, description, origine, orientation, état, provenance et usages.",
        "Aucune licence, origine, coordonnée ou compatibilité inventée.",
        "Ne jamais écraser un asset publié ; versionner les variantes et dérivations.",
        "Headless first ; aucune manipulation graphique humaine requise pour le pipeline nominal.",
        "Ne pas modifier les jeux pendant l'inventaire initial.",
        "Toute mutation passe par PR et CI ; ne pas contourner les tests.",
        "Ne pas exposer les assets privés ni les secrets dans les dépôts publics.",
        "Mettre à jour l'index des usages après tout ajout, modification ou suppression de référence dans un jeu.",
    )

    def test_les_dix_regles_numerotees_dans_agents_md(self):
        texte = (ROOT / "docs" / "AGENTS.md").read_text(encoding="utf-8")
        for numero, regle in enumerate(self.REGLES, 1):
            with self.subTest(regle=numero):
                self.assertIn(f"{numero}. {regle}", texte)

    def test_git_lfs_decision_ecrite(self):
        texte = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertRegex(" ".join(texte.split()), r"Git LFS reste une option")

    def test_codes_de_retour_documentes_egaux_aux_codes_du_programme(self):
        from tools.core.exit_codes import ExitCode
        attendus = {int(code) for code in ExitCode}
        for doc in ("README.md", "docs/ARCHITECTURE.md"):
            with self.subTest(doc=doc):
                texte = (ROOT / doc).read_text(encoding="utf-8")
                self.assertEqual({int(n) for n in re.findall(r"^\| (\d) \|", texte, re.M)}, attendus)


class GardesDeConception(unittest.TestCase):
    """E035 (aucune valeur de l'exemple contractuel codée en dur) et E071 (ni PostgreSQL ni service permanent)."""

    EXEMPLE = ("asset-kitchen-whisk-0001", "sheet-kitchen-multiview-001", "sprites/kitchen/whisk.png")
    INTERDITS = re.compile(r"(?i)^(psycopg|asyncpg|sqlalchemy|pg8000|flask|fastapi|django|uvicorn|gunicorn|celery|redis)")

    def test_identifiants_de_l_exemple_absents_du_code(self):
        for fichier in sorted((ROOT / "tools").rglob("*.py")):
            texte = fichier.read_text(encoding="utf-8")
            for valeur in self.EXEMPLE:
                with self.subTest(fichier=fichier.name, valeur=valeur):
                    self.assertNotIn(valeur, texte)

    def test_aucune_base_serveur_ni_service_permanent(self):
        lignes = [l.strip() for l in (ROOT / "requirements.txt").read_text().splitlines() if l.strip()]
        self.assertTrue(lignes)
        self.assertEqual([l for l in lignes if self.INTERDITS.match(l)], [])
        for fichier in sorted((ROOT / "tools").rglob("*.py")):
            texte = fichier.read_text(encoding="utf-8")
            with self.subTest(fichier=fichier.name):
                self.assertNotRegex(texte, r"serve_forever|HTTPServer|socketserver|import psycopg")
