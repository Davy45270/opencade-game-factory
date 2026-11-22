"""EXT-002 P1/P2 et lignes restantes : LV-16 similarité expliquée, LV-17 jeux libres (licence vérifiée par source),
LV-18 captures et revue non bloquante, LV-19 bot de pilotage kart, LV-20 catalogue web statique, E205 pipeline
request → … → PR, E207 unicité d'un puzzle si exigée, E197 mise à jour des usages par PR. Hors ligne."""
import json
import subprocess
import sys
from pathlib import Path
from unittest import TestCase, mock

from tests.unit.test_ext001_sources import FauxWeb
from tests.unit.test_ext002 import ANNEAU, CIRCUIT, GIT, NiveauxFixture, _circuit, tiled
from tests.unit.test_ext002_jeux import MIT, casse_tete

DONJON = """
#########
#S..k...#
#...#...#
#...D..G#
#########
"""
DONJON2 = """
#########
#S..k...#
#...#...#
#...D.G.#
#########
"""
PLATEFORME = """
..........
S.......G.
##########
"""
EPINGLE = """
##########
#TTTTTTTT#
#TsTTTTaT#
#T######T#
#TcTTTTbT#
##########
"""


class Similarite(NiveauxFixture, TestCase):
    """LV-16 : classement et score explicables."""

    def test_le_plus_proche_d_abord_et_score_decompose(self):
        a = self.importer("a", DONJON, kind="dungeon")
        b = self.importer("b", DONJON2, kind="dungeon")
        c = self.importer("c", PLATEFORME, kind="platformer")
        res = self.lv("search", "--similar-to", a)
        ids = [r["id"] for r in res["results"]]
        self.assertEqual(ids[:2], [b, c])
        premier = res["results"][0]
        for composante in ("genre", "dimensions", "entites", "structure"):
            self.assertIn(composante, premier["explication"])
        self.assertAlmostEqual(premier["score"], round(sum(v["contribution"] for v in premier["explication"].values()), 4),
                               places=3)
        self.assertGreater(premier["score"], res["results"][1]["score"])


class JeuxLibres(NiveauxFixture, TestCase):
    """LV-17 : la licence des cartes se vérifie PAR SOURCE ; celle du code du dépôt ne la donne pas."""

    SHA = "b" * 40

    def liste(self, licence="LicenseRef-Domaine-Public-Declare", fichier="exemples/README.md"):
        (self.root / "external").mkdir(exist_ok=True)
        (self.root / "external" / "niveaux-libres.json").write_text(json.dumps({"schemaVersion": "1.0", "sources": [
            {"id": "chevalier", "repo": "exemple/editeur", "ref": self.SHA, "paths": r"^exemples/.*\.tmj$",
             "licence": licence, "licenceFile": fichier, "codeLicence": "GPL-2.0-or-later", "kind": "platformer",
             "review": {"licence": "README du dossier : domaine public", "securite": "JSON seuls", "par": "registre",
                        "date": "2026-11-22", "pr": "forge#0"}}]}))

    def web(self, readme):
        raw = f"https://raw.githubusercontent.com/exemple/editeur/{self.SHA}"
        faux = FauxWeb({
            f"https://api.github.com/repos/exemple/editeur/git/trees/{self.SHA}?recursive=1": (200, json.dumps({
                "tree": [{"path": "exemples/carte.tmj", "type": "blob"}, {"path": "COPYING", "type": "blob"}]}), {}),
            f"{raw}/exemples/carte.tmj": (200, json.dumps(tiled(PLATEFORME)), {}),
            f"{raw}/exemples/README.md": (200, readme, {})})
        for p in (mock.patch("urllib.request.urlopen", faux), mock.patch("time.sleep", lambda s: None)):
            p.start()
            self.addCleanup(p.stop)

    def test_cartes_en_domaine_public_verifie_au_meme_commit(self):
        self.liste()
        self.web("This example is by someone and released to the public domain.\n")
        res = self.lv("libre", "--id", "chevalier")
        (niveau,) = res["created"]
        fiche = self.lv("inspect", niveau)["level"]
        self.assertEqual((fiche["origin"]["licenseStatus"], fiche["origin"]["license"]),
                         ("verified", "LicenseRef-Domaine-Public-Declare"))

    def test_licence_des_cartes_non_prouvee_publication_refusee(self):
        self.liste()
        self.web("Example maps for the editor.\n")
        (niveau,) = self.lv("libre", "--id", "chevalier")["created"]
        self.assertEqual(self.lv("inspect", niveau)["level"]["origin"]["licenseStatus"], "unknown")
        self.lv("publish", niveau, "--version", "1.0.0", code=5)


