"""EXT-002 — niveaux : scénarios d'acceptation AT01 à AT20, hors ligne, sur fixtures versionnées dans ce fichier.

Les cartes sont dessinées en ASCII puis écrites en Tiled JSON, TMX ou LDtk : `#` mur, `S` apparition, `G` objectif,
`B` boss, `k`/`D` clé et porte rouges, `1`/`2` interrupteurs, `g` grille (1 et 2), `C` point de sauvegarde,
`T` piste, `^` danger. Aucune requête réseau ; les dépôts de jeux sont des dépôts git temporaires.
"""
import json
import os
import subprocess
import zipfile
from pathlib import Path
from unittest import TestCase, mock

from tests.unit.test_oracles import ASSET_ID, CatalogueFixture

TILE = 16
GIT = ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false"]
CC0 = "Creative Commons Zero, CC0 1.0 Universal\nhttps://creativecommons.org/publicdomain/zero/1.0/\n"


def tiled(art, entities=None, extra_layers=(), properties=(), tilesets=(), track=False):
    """ASCII → carte Tiled JSON. `entities` : {caractère: (type, propriétés)} en plus des caractères connus."""
    rows = [r for r in art.strip("\n").split("\n")]
    width, height = max(map(len, rows)), len(rows)
    rows = [r.ljust(width, ".") for r in rows]
    known = {"S": ("spawn", {}), "G": ("goal", {}), "B": ("boss", {}), "k": ("key", {"color": "red"}),
             "D": ("door", {"color": "red"}), "1": ("switch", {"switch": "s1"}), "2": ("switch", {"switch": "s2"}),
             "g": ("gate", {"switches": "s1,s2"}), "C": ("checkpoint", {}), "^": ("hazard", {}),
             **(entities or {})}
    solid = [1 if c == "#" else 0 for row in rows for c in row]
    objects, n = [], 0
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            if char in known:
                n += 1
                kind, props = known[char]
                objects.append({"id": n, "name": f"{kind}{n}", "type": kind, "x": x * TILE, "y": y * TILE,
                                "width": TILE, "height": TILE, "rotation": 0, "visible": True,
                                "properties": [{"name": k, "type": "string" if isinstance(v, str) else
                                                "bool" if isinstance(v, bool) else "int", "value": v}
                                               for k, v in sorted(props.items())]})
    layers = [{"id": 1, "name": "collision", "type": "tilelayer", "width": width, "height": height, "data": solid,
               "opacity": 1, "visible": True, "x": 0, "y": 0}]
    if track:
        layers.append({"id": 2, "name": "track", "type": "tilelayer", "width": width, "height": height,
                       "data": [0 if c in "#." else 1 for row in rows for c in row], "opacity": 1, "visible": True,
                       "x": 0, "y": 0})
    layers.append({"id": 3, "name": "entities", "type": "objectgroup", "objects": objects, "opacity": 1,
                   "visible": True, "x": 0, "y": 0, "draworder": "topdown"})
    return {"type": "map", "orientation": "orthogonal", "width": width, "height": height, "tilewidth": TILE,
            "tileheight": TILE, "infinite": False, "layers": layers + list(extra_layers), "renderorder": "right-down",
            "tilesets": list(tilesets) or [{"firstgid": 1, "name": "murs", "tilewidth": TILE, "tileheight": TILE,
                                            "tilecount": 1, "columns": 1, "image": "murs.png", "imagewidth": TILE,
                                            "imageheight": TILE}],
            "properties": list(properties), "tiledversion": "1.10.2", "version": "1.10"}


class NiveauxFixture(CatalogueFixture):
    def setUp(self):
        super().setUp()
        self.repos = self.root / "depots"
        self.repos.mkdir()

    def depot(self, name, files, commit=True):
        path = self.repos / name
        for rel, content in files.items():
            target = path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content if isinstance(content, bytes) else
                               content.encode() if isinstance(content, str) else json.dumps(content).encode())
        path.mkdir(parents=True, exist_ok=True)
        if not (path / ".git").exists():
            subprocess.run(["git", "init", "-q", str(path)], check=True)
        if commit:
            subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(path), *GIT, "commit", "-q", "--allow-empty", "-m", "fixture"],
                           check=True)
        return path

    def head(self, path):
        return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()

    def scope(self, repos):
        path = self.root / "scope.json"
        path.write_text(json.dumps({"repos": repos}))
        return str(path)

    def lv(self, *args, code=0):
        result = self.cli("level", *args)
        self.assertEqual(result[0], code, result[1])
        for field in ("operationId", "status", "artifacts", "diagnostics"):
            self.assertIn(field, result[1])
        return result[1]

    def importer(self, name, art_or_map, *extra, kind=None, license_=True, filename="niveau.tmj"):
        data = art_or_map if isinstance(art_or_map, dict) else tiled(art_or_map)
        files = {f"levels/{filename}": data}
        if license_:
            files["LICENSE.txt"] = CC0
        repo = self.depot(name, files)
        args = ["import", "--source", "local", "--repo", str(repo), "--game", name, *extra]
        if license_:
            args += ["--license", "CC0-1.0", "--license-evidence", "LICENSE.txt"]
        if kind:
            args += ["--kind", kind]
        result = self.lv(*args)
        return result["created"][0] if result["created"] else (result["observed"] or result["unchanged"])[0]

    def codes(self, payload):
        return {d["code"] for d in payload["diagnostics"]}


