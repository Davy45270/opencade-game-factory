"""EXT-002 sur les niveaux réels des jeux : plans en grille de Pestouille, graphe de monde et son complément,
types d'objets en français, miroirs nus de scan-repos, licence MIT, import transactionnel (HL-538)."""
import json
import subprocess
from unittest import TestCase

from tests.unit.test_ext002 import NiveauxFixture, tiled

MIT = ("MIT License\n\nCopyright (c) 2026 Davy45270\n\nPermission is hereby granted, free of charge, to any "
       "person obtaining a copy of this software...\n")


def plan(boss_mure=False):
    """Même structure qu'un plan de content/maps de pestouille-rpg (32 × 24 réduit à 10 × 7)."""
    terrain = ["##########", "#........#", "#........#", "#........#", "#........#", "#........#", "##########"]
    if boss_mure:
        terrain[1], terrain[2], terrain[3] = "#.#......#", "##.......#", "#........#"
    return {"id": "foret_murmures_dungeon", "regionId": "foret_murmures", "width": 10, "height": 7, "tileSize": 16,
            "terrain": terrain, "spawn": {"x": 5, "y": 3},
            "exits": [{"id": "exit_next", "at": {"x": 8, "y": 3}, "targetMapId": "grottes_overworld",
                       "targetSpawn": "main", "requiredFlags": ["flame_1"]}],
            "entities": [{"id": "checkpoint_1", "kind": "checkpoint", "at": {"x": 4, "y": 3}},
                         {"id": "boss_1", "kind": "boss", "at": {"x": 1, "y": 1}, "definitionId": "boss_foret"}]}


GRAPHE = {"schemaVersion": 1, "id": "first_flame",
          "regions": {"village": ["place", "forest_gate"], "temple": ["hall", "key", "antechamber", "boss"]},
          "transitions": [["village.forest_gate", "temple.hall"], ["temple.hall", "temple.key"],
                          ["temple.key", "temple.antechamber"], ["temple.antechamber", "temple.boss"]],
          "gates": [{"target": "temple.hall", "requires": "party_four"}],
          "checkpoints": ["village.place", "temple.antechamber"]}
COMPLEMENT = {"schemaVersion": 1, "id": "first_flame", "start": "village.place",
              "gates": [{"target": "temple.antechamber", "requires": "root_key"}],
              "grants": {"village.place": "party_four", "temple.key": "root_key"}}


class EXT002Jeux(NiveauxFixture, TestCase):
    def depot_mit(self, name, files):
        return self.depot(name, {**files, "LICENSE": MIT})

    def importer_mit(self, repo, name, code=0):
        return self.lv("import", "--source", "local", "--repo", str(repo), "--game", name, "--license", "MIT",
                       "--license-evidence", "LICENSE", code=code)

    def test_plan_en_grille_pestouille_valide_et_boss_mure_insoluble(self):
        repo = self.depot_mit("pestouille", {"content/maps/foret/dungeon.json": plan()})
        fiche = self.importer_mit(repo, "pestouille")
        self.assertEqual(fiche["licenseStatus"], "verified")
        (niveau,) = fiche["created"]
        relu = self.lv("inspect", niveau)["level"]
        self.assertEqual((relu["kind"], relu["format"]), ("dungeon", "ascii-grid"))
        self.assertIn("décors posés par le jeu", " ".join(relu["losses"]))
        self.assertEqual(self.lv("validate", niveau)["status"], "pass")
        mure = self.depot_mit("pestouille-mure", {"content/maps/foret/dungeon.json": plan(boss_mure=True)})
        (coince,) = self.importer_mit(mure, "pestouille-mure")["created"]
        self.assertIn("dungeon-unsolvable", self.codes(self.lv("validate", coince, code=4)))

    def test_graphe_de_monde_avec_son_complement(self):
        repo = self.depot_mit("monde", {"content/world/world_graph.json": GRAPHE,
                                        "content/world/first_flame.json": COMPLEMENT})
        created = self.importer_mit(repo, "monde")["created"]
        (graphe,) = [c for c in created if c.endswith("first-flame")]
        rapport = self.lv("validate", graphe)
        self.assertEqual(rapport["status"], "pass")
        sans_cle = {**COMPLEMENT, "grants": {"village.place": "party_four"}}
        cassé = self.depot_mit("monde-casse", {"content/world/world_graph.json": GRAPHE,
                                               "content/world/first_flame.json": sans_cle})
        (graphe,) = [c for c in self.importer_mit(cassé, "monde-casse")["created"] if c.endswith("first-flame")]
        echec = self.lv("validate", graphe, code=4)
        self.assertTrue({"quest-unreachable", "place-unreachable"} <= self.codes(echec))

    def test_region_sans_transition_interne_se_parcourt_librement(self):
        """Règle du jeu (pestouille-rpg, packages/world) : sans elle, la place du village serait un cul-de-sac."""
        repo = self.depot_mit("libre", {"content/world/world_graph.json": GRAPHE,
                                        "content/world/first_flame.json": COMPLEMENT})
        (graphe,) = [c for c in self.importer_mit(repo, "libre")["created"] if c.endswith("first-flame")]
        contenu = self.lv("inspect", graphe)["level"]["content"]["graph"]
        self.assertIn(["village.forest_gate", "village.place"], contenu["edges"])
        self.assertNotIn(["temple.boss", "temple.hall"], contenu["edges"])

    def test_types_francais_lieu_inatteignable(self):
        lieu = {"L": ("lieu", {})}
        ouvert = self.depot_mit("fr", {"content/tiled/foret.json": tiled("S..L", entities=lieu)})
        (niveau,) = self.importer_mit(ouvert, "fr")["created"]
        self.assertEqual(self.lv("validate", niveau)["status"], "pass")
        ferme = self.depot_mit("fr-ferme", {"content/tiled/foret.json": tiled("S.#L", entities=lieu)})
        (niveau,) = self.importer_mit(ferme, "fr-ferme")["created"]
        self.assertIn("place-unreachable", self.codes(self.lv("validate", niveau, code=4)))

    def test_import_transactionnel_rien_ecrit_si_une_fiche_est_invalide(self):
        vide = {"schemaVersion": 1, "id": "vide", "regions": {}, "transitions": []}
        repo = self.depot_mit("mixte", {"levels/bon.tmj": tiled("S.G"), "content/world/vide.json": vide})
        echec = self.importer_mit(repo, "mixte", code=2)
        self.assertIn("invalid-record", self.codes(echec))
        self.assertFalse((self.root / "catalog" / "levels").exists() and
                         any((self.root / "catalog" / "levels").iterdir()))
        self.assertFalse((self.root / "originals").exists())

    def test_licence_mit_confirmee_par_le_texte_seulement(self):
        repo = self.depot("faux-mit", {"levels/a.tmj": tiled("S.G"), "LICENSE": "Tous droits réservés.\n"})
        refus = self.lv("import", "--source", "local", "--repo", str(repo), "--license", "MIT",
                        "--license-evidence", "LICENSE")
        self.assertEqual(refus["licenseStatus"], "unknown")

    def test_miroir_nu_de_scan_repos_lu_par_git(self):
        source = self.depot_mit("source", {"levels/a.tmj": tiled("S.G")})
        nu = self.repos / "miroir.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(source), str(nu)], check=True)
        rapport = self.lv("discover", "--scope", self.scope([{"name": "miroir", "path": str(nu)}]), "--dry-run")
        (depot,) = rapport["repos"]
        self.assertEqual(depot["commit"], self.head(source))
        self.assertEqual(len(depot["levels"]), 1)
        self.assertGreaterEqual(rapport["coverage"]["detected"], 1)


