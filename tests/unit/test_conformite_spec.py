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


class BinairesDuRegistre(CatalogueFixture, unittest.TestCase):
    """E078, E079 : la CI du registre contrôle empreintes, dimensions et alpha des binaires qu'il garde."""

    def setUp(self):
        super().setUp()
        import hashlib
        import io
        from PIL import Image
        image = Image.new("RGBA", (16, 16), (200, 30, 30, 255))
        image.putpixel((0, 0), (0, 0, 0, 0))
        flux = io.BytesIO()
        image.save(flux, "PNG")
        self.octets = flux.getvalue()
        (self.root / "sprites").mkdir()
        (self.root / "sprites" / "fouet.png").write_bytes(self.octets)
        self.asset["files"] = {"locations": [], "registry": "sprites/fouet.png"}
        self.asset["sha256"] = hashlib.sha256(self.octets).hexdigest()
        self.write("ids.json", {f"file:sha256:{self.asset['sha256']}": ASSET_ID})

    def codes(self):
        self.write_asset()
        code, payload = self.cli("validate")
        return code, {issue["code"] for issue in payload.get("issues", [])}

    def test_binaire_conforme_puis_chaque_ecart_refuse(self):
        self.assertEqual(self.codes(), (0, set()))
        cas = {
            "registry-digest": lambda a: a.update(sha256="d" * 64),
            "registry-dimensions": lambda a: a.update(dimensions={"width": 16, "height": 17}),
            "registry-alpha": lambda a: a.update(alpha=False),
        }
        for attendu, alterer in cas.items():
            with self.subTest(ecart=attendu):
                self.asset = copy.deepcopy(self.asset_sain())
                alterer(self.asset)
                code, codes = self.codes()
                self.assertEqual(code, 1)
                self.assertIn(attendu, codes)
        self.asset = self.asset_sain()
        (self.root / "sprites" / "fouet.png").unlink()
        self.assertEqual(self.codes(), (1, {"missing-registry-file"}))

    def asset_sain(self):
        import hashlib
        sain = copy.deepcopy(ASSET)
        sain["files"] = {"locations": [], "registry": "sprites/fouet.png"}
        sain["sha256"] = hashlib.sha256(self.octets).hexdigest()
        return sain


class DetourageSansInterface(unittest.TestCase):
    """E018, E104 : le pipeline headless détoure (recette `detour` de `derive`), sans rien deviner."""

    def planche(self):
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (40, 40), (255, 0, 255))
        dessin = ImageDraw.Draw(image)
        dessin.ellipse((5, 5, 34, 34), fill=(200, 30, 30))
        # Trou de la couleur du fond, enfermé dans le sujet : il n'est pas relié au bord.
        dessin.rectangle((18, 18, 21, 21), fill=(255, 0, 255))
        return image

    def test_fond_relie_au_bord_transparent_sujet_et_trou_interieur_intacts(self):
        from tools.creation import transform
        resultat = transform(self.planche(), {"detour": {"tolerance": 8}})
        alpha = resultat.getchannel("A")
        for coin in ((0, 0), (39, 0), (0, 39), (39, 39), (2, 20)):
            self.assertEqual(alpha.getpixel(coin), 0, coin)
        for interieur in ((10, 20), (19, 19), (30, 20)):
            self.assertEqual(alpha.getpixel(interieur), 255, interieur)

    def test_coins_discordants_refuses(self):
        from tools.core.catalog import InvalidJSON
        from tools.creation import transform
        image = self.planche()
        image.putpixel((39, 39), (0, 255, 0))
        with self.assertRaises(InvalidJSON):
            transform(image, {"detour": {"tolerance": 8}})
        for invalide in ({"tolerance": -1}, {"tolerance": 300}, {"tolerance": 1.5}, {}):
            with self.subTest(options=invalide), self.assertRaises(InvalidJSON):
                transform(self.planche(), {"detour": invalide})