ANNEAU = """
###########
#TTTTTTTTT#
#TTTTTTTTT#
#TT#####TT#
#TT#####TT#
#TTTTTTTTT#
#TTTTTTTTT#
###########
"""


class EXT002Acceptation(NiveauxFixture, TestCase):
    def test_AT01_depot_vide(self):
        self.depot("vide", {})
        rapport = self.lv("discover", "--scope", self.scope([{"name": "vide", "path": "depots/vide"}]))
        self.assertEqual(rapport["coverage"], {"detected": 0, "inventoried": 0, "exceptions": 0, "ignored": 0,
                                               "classified": 0, "ratio": 1.0})
        self.assertEqual(rapport["repos"][0]["levels"], [])
        self.assertTrue(rapport["sourcesUnchanged"])

    def test_AT02_monorepo_multijeux_references_generateurs_sources_intactes(self):
        temple = tiled("S..\n.#.\n..G", entities={"t": ("trigger", {})})
        temple["layers"][-1]["objects"].append({"id": 99, "name": "t", "type": "transition", "x": 0, "y": 0,
                                               "width": 16, "height": 16, "properties": [{"name": "target",
                                                                                         "type": "string",
                                                                                         "value": "level-b"}]})
        repo = self.depot("mono", {
            "games/alpha/levels/temple.tmj": temple,
            "games/beta/maps/foret.tmx": TMX,
            "games/beta/maps/tiles/foret.tsx": TSX,
            "games/beta/src/load.ts": 'const m = load("maps/foret.tmx");\nconst n = `levels/${i}.tmj`;\n'
                                      'const d = new ROT.Map.Digger(40, 25);\n',
            "games/alpha/gen.py": 'carte = generate_dungeon(32, 24, seed=7)\nfichier = f"levels/{n}.tmj"\n',
            "package.json": {"name": "mono"}})
        avant = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}
        rapport = self.lv("discover", "--scope", self.scope([{"name": "mono", "path": "depots/mono", "games": {
            "games/alpha": "alpha", "games/beta": "beta"}}]))
        depot = rapport["repos"][0]
        self.assertEqual({(l["game"], l["file"]) for l in depot["levels"]},
                         {("alpha", "games/alpha/levels/temple.tmj"), ("beta", "games/beta/maps/foret.tmx")})
        temple_row = next(l for l in depot["levels"] if l["game"] == "alpha")
        self.assertEqual((temple_row["width"], temple_row["height"], temple_row["transitions"],
                          temple_row["triggers"], temple_row["collisionCells"]), (3, 3, 1, 0, 1))
        self.assertEqual(temple_row["layers"], ["collision", "entities"])
        self.assertIn({"file": "games/beta/src/load.ts", "game": "beta", "target": "maps/foret.tmx"},
                      depot["references"])
        self.assertEqual({(d["file"], d["status"]) for d in depot["dynamic"]},
                         {("games/beta/src/load.ts", "unresolved"), ("games/alpha/gen.py", "unresolved")})
        appels = {(g["call"], tuple(map(str, g["params"]))) for g in depot["generators"]}
        self.assertIn(("ROT.Map.Digger", ("40", "25")), appels)
        self.assertIn(("generate_dungeon", ("32", "24")), appels)
        self.assertEqual(depot["tilesets"][0]["file"], "games/beta/maps/tiles/foret.tsx")
        self.assertEqual(rapport["coverage"]["ratio"], 1.0)
        self.assertTrue(rapport["sourcesUnchanged"])
        self.assertEqual({p: p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}, avant)

    def test_AT03_import_repete_sans_doublon_et_nouveau_commit_meme_id(self):
        repo = self.depot("jeu", {"levels/a.tmj": tiled("S.G"), "LICENSE.txt": CC0})
        args = ["import", "--source", "local", "--repo", str(repo), "--game", "jeu"]
        premier = self.lv(*args)
        self.assertEqual(len(premier["created"]), 1)
        self.assertEqual(self.lv(*args)["unchanged"], premier["created"])
        (repo / "README.md").write_text("autre fichier")
        self.depot("jeu", {})
        nouveau = self.lv(*args)
        self.assertEqual((nouveau["created"], nouveau["observed"]), ([], premier["created"]))
        fiche = self.lv("inspect", premier["created"][0])["level"]
        self.assertEqual(len(fiche["observations"]), 2)
        self.assertEqual({tuple(sorted(o)) for o in fiche["observations"]},
                         {("commit", "contentSha256", "observedAt", "path", "provider", "repo")})
        self.assertEqual(len(list((self.root / "catalog" / "levels").glob("*.json"))), 1)
        self.assertEqual(len(list((self.root / "originals" / "sha256").iterdir())), 1)

    def test_AT04_format_inconnu_en_exception(self):
        self.depot("bizarre", {"maps/niveau.ldtk": b"\x00\x01 pas du json", "maps/scene.blend": b"BLENDER-v300",
                               "maps/donnees.xml": "<root/>", "maps/carte.json": {"pas": "une carte"}})
        rapport = self.lv("discover", "--scope", self.scope([{"name": "b", "path": "depots/bizarre"}]))
        exceptions = {e["file"]: e["reason"] for e in rapport["repos"][0]["exceptions"]}
        self.assertEqual(set(exceptions), {"maps/niveau.ldtk", "maps/scene.blend", "maps/donnees.xml",
                                           "maps/carte.json"})
        self.assertIn("Blender", exceptions["maps/scene.blend"])
        self.assertEqual((rapport["coverage"]["exceptions"], rapport["coverage"]["ratio"]), (4, 1.0))

    def test_AT05_tmx_avec_tileset_externe(self):
        repo = self.depot("foret", {"maps/foret.tmx": TMX, "maps/tiles/foret.tsx": TSX, "LICENSE.txt": CC0})
        cree = self.lv("import", "--source", "local", "--repo", str(repo), "--game", "foret", "--license", "CC0-1.0",
                       "--license-evidence", "LICENSE.txt")
        fiche = self.lv("inspect", cree["created"][0])["level"]
        tileset = fiche["content"]["tilesets"][0]
        self.assertEqual((tileset["source"], tileset["resolved"], tileset["name"]), ("tiles/foret.tsx", True, "foret"))
        self.assertEqual(fiche["dependencies"]["assets"], [{"id": ASSET_ID, "version": None}])
        self.assertEqual(fiche["content"]["layers"][0]["data"][:3], [1, 2147483649, 0])
        self.assertEqual(self.lv("validate", fiche["id"])["status"], "pass")
        manque = self.depot("orphelin", {"maps/foret.tmx": TMX})
        cree = self.lv("import", "--source", "local", "--repo", str(manque), "--game", "orphelin")
        self.assertIn("tileset-missing", self.codes(cree))

    def test_AT06_ldtk_entites_et_couches_conservees(self):
        repo = self.depot("ldtk", {"world.ldtk": LDTK, "LICENSE.txt": CC0})
        cree = self.lv("import", "--source", "local", "--repo", str(repo), "--game", "ldtk", "--license", "CC0-1.0",
                       "--license-evidence", "LICENSE.txt", "--kind", "dungeon")
        fiche = self.lv("inspect", cree["created"][0])["level"]
        contenu = fiche["content"]
        self.assertEqual([l["name"] for l in contenu["layers"]], ["Collision", "Entities"])
        self.assertEqual(contenu["layers"][0]["data"], LDTK_GRID)
        porte = next(o for o in contenu["layers"][1]["objects"] if o["type"] == "door")
        self.assertEqual(porte["properties"], [{"name": "color", "type": "ldtk", "value": "red"}])
        self.assertEqual(contenu["world"]["worldX"], 256)
        self.assertIn("layers", contenu["extensions"]["ldtk"]["defs"])
        self.assertEqual(self.lv("validate", fiche["id"])["status"], "pass")

    def test_AT07_conversion_avec_pertes_declarees_et_aller_retour(self):
        from tools.levels.formats import parse, to_tiled_json
        carte = tiled("S.#\n..G", properties=[{"name": "kind", "type": "string", "value": "dungeon"}])
        carte["layers"][0]["data"][2] = 0x80000001  # tuile retournée horizontalement
        carte["layers"].append({"id": 9, "name": "fond", "type": "imagelayer", "image": "ciel.png"})
        carte["editorsettings"] = {"export": {"target": "x"}}
        (niveau,) = parse("x.tmj", json.dumps(carte).encode())
        self.assertEqual(sorted(niveau["losses"]), ["champ Tiled editorsettings non conservé",
                                                    "couche fond de type imagelayer non normalisée (conservée dans "
                                                    "l'original)"])
        retour = to_tiled_json(niveau)
        for cle in ("width", "height", "tilewidth", "tileheight", "orientation", "properties"):
            self.assertEqual(retour[cle], carte[cle])
        self.assertEqual(retour["layers"][0]["data"], carte["layers"][0]["data"])
        self.assertEqual(retour["layers"][1]["objects"], carte["layers"][1]["objects"])
        (relu,) = parse("y.tmj", json.dumps(retour).encode())
        self.assertEqual(relu["layers"], niveau["layers"])
        self.assertEqual(relu["losses"], [])
        cree = self.importer("pertes", carte)
        self.assertEqual(len(self.lv("inspect", cree)["level"]["losses"]), 2)

    def test_AT08_licence_absente_publication_refusee(self):
        sans = self.importer("sans-licence", "S.G", license_=False)
        self.assertEqual(self.lv("inspect", sans)["level"]["origin"]["licenseStatus"], "unknown")
        refus = self.lv("publish", sans, "--version", "1.0.0", code=5)
        self.assertEqual((refus["status"], self.codes(refus)), ("blocked", {"license-unknown"}))
        self.assertFalse((self.root / "published" / "levels").exists())
        repo = self.depot("faux", {"levels/a.tmj": tiled("S.G"), "LICENSE.txt": "Free to use!"})
        faux = self.lv("import", "--source", "local", "--repo", str(repo), "--game", "faux", "--license", "CC0-1.0",
                       "--license-evidence", "LICENSE.txt")
        self.assertEqual(faux["licenseStatus"], "unknown")
        avec = self.importer("avec-licence", "S.G")
        self.assertEqual(self.lv("publish", avec, "--version", "1.0.0")["status"], "published")

    def test_AT09_archive_traversante_rejetee_en_quarantaine(self):
        archive = self.root / "cartes.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("../../evasion.tmj", json.dumps(tiled("S.G")))
            z.writestr("LICENSE.txt", CC0)
        refus = self.lv("import", "--source", "archive", "--archive", str(archive), "--license", "CC0-1.0", code=2)
        self.assertEqual(refus["status"], "blocked")
        self.assertIn("unsafe-archive", self.codes(refus))
        self.assertTrue((self.root / refus["quarantine"]).is_file())
        self.assertFalse((self.root / "catalog" / "levels").exists())
        saine = self.root / "saine.zip"
        with zipfile.ZipFile(saine, "w") as z:
            z.writestr("maps/a.tmj", json.dumps(tiled("S.G")))
            z.writestr("LICENSE.txt", CC0)
        ok = self.lv("import", "--source", "archive", "--archive", str(saine), "--license", "CC0-1.0",
                     "--source-url", "https://example.invalid/cartes", "--game", "tiers")
        self.assertEqual((len(ok["created"]), ok["licenseStatus"]), (1, "verified"))

    def test_AT10_asset_ext001_manquant_signale(self):
        tileset = [{"firstgid": 1, "name": "cuisine", "properties": [
            {"name": "assetId", "type": "string", "value": "asset-sprite-introuvable-0001"}]}]
        absent = self.importer("absent", tiled("S.G", tilesets=tileset))
        echec = self.lv("validate", absent, code=3)
        self.assertIn("asset-missing", self.codes(echec))
        present = self.importer("present", tiled("S.G", tilesets=[{"firstgid": 1, "name": "cuisine", "properties": [
            {"name": "assetId", "type": "string", "value": ASSET_ID}]}]))
        fiche = self.lv("inspect", present)["level"]
        self.assertEqual(fiche["dependencies"]["assets"], [{"id": ASSET_ID, "version": None}])
        self.assertEqual(self.lv("validate", present)["status"], "pass")
        self.assertFalse(any(p.suffix == ".png" for p in self.root.rglob("originals/**/*")))

    def test_AT11_donjon_cle_derriere_sa_porte(self):
        piege = self.importer("piege", "S...D.k\n#######\n......G", kind="dungeon")
        echec = self.lv("validate", piege, code=4)
        self.assertTrue({"key-behind-own-door", "dungeon-unsolvable"} <= self.codes(echec))
        bon = self.importer("bon", "S.k.D.G\n#######", kind="dungeon")
        rapport = self.lv("validate", bon)
        self.assertEqual(rapport["checks"]["dungeon"]["metrics"]["pathLength"], 6)

    def test_AT12_donjon_multi_interrupteurs(self):
        ok = self.importer("deux", "1.S.2\n##.##\n##g##\n##G##", kind="dungeon")
        rapport = self.lv("validate", ok)
        self.assertEqual(rapport["checks"]["dungeon"]["metrics"]["pathLength"], 11)
        coince = self.importer("coince", "1.S##\n##.#2\n##g##\n##G##", kind="dungeon")
        self.assertIn("dungeon-unsolvable", self.codes(self.lv("validate", coince, code=4)))

    def test_AT13_rpg_quete_inaccessible(self):
        quete = {"Q": ("quest", {"quest": "q1", "requires": "epee", "gives": "cle"}),
                 "E": ("item", {"gives": "epee"}), "X": ("barrier", {"requires": "cle"})}
        bloque = self.importer("bloque", tiled("S.Q.X.E\n#######", entities=quete), kind="rpg")
        echec = self.lv("validate", bloque, code=4)
        self.assertIn("quest-unreachable", self.codes(echec))
        jouable = self.importer("jouable", tiled("S.E.Q.X.B\n#########", entities=quete), kind="rpg")
        rapport = self.lv("validate", jouable)
        self.assertEqual(rapport["checks"]["rpg"]["metrics"]["questsDone"], ["2", "q1"])

    def test_AT14_apparition_dans_un_obstacle(self):
        carte = tiled("#.G")
        carte["layers"][-1]["objects"].append({"id": 50, "name": "spawn", "type": "spawn", "x": 0, "y": 0,
                                              "width": 16, "height": 16, "properties": []})
        niveau = self.importer("mur", carte, kind="dungeon")
        self.assertIn("spawn-in-obstacle", self.codes(self.lv("validate", niveau, code=4)))

    def test_AT15_saut_hors_de_portee(self):
        proche = self.importer("proche", plateforme(3), kind="platformer")
        self.assertEqual(self.lv("validate", proche)["status"], "pass")
        loin = self.importer("loin", plateforme(12), kind="platformer")
        echec = self.lv("validate", loin, code=4)
        self.assertIn("jump-out-of-range", self.codes(echec))
        profil = self.root / "profil.json"
        profil.write_text(json.dumps({"platformer": {"jumpVelocity": 4.0}}))
        self.assertIn("jump-out-of-range", self.codes(self.lv("validate", proche, "--profile", str(profil), code=4)))

    def test_AT16_plateforme_mobile_et_timing(self):
        navette = {"P": ("moving-platform", {"toX": 16, "period": 4})}
        avec = self.importer("navette", tiled(plateforme(12, (7, 16)), entities=navette), kind="platformer")
        rapport = self.lv("simulate", avec, "--agent", "platform-bot")
        self.assertEqual(rapport["status"], "pass")
        self.assertEqual(rapport["metrics"]["movingPlatformCells"], 10)
        courte = {"P": ("moving-platform", {"toX": 9, "period": 4})}
        sans = self.importer("courte", tiled(plateforme(12, (7, 9)), entities=courte), kind="platformer")
        self.assertIn("jump-out-of-range", self.codes(self.lv("simulate", sans, "--agent", "platform-bot", code=4)))
        self.assertEqual(self.lv("simulate", avec, "--agent", "kart-bot", code=2)["status"], "failed")

    def test_AT17_circuit_interrompu(self):
        rompu = self.importer("rompu", tiled(_circuit(ANNEAU_ROMPU), entities=CIRCUIT, track=True), kind="circuit")
        self.assertIn("circuit-interrupted", self.codes(self.lv("validate", rompu, code=4)))

    def test_AT18_points_de_controle_desordonnes(self):
        bon = self.importer("bon", tiled(_circuit(ANNEAU), entities=CIRCUIT, track=True), kind="circuit")
        rapport = self.lv("validate", bon)
        self.assertGreater(rapport["checks"]["circuit"]["metrics"]["lapCells"], 10)
        desordre = {**CIRCUIT, "b": ("checkpoint", {"order": 3}), "c": ("checkpoint", {"order": 2})}
        faux = self.importer("faux", tiled(_circuit(ANNEAU), entities=desordre, track=True), kind="circuit")
        self.assertIn("checkpoints-out-of-order", self.codes(self.lv("validate", faux, code=4)))
        etroit = self.root / "kart.json"
        etroit.write_text(json.dumps({"circuit": {"minWidth": 5, "kart": {"id": "kart-a", "version": "1.0.0"}}}))
        self.assertIn("checkpoint-off-track", self.codes(self.lv("validate", bon, "--profile", str(etroit), code=4)))

    def test_AT19_generation_stable_par_seed(self):
        contraintes = self.root / "demande.json"
        contraintes.write_text(json.dumps({"width": 40, "height": 30, "minRoom": 6, "depth": 3}))
        a = self.lv("generate", "--genre", "dungeon", "--constraints", str(contraintes), "--seed", "123")
        b = self.lv("generate", "--genre", "dungeon", "--constraints", str(contraintes), "--seed", "123")
        c = self.lv("generate", "--genre", "dungeon", "--constraints", str(contraintes), "--seed", "124")
        self.assertEqual((a["id"], a["contentSha256"]), (b["id"], b["contentSha256"]))
        self.assertEqual((a["status"], b["status"]), ("created", "unchanged"))
        self.assertNotEqual(a["contentSha256"], c["contentSha256"])
        self.assertEqual(a["generation"]["algorithm"], "bsp")
        self.assertIn("constraintsSha256", a["generation"])
        self.assertEqual(self.lv("validate", a["id"])["status"], "pass")
        with mock.patch("time.time", side_effect=AssertionError("horloge lue")):
            from tools.levels.generate import bsp_dungeon
            self.assertEqual(bsp_dungeon({"width": 40, "height": 30, "minRoom": 6, "depth": 3}, 123)[1]["rngState"],
                             a["generation"]["rngState"])

    def test_AT20_usage_multijeux_et_historique(self):
        niveau = self.importer("source", "S.G")
        lock = lambda v: {"levels": [{"id": niveau, "version": v, "sha256": "0" * 64, "transform": None}]}
        jeu_a = self.depot("jeu-a", {"level.lock.json": lock("1.0.0")})
        self.depot("jeu-a", {"level.lock.json": lock("1.1.0")})
        self.depot("jeu-b", {"game/level.lock.json": lock("1.0.0")})
        scope = self.scope([{"name": "jeu-a", "path": "depots/jeu-a"}, {"name": "jeu-b", "path": "depots/jeu-b"}])
        rapport = self.lv("usages", niveau, "--scope", scope)
        self.assertEqual(rapport["games"], ["jeu-a", "jeu-b"])
        self.assertEqual({(u["game"], u["version"]) for u in rapport["usages"]}, {("jeu-a", "1.1.0"),
                                                                                  ("jeu-b", "1.0.0")})
        self.assertEqual(sorted((h["game"], h["version"]) for h in rapport["history"]),
                         [("jeu-a", "1.0.0"), ("jeu-a", "1.1.0"), ("jeu-b", "1.0.0")])
        self.assertEqual(self.head(jeu_a), rapport["usages"][0]["commit"] if rapport["usages"][0]["game"] == "jeu-a"
                         else rapport["usages"][1]["commit"])