class Revue(NiveauxFixture, TestCase):
    """LV-18 : capture PNG sans écran et rapport de revue NON bloquant (jamais un verdict d'amusement)."""

    def test_capture_et_rapport_non_bloquant(self):
        n = self.importer("d", DONJON, kind="dungeon")
        dossier = self.root / "revue"
        res = self.lv("review", n, "--out", str(dossier))
        self.assertEqual(res["status"], "report")
        png = dossier / f"{n}.png"
        self.assertTrue(png.read_bytes().startswith(b"\x89PNG"))
        rapport = json.loads((dossier / f"{n}.json").read_text())
        self.assertFalse(rapport["bloquant"])
        self.assertIn("revueHumaine", rapport)
        mur = self.importer("m", DONJON.replace("D..G", "D.#G").replace("...D", "#..D"), kind="dungeon")
        self.assertEqual(self.lv("review", mur, "--out", str(dossier))["status"], "report")   # jamais bloquant


class BotKart(NiveauxFixture, TestCase):
    """LV-19 : trajectoire validée par un bot à modèle de bicyclette (rayon de braquage du profil de kart)."""

    def profil(self, rayon):
        p = self.root / f"kart-{rayon}.json"
        p.write_text(json.dumps({"circuit": {"kart": {"id": "kart-a", "version": "1.0.0", "turningRadius": rayon,
                                                      "maxSpeed": 6.0, "grip": 8.0}}}))
        return str(p)

    def test_anneau_large_tour_mesure(self):
        n = self.importer("anneau", tiled(_circuit(ANNEAU), entities=CIRCUIT, track=True), kind="circuit")
        res = self.lv("simulate", n, "--agent", "kart-bot", "--profile", self.profil(0.8))
        self.assertEqual(res["status"], "pass")
        bot = res["metrics"]["bot"]
        self.assertEqual(bot["sortiesDePiste"], 0)
        self.assertGreater(bot["tourSecondes"], 0)
        self.assertEqual(bot["pointsDeControle"], [1, 2, 3])

    def test_epingle_trop_serree_pour_le_kart(self):
        n = self.importer("epingle", tiled(EPINGLE, entities={**CIRCUIT}, track=True), kind="circuit")
        res = self.lv("simulate", n, "--agent", "kart-bot", "--profile", self.profil(6.0), code=4)
        self.assertIn("kart-off-track", self.codes(res))


class CatalogueWeb(NiveauxFixture, TestCase):
    """LV-20 : catalogue web statique, contrôlé (--check échoue sur une page périmée)."""

    def test_pages_et_controle(self):
        a = self.importer("a", DONJON, kind="dungeon")
        dossier = self.root / "site"
        res = self.lv("site", "--out", str(dossier))
        self.assertEqual(res["pages"], 2)
        index = (dossier / "index.html").read_text()
        self.assertIn(a, index)
        self.assertIn('data-genre="dungeon"', index)
        self.assertTrue((dossier / f"{a}.html").is_file() and (dossier / f"{a}.png").is_file())
        self.assertEqual(self.lv("site", "--out", str(dossier), "--check")["status"], "a-jour")
        # Même image, octets compressés différents (autre zlib) : toujours à jour.
        from PIL import Image
        Image.open(dossier / f"{a}.png").save(dossier / f"{a}.png", compress_level=1)
        self.assertEqual(self.lv("site", "--out", str(dossier), "--check")["status"], "a-jour")
        (dossier / f"{a}.html").write_text("périmé")
        self.lv("site", "--out", str(dossier), "--check", code=4)