class SynchronisationParPR(unittest.TestCase):
    """E042, E073 : la synchronisation pousse une branche sync/… et OUVRE une PR vers main, sans toucher main
    ni le jeu ; rejouée, elle retrouve la même PR ; le jeton n'apparaît nulle part."""

    JETON = "jeton-de-fixture-sync-pr"

    def setUp(self):
        import json as _json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from tests.acceptance import _monde as M
        self.M = M
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        self.assertEqual(self.world.scan().code, 0)
        self.world.commiter_registre("Import de fixture")
        self.requetes, ouvertes = [], []
        test = self

        class Forge(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def repondre(self, code, valeur):
                corps = _json.dumps(valeur).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def do_POST(self):
                corps = _json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                test.requetes.append(("POST", self.path, self.headers.get("Authorization"), corps))
                if ouvertes:
                    return self.repondre(409, {"message": "pull request already exists"})
                ouvertes.append({"number": 7, "html_url": "http://forge/pulls/7", "head": {"ref": corps["head"]},
                                 "base": {"ref": corps["base"]}})
                self.repondre(201, ouvertes[0])

            def do_GET(self):
                test.requetes.append(("GET", self.path, self.headers.get("Authorization"), None))
                self.repondre(200, ouvertes)

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Forge)
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        self.addCleanup(self.serveur.server_close)
        self.addCleanup(self.serveur.shutdown)
        self.distant = self.world.racine / "forge.git"
        self.world.git(self.world.racine, "init", "-q", "--bare", str(self.distant))

    def sync(self, *extra, jeton=True):
        import subprocess
        import sys
        from tests.acceptance import _contrat as C
        env = C.environnement(self.world.home)
        if jeton:
            env["ASSETCTL_FORGEJO_TOKEN"] = self.JETON
        p = subprocess.run([sys.executable, str(self.world.registre / "assetctl"), "sync", "--branch", "sync/pr",
                            "--open-pr", "--forge-repo", "david/registre",
                            "--forge-url", f"http://127.0.0.1:{self.serveur.server_port}",
                            "--pr-remote", self.distant.as_uri(), *extra, "--json"],
                           cwd=self.world.registre, env=env, capture_output=True, text=True, timeout=300)
        self.assertNotIn(self.JETON, p.stdout + p.stderr)
        import json as _json
        return p.returncode, _json.loads(p.stdout)

    def test_pr_ouverte_puis_retrouvee_main_et_jeu_intacts(self):
        from tests.acceptance import _contrat as C
        main = self.world.git(self.world.registre, "rev-parse", "main")
        self.M.ajouter_commit(self.world, "jeu-a", {"public/assets/sync-pr.png": self.M.png(self.M.uni(5, 6, (9, 99, 199, 255)))},
                              (), "2026-03-03T10:00:00Z", "Ajout pour la PR de sync")
        jeu = C.empreinte_arbre(self.world.depot("jeu-a"))
        code, premier = self.sync()
        self.assertEqual(code, 0, premier)
        self.assertEqual(premier["pullRequest"], {"number": 7, "url": "http://forge/pulls/7", "created": True})
        poste = [r for r in self.requetes if r[0] == "POST"][0]
        self.assertEqual(poste[1], "/api/v1/repos/david/registre/pulls")
        self.assertEqual(poste[2], f"token {self.JETON}")
        self.assertEqual((poste[3]["head"], poste[3]["base"]), ("sync/pr", "main"))
        self.assertIn("Copies analysées · 1", poste[3]["body"])
        pousse = self.world.git(self.distant, "rev-parse", "refs/heads/sync/pr")
        self.assertEqual(pousse, premier["commit"])
        self.assertNotIn("main", self.world.git(self.distant, "for-each-ref", "--format=%(refname:short)"))
        code, second = self.sync()
        self.assertEqual(code, 0, second)
        self.assertEqual(second["pullRequest"]["number"], 7)
        self.assertFalse(second["pullRequest"]["created"])
        self.assertEqual(self.world.git(self.world.registre, "rev-parse", "main"), main)
        self.assertEqual(C.empreinte_arbre(self.world.depot("jeu-a")), jeu)

    def test_sans_jeton_pas_de_pr_et_code_4(self):
        self.M.ajouter_commit(self.world, "jeu-a", {"public/assets/sync-pr.png": self.M.png(self.M.uni(5, 6, (9, 99, 199, 255)))},
                              (), "2026-03-03T10:00:00Z", "Ajout pour la PR de sync")
        code, resultat = self.sync(jeton=False)
        self.assertEqual((code, resultat["error"]), (4, "sync-pr-failed"))
        self.assertEqual([r for r in self.requetes if r[0] == "POST"], [])
        self.assertEqual(self.world.git(self.distant, "for-each-ref"), "")