class EXT002Registre(NiveauxFixture, TestCase):
    def test_publication_lock_et_version_immuable(self):
        repo = self.depot("jeu", {"levels/a.tmj": tiled("S.G"), "LICENSE.txt": CC0})
        args = ["import", "--source", "local", "--repo", str(repo), "--game", "jeu", "--license", "CC0-1.0",
                "--license-evidence", "LICENSE.txt"]
        niveau = self.lv(*args)["created"][0]
        publie = self.lv("publish", niveau, "--version", "1.0.0")
        self.assertEqual(sorted(publie["lock"]), ["id", "sha256", "transform", "version"])
        self.assertTrue((self.root / publie["artifacts"][0]).is_file())
        self.assertEqual(self.lv("publish", niveau, "--version", "1.0.0")["status"], "unchanged")
        self.depot("jeu", {"levels/a.tmj": tiled("S..G")})
        self.lv(*args)
        conflit = self.lv("publish", niveau, "--version", "1.0.0", code=2)
        self.assertIn("version-immutable", self.codes(conflit))
        self.assertEqual(self.lv("publish", niveau, "--version", "1.1.0")["status"], "published")
        versions = self.lv("inspect", niveau)["level"]["versions"]
        self.assertEqual([v["version"] for v in versions], ["1.0.0", "1.1.0"])
        self.assertNotEqual(versions[0]["sha256"], versions[1]["sha256"])

    def test_derivation_miroir_liee_a_l_original(self):
        carte = tiled("S.#\n..G")
        niveau = self.importer("miroir", carte, kind="dungeon")
        demande = self.root / "miroir.json"
        demande.write_text(json.dumps({"transforms": ["mirror"]}))
        enfant = self.lv("derive", niveau, "--constraints", str(demande), "--seed", "1")
        fiche = self.lv("inspect", enfant["id"])["level"]
        self.assertEqual(fiche["derivedFrom"]["id"], niveau)
        self.assertEqual(fiche["transformations"], [{"transforms": ["mirror"], "seed": 1}])
        self.assertEqual(fiche["content"]["layers"][0]["data"][:3], [0x80000001, 0, 0])
        self.assertEqual(self.lv("validate", enfant["id"])["status"], "pass")

    def test_budget_depasse_inconclusive_jamais_pass(self):
        niveau = self.importer("grand", "S" + "." * 30 + "\n" + "." * 30 + "G", kind="dungeon")
        profil = self.root / "budget.json"
        profil.write_text(json.dumps({"budget": 5}))
        rapport = self.lv("validate", niveau, "--profile", str(profil), code=6)
        self.assertEqual(rapport["status"], "inconclusive")

    def test_recherche_fts5_et_filtre_par_genre(self):
        self.importer("temple", tiled("S.k.D.G", properties=[{"name": "kind", "type": "string", "value": "dungeon"}]))
        self.importer("plaine", "S...G", kind="rpg")
        self.assertEqual([r["id"] for r in self.lv("search", "--query", "keys")["results"]],
                         ["level-temple-niveau"])
        self.assertEqual([r["id"] for r in self.lv("search", "--query", "", "--type", "rpg")["results"]],
                         ["level-plaine-niveau"])

    def test_doublons_de_structure_proposes_jamais_fusionnes(self):
        carte = tiled("S.G")
        self.depot("doubles", {"levels/a.tmj": carte, "levels/b.tmj": carte})
        rapport = self.lv("discover", "--scope", self.scope([{"name": "d", "path": "depots/doubles"}]))
        self.assertEqual(rapport["repos"][0]["duplicates"], [{"files": ["levels/a.tmj", "levels/b.tmj"],
                                                              "kind": "structure-identique", "merged": False}])

    def test_transition_bidirectionnelle_exigee(self):
        aller = tiled("S.G", entities={"G": ("transition", {"target": "level-b-niveau", "bidirectional": True})})
        a = self.importer("a", aller, kind="rpg")
        self.assertIn("transition-one-way", self.codes(self.lv("validate", a, code=4)))
        self.importer("b", tiled("S.G", entities={"G": ("transition", {"target": a})}), kind="rpg")
        self.assertEqual(self.lv("validate", a)["status"], "pass")

    def test_schema_level_de_la_spec(self):
        from tools.core.schemas import schemas
        niveau = self.importer("schema", "S.G")
        fiche = self.lv("inspect", niveau)["level"]
        valide = schemas().validator("level")
        self.assertTrue(valide.is_valid(fiche))
        for champ in ("origin", "geometry", "dependencies", "validation", "usage"):
            faux = {k: v for k, v in fiche.items() if k != champ}
            self.assertFalse(valide.is_valid(faux))

    def test_codes_de_retour_de_la_spec(self):
        """06_CLI_AGENTS : 0 succès, 2 entrée invalide, 3 référence absente, 4 validation échouée,
        5 droits/licence bloquants, 6 simulation indéterminée, 7 erreur d'infrastructure."""
        bon = self.importer("codes-ok", "S.G", kind="dungeon")
        self.lv("validate", bon, code=0)
        self.lv("publish", bon, "--version", "pas-semver", code=2)
        self.lv("inspect", "level-qui-n-existe-pas", code=3)
        piege = self.importer("codes-piege", "S#G", kind="dungeon")
        self.lv("validate", piege, code=4)
        profil = self.root / "codes-budget.json"
        profil.write_text(json.dumps({"budget": 1}))
        grand = self.importer("codes-grand", "S" + "." * 20 + "G", kind="dungeon")
        self.lv("validate", grand, "--profile", str(profil), code=6)
        with mock.patch("tools.levels.commands.Source.files",
                        side_effect=subprocess.CalledProcessError(128, "git")):
            portee = self.root / "codes-scope.json"
            portee.write_text(json.dumps({"repos": [{"name": "x", "path": "."}]}))
            self.lv("usages", bon, "--scope", str(portee), code=7)

    def test_module_desactive_et_registre_intact(self):
        with mock.patch.dict(os.environ, {"ASSETCTL_LEVELS": "off"}):
            self.assertEqual(self.cli("level", "search")[0], 7)
            self.assertEqual(self.cli("validate")[0], 0)