class Pipeline(NiveauxFixture, TestCase):
    """E205 : request → search → candidate scoring → reuse/derive/generate → normalize → validators → simulated
    playtest → visual render → PR, chaque étape tracée ; la PR est une branche commitée (jamais main)."""

    def test_reutilise_un_niveau_existant_avant_de_generer(self):
        existant = self.importer("d", DONJON, kind="dungeon")
        req = self.root / "demande.json"
        req.write_text(json.dumps({"genre": "dungeon", "query": "", "constraints": {"width": 9, "height": 5}}))
        res = self.lv("pipeline", "--request", str(req), "--seed", "7", "--dry-run")
        etapes = [e["etape"] for e in res["etapes"]]
        self.assertEqual(etapes, ["request", "search", "candidate-scoring", "reuse/derive/generate", "normalize",
                                  "validators", "simulated-playtest", "visual-render", "pr"])
        self.assertEqual((res["decision"]["action"], res["decision"]["id"]), ("reuse", existant))

    def test_genere_puis_branche_de_pr(self):
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), *GIT, "commit", "-q", "--allow-empty", "-m", "base"], check=True)
        req = self.root / "demande.json"
        req.write_text(json.dumps({"genre": "dungeon", "query": "introuvable", "constraints": {
            "width": 30, "height": 20, "minRoom": 4}}))
        res = self.lv("pipeline", "--request", str(req), "--seed", "42", "--branch", "niveaux/essai")
        self.assertEqual(res["decision"]["action"], "generate")
        self.assertEqual(res["pr"]["branch"], "niveaux/essai")
        main = subprocess.run(["git", "-C", str(self.root), "rev-parse", "main"], capture_output=True, text=True).stdout
        tete = subprocess.run(["git", "-C", str(self.root), "rev-parse", "niveaux/essai"], capture_output=True,
                              text=True).stdout
        self.assertNotEqual(main, tete)
        self.assertIn("seed 42", res["pr"]["body"])


class PuzzleUnicite(NiveauxFixture, TestCase):
    """E207 : unicité mesurée par le moteur du jeu quand le profil l'exige ; sinon déclarée non exigée."""

    MOTEUR = '''import json, sys
n = json.load(open(sys.argv[1]))
print("SOLUTIONS %d" % n.get("solutions", 1))
print(f"OK {n['id']} résolu")
'''

    def puzzle(self, solutions, exige):
        jeu = self.repos / f"moteur-{solutions}"
        jeu.mkdir(exist_ok=True)
        (jeu / "v.py").write_text(self.MOTEUR)
        profil = self.root / f"p-{solutions}-{exige}.json"
        profil.write_text(json.dumps({"engine": {"cwd": str(jeu), "command": [sys.executable, "v.py"]},
                                      "puzzle": {"requireUnique": exige}}))
        niveau = {**casse_tete(), "solutions": solutions}
        repo = self.depot(f"cozy-{solutions}-{exige}", {"content/levels/001-salon.json": niveau, "LICENSE": MIT})
        n = self.lv("import", "--source", "local", "--repo", str(repo), "--game", "cozy", "--license", "MIT",
                    "--license-evidence", "LICENSE")["created"][0]
        return n, str(profil)

    def test_unicite_exigee_deux_solutions_echec(self):
        n, p = self.puzzle(2, True)
        self.assertIn("puzzle-not-unique", self.codes(self.lv("validate", n, "--profile", p, code=4)))

    def test_unicite_exigee_une_solution_et_contrat_des_sept_points(self):
        n, p = self.puzzle(1, True)
        res = self.lv("validate", n, "--profile", p)
        contrat = res["checks"]["puzzle"]["metrics"]["contrat"]
        self.assertEqual(contrat["unicite"], "unique (1 solution)")
        self.assertEqual(contrat["solutionDeReference"], "meta.solution")
        for cle in ("etatInitial", "regles", "objectifs", "solveur", "difficulte"):
            self.assertIn(cle, contrat)

    def test_unicite_non_exigee_dite_telle_quelle(self):
        n, p = self.puzzle(3, False)
        res = self.lv("validate", n, "--profile", p)
        self.assertEqual(res["checks"]["puzzle"]["metrics"]["contrat"]["unicite"], "non exigée par le profil")


class UsagesParPR(NiveauxFixture, TestCase):
    """E197 : l'adoption d'une version publiée met à jour level.lock.json du jeu sur une BRANCHE, jamais sur main."""

    def test_branche_du_jeu_mise_a_jour_main_intacte(self):
        n = self.importer("d", DONJON, kind="dungeon")
        self.lv("publish", n, "--version", "1.0.0")
        jeu = self.depot("jeu", {"README.md": "jeu"})
        subprocess.run(["git", "-C", str(jeu), "branch", "-M", "main"], check=True)
        avant = self.head(jeu)
        res = self.lv("adopt", n, "--version", "1.0.0", "--repo", str(jeu), "--game", "jeu")
        self.assertEqual(self.head(jeu), avant)                                   # main intacte
        branche = res["branch"]
        verrou = json.loads(subprocess.run(["git", "-C", str(jeu), "show", f"{branche}:level.lock.json"],
                                           capture_output=True, text=True, check=True).stdout)
        (entree,) = verrou["levels"]
        self.assertEqual((entree["id"], entree["version"]), (n, "1.0.0"))
        self.assertEqual(len(entree["sha256"]), 64)
        self.lv("adopt", n, "--version", "9.9.9", "--repo", str(jeu), "--game", "jeu", code=3)