MOTEUR = '''import json, sys
niveau = json.load(open(sys.argv[1]))
# Règle du « jeu » de la fixture : un objet ne peut pas se bloquer lui-même.
fautif = [o["id"] for o in niveau["objects"] if o["id"] in o.get("blockedBy", [])]
print(f"ÉCHEC {niveau['id']} : cycle de blocage : {fautif[0]}" if fautif else f"OK {niveau['id']} 2 objets, 3 états")
sys.exit(1 if fautif else 0)
'''


def casse_tete(cycle=False):
    """Même structure qu'un niveau de cozy-room-sort (rules, objects, scoring, meta.solution)."""
    return {"schemaVersion": "1.2", "id": "001-salon", "name": "Le salon", "theme": "salon", "rules": {},
            "categories": [{"id": "plantes"}], "boxes": [],
            "objects": [{"id": "pile-1", "blockedBy": ["pile-1"] if cycle else []}, {"id": "pile-2", "blockedBy": []}],
            "scoring": {"threeStarsMaxBuffered": 0}, "meta": {"solution": ["pile-1", "pile-2"]}}


class EXT002Puzzle(NiveauxFixture, TestCase):
    """E192/E207 : les règles du puzzle restent au jeu ; le validateur appelle son moteur sans écran."""

    def profil(self, sans_moteur=False):
        jeu = self.repos / "moteur"
        jeu.mkdir(exist_ok=True)
        (jeu / "valider.py").write_text(MOTEUR)
        path = self.root / "profil-puzzle.json"
        import sys
        path.write_text(json.dumps({} if sans_moteur else {"engine": {"cwd": str(jeu),
                                                                       "command": [sys.executable, "valider.py"]}}))
        return str(path)

    def importer_puzzle(self, name, cycle=False):
        repo = self.depot(name, {"content/levels/001-salon.json": casse_tete(cycle), "LICENSE": MIT})
        result = self.lv("import", "--source", "local", "--repo", str(repo), "--game", name, "--license", "MIT",
                         "--license-evidence", "LICENSE")
        return result["created"][0]

    def test_moteur_du_jeu_juge_le_niveau(self):
        bon = self.importer_puzzle("cozy")
        fiche = self.lv("inspect", bon)["level"]
        self.assertEqual((fiche["kind"], fiche["format"]), ("puzzle", "game-puzzle"))
        self.assertEqual(fiche["content"]["puzzle"]["meta"]["solution"], ["pile-1", "pile-2"])
        rapport = self.lv("validate", bon, "--profile", self.profil())
        self.assertEqual(rapport["checks"]["puzzle"]["metrics"]["verdict"], "OK 001-salon 2 objets, 3 états")
        mauvais = self.importer_puzzle("cozy-cycle", cycle=True)
        echec = self.lv("validate", mauvais, "--profile", self.profil(), code=4)
        self.assertIn("puzzle-rejected-by-engine", self.codes(echec))
        self.assertIn("cycle de blocage", " ".join(d["message"] for d in echec["diagnostics"]))

    def test_sans_moteur_declare_jamais_pass(self):
        niveau = self.importer_puzzle("cozy-seul")
        self.assertEqual(self.lv("validate", niveau, "--profile", self.profil(sans_moteur=True), code=6)["status"],
                         "inconclusive")