class EXT002Documentation(TestCase):
    def test_regles_agents_ext002(self):
        texte = " ".join((Path(__file__).resolve().parents[2] / "docs" / "AGENTS.md").read_text().split())
        for attendu in ("Rechercher les niveaux internes avant les bibliothèques externes, puis adapter avant de générer",
                        "Réutiliser des bibliothèques de génération existantes", "Ne jamais inventer licence",
                        "Ne pas modifier les dépôts sources pendant le bootstrap",
                        "Ne pas publier de niveau dont les assets ou les dépendances ont des droits inconnus",
                        "seed, contraintes, versions, rapport de validation", "pas de clics manuels",
                        "3 tentatives", "validation structurelle et qualité ludique",
                        "manifestes d'usage des jeux à chaque adoption"):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, texte)


def plateforme(trou, mobile=None):
    """Sol, fosse de `trou` cases, sol ; `mobile` = (colonne de départ, colonne d'arrivée) d'une plateforme mobile
    posée au niveau du sol dans la fosse."""
    largeur = 12 + trou
    sol = list("######" + "." * trou + "######")
    if mobile:
        sol[mobile[0]] = "P"
    return "\n".join(["." * largeur, "." * largeur, "S" + "." * (largeur - 2) + "G", "".join(sol)])


ANNEAU_ROMPU = ANNEAU.replace("#TTTTTTTTT#\n#TTTTTTTTT#\n###########", "#TTTTTT.TT#\n#TTTTTT.TT#\n###########")
CIRCUIT = {"s": ("start", {}), "a": ("checkpoint", {"order": 1}), "b": ("checkpoint", {"order": 2}),
           "c": ("checkpoint", {"order": 3})}


def _circuit(anneau):
    lignes = [list(l) for l in anneau.strip("\n").split("\n")]
    for y, x, c in ((1, 5, "s"), (2, 5, "s"), (3, 8, "a"), (3, 9, "a"), (5, 5, "b"), (6, 5, "b"), (4, 1, "c"),
                    (4, 2, "c")):
        lignes[y][x] = c
    return "\n".join("".join(l) for l in lignes)


TSX = """<?xml version="1.0" encoding="UTF-8"?>
<tileset version="1.10" name="foret" tilewidth="16" tileheight="16" tilecount="4" columns="2">
 <properties><property name="assetId" value="%s"/></properties>
 <image source="foret.png" width="32" height="32"/>
</tileset>
""" % ASSET_ID

TMX = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" orientation="orthogonal" renderorder="right-down" width="3" height="2" tilewidth="16"
     tileheight="16" infinite="0">
 <editorsettings><export target="foret.tmj"/></editorsettings>
 <tileset firstgid="1" source="tiles/foret.tsx"/>
 <layer id="1" name="sol" width="3" height="2"><data encoding="csv">1,2147483649,0,
0,0,0</data></layer>
 <layer id="2" name="collision" width="3" height="2"><data encoding="csv">0,0,0,0,0,1</data></layer>
 <objectgroup id="3" name="entites">
  <object id="1" name="depart" type="spawn" x="0" y="16" width="16" height="16"/>
  <object id="2" name="sortie" type="goal" x="32" y="0" width="16" height="16">
   <properties><property name="required" type="bool" value="true"/></properties>
  </object>
 </objectgroup>
</map>
"""

LDTK_GRID = [0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0]
LDTK = json.dumps({
    "jsonVersion": "1.5.3", "defaultGridSize": 16, "worldLayout": "Free",
    "defs": {"layers": [{"identifier": "Collision", "type": "IntGrid"}, {"identifier": "Entities", "type": "Entities"}],
             "entities": [{"identifier": "Player"}, {"identifier": "Door"}, {"identifier": "Key"},
                          {"identifier": "Goal"}], "tilesets": []},
    "levels": [{"identifier": "Crypte", "iid": "l1", "pxWid": 64, "pxHei": 48, "worldX": 256, "worldY": 0,
                "fieldInstances": [], "__neighbours": [],
                "layerInstances": [
                    {"__identifier": "Entities", "__type": "Entities", "__gridSize": 16, "__cWid": 4, "__cHei": 3,
                     "__pxTotalOffsetX": 0, "__pxTotalOffsetY": 0, "visible": True,
                     "entityInstances": [
                         {"__identifier": "Player", "iid": "e1", "px": [0, 0], "width": 16, "height": 16,
                          "fieldInstances": []},
                         {"__identifier": "Key", "iid": "e2", "px": [48, 0], "width": 16, "height": 16,
                          "fieldInstances": [{"__identifier": "color", "__value": "red", "__type": "String"}]},
                         {"__identifier": "Door", "iid": "e3", "px": [48, 16], "width": 16, "height": 16,
                          "fieldInstances": [{"__identifier": "color", "__value": "red", "__type": "String"}]},
                         {"__identifier": "Goal", "iid": "e4", "px": [48, 32], "width": 16, "height": 16,
                          "fieldInstances": []}]},
                    {"__identifier": "Collision", "__type": "IntGrid", "__gridSize": 16, "__cWid": 4, "__cHei": 3,
                     "__pxTotalOffsetX": 0, "__pxTotalOffsetY": 0, "visible": True, "intGridCsv": LDTK_GRID,
                     "autoLayerTiles": []}]}]})
