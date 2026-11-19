"""Contrôles de découverte avec des fichiers et dépôts jetables."""

import base64
import io
import json
import struct
import subprocess
import unittest

from PIL import Image, ImageDraw

from tests.acceptance import _contrat as C
from tests.acceptance._monde import NIVEAU, TRONQUE, _ecrire, aseprite, creer_monde, wav


def picture(format, mode="RGB"):
    image = Image.new(mode, (20, 12), (30, 50, 60, 120) if mode == "RGBA" else (30, 50, 60))
    stream = io.BytesIO()
    image.save(stream, format, **({"save_all": True, "append_images": [Image.new(mode, image.size)], "duration": 100}
                                  if format == "GIF" else {}))
    return stream.getvalue()


class Discovery(unittest.TestCase):
    def setUp(self):
        self.world = creer_monde()
        self.addCleanup(self.world.nettoyer)
        self.root = self.world.registre

    def scan(self, *args, code=0):
        result = self.world.scan(*args)
        self.assertEqual(result.code, code, str(result))
        return result.json

    def test_T09_hors_liste(self):
        self.scan("--only", str(self.world.depot("intrus")), code=3)
        self.assertFalse(self.world.cache.exists())
        sources = C.lire_json(self.root / C.SOURCES)
        sources["sources"][0]["copies"][0]["path"] = str(self.world.depot("intrus"))
        selection = self.root / "selection.json"
        selection.write_text(json.dumps(sources))
        self.scan("--sources", str(selection), code=3)
        self.assertFalse(self.world.cache.exists())

    def test_T10_formats(self):
        from tools.discovery.formats import inspect
        face = "Fixture".encode("utf-16-be")
        names = struct.pack(">HHH6H", 0, 1, 18, 3, 1, 1033, 1, len(face), 0) + face
        font = b"\x00\x01\x00\x00" + struct.pack(">4H4s3I", 1, 0, 0, 0, b"name", 0, 28, len(names)) + names
        frame = {"frame": {"x": 0, "y": 0, "w": 4, "h": 5}}
        formats = {
            "opaque.png": (picture("PNG"), "image"),
            "alpha.png": (picture("PNG", "RGBA"), "image"),
            "image.jpeg": (picture("JPEG"), "image"),
            "image.webp": (picture("WEBP"), "image"),
            "animated.gif": (picture("GIF"), "animation"),
            "icon.svg": (b'<svg width="20" height="12" viewBox="0 0 20 12"/>', "svg"),
            "sprite.ase": (aseprite(), "animation"),
            "hash.json": (json.dumps({"frames": {"one": frame}, "meta": {"image": "a.png"}}).encode(), "atlas"),
            "array.json": (json.dumps({"frames": [{"filename": "one", **frame}], "meta": {"image": "a.png"}}).encode(), "atlas"),
            "map.tmj": (b'{"tiledversion":"1.10","tilewidth":16,"tileheight":16,"layers":[]}', "tilemap"),
            "map.tmx": (b'<map tilewidth="16" tileheight="16"><layer/></map>', "tilemap"),
            "tiles.tsj": (b'{"tilewidth":16,"tileheight":16,"tilecount":3}', "tileset"),
            "tiles.tsx": (b'<tileset tilewidth="16" tileheight="16" tilecount="3"/>', "tileset"),
            "sound.wav": (wav(), "audio"),
            "sound.ogg": (b'OggS\x00\x02' + bytes(50), "audio"),
            "font.ttf": (font, "font"),
            "water.glsl": (b'void main() {}', "shader"),
            "draw.ts": (b"g.generateTexture('k', 8, 8); g.generateTexture('other');", "code-generated"),
        }
        for path, (data, family) in formats.items():
            with self.subTest(path=path):
                self.assertEqual(inspect(path, data).family["type"], family)
        self.assertIs(inspect("opaque.png", formats["opaque.png"][0]).alpha, False)
        self.assertIs(inspect("alpha.png", formats["alpha.png"][0]).alpha, True)
        self.assertEqual(inspect("sound.wav", wav()).family["audio"]["durationSec"], 0.5)
        self.assertEqual(inspect("font.ttf", font).family["font"]["family"], "Fixture")
        self.assertEqual(inspect("draw.ts", formats["draw.ts"][0]).symbols, ("k", "other"))

    def test_T11_exception(self):
        self.scan()
        self.assertTrue(C.contient_valeur(C.lire_json(C.rapport(self.root, "exceptions")), TRONQUE))
        self.assertTrue(C.asset_par_chemin(self.root, "jeu-a", NIVEAU))

    def test_T13_exact(self):
        repo = self.world.depot("jeu-a")
        _ecrire(repo, {"equal-a.png": picture("PNG"), "equal-b.png": picture("PNG")})
        self.world.git(repo, "add", "--", "equal-a.png", "equal-b.png")
        self.world.git(repo, "commit", "-qm", "equal")
        self.scan()
        asset_id, asset = C.asset_par_chemin(self.root, "jeu-a", "equal-a.png")
        self.assertEqual(asset_id, C.asset_par_chemin(self.root, "jeu-a", "equal-b.png")[0])
        self.assertEqual(len(asset["files"]["locations"]), 2)

    def test_T14_similaire(self):
        from tools.index.dedup import duplicates, fingerprints
        image = Image.new("RGB", (100, 100), (55, 55, 55))
        draw = ImageDraw.Draw(image)
        draw.ellipse((10, 12, 72, 90), fill=(200, 200, 200))
        draw.rectangle((40, 70, 95, 82), fill=(95, 95, 95))
        near = image.point(lambda n: n + 1).crop((1, 0, 100, 100))
        different = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        assets = [{"id": str(i), "family": {"type": "image"}, "sha256": str(i), "variants": [], "files": {"locations": []},
                   "dimensions": {"width": im.width, "height": im.height}, "perceptual": fingerprints(im)}
                  for i, im in enumerate((image, near, different))]
        pairs = duplicates(assets)["similar"]
        self.assertEqual([(p["a"], p["b"]) for p in pairs], [("0", "1")])
        self.assertTrue(all(a["variants"] == [] for a in assets))

    def test_T15_idempotent(self):
        self.scan()
        before = C.empreinte_arbre(self.root / "catalog", avec_dates=False)
        result = self.scan()
        self.assertEqual(result["newAssets"], 0)
        self.assertEqual(result["newIds"], 0)
        self.assertEqual(before, C.empreinte_arbre(self.root / "catalog", avec_dates=False))

    def test_lecture_seule(self):
        repo = self.world.depot("jeu-a")
        before = C.empreinte_arbre(repo)
        self.scan()
        self.scan("--verify")
        self.assertEqual(before, C.empreinte_arbre(repo))

    def test_jeton(self):
        token = "faux-jeton-confidentiel-L2a"
        env = C.environnement(self.world.home)
        env.update(ASSETCTL_GITHUB_TOKEN=token, ASSETCTL_FORGEJO_TOKEN=token)
        command = [str(self.root / "assetctl"), *C.cmd_scan(self.world.cache), "--log", "scan.log"]
        result = subprocess.run(command, cwd=self.root, env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for secret in (token.encode(), base64.b64encode(f"x-access-token:{token}".encode())):
            self.assertNotIn(secret, result.stdout + result.stderr)
            for directory in ("catalog", "generated", "thumbnails"):
                for path in (self.root / directory).rglob("*"):
                    if path.is_file():
                        self.assertNotIn(secret, path.read_bytes())
            self.assertNotIn(secret, (self.root / "scan.log").read_bytes())

    def test_verify_oubli(self):
        self.scan()
        asset_id, _ = C.asset_par_chemin(self.root, "jeu-a", NIVEAU)
        (self.root / C.DOSSIER_ASSETS / f"{asset_id}.json").unlink()
        report = self.scan("--verify", code=1)
        self.assertTrue(C.contient_valeur(report["forgotten"], NIVEAU))

    def test_date_retrait_et_derive(self):
        from datetime import datetime

        repo = self.world.depot("jeu-a")
        created = self.world.git(repo, "show", "-s", "--format=%cI", "HEAD")
        self.world.git(repo, "commit", "--allow-empty", "-qm", "new reference",
                       date="2026-02-04T00:00:00+00:00")
        reference = self.world.git(repo, "rev-parse", "HEAD")
        updated = self.world.git(repo, "show", "-s", "--format=%cI", "HEAD")
        self.scan()
        asset_id, asset = C.asset_par_chemin(self.root, "jeu-a", NIVEAU)
        self.assertEqual(datetime.fromisoformat(asset["createdAt"]), datetime.fromisoformat(created))
        self.assertEqual(asset["updatedAt"], updated)
        self.world.git(repo, "rm", "--", NIVEAU)
        self.world.git(repo, "commit", "-qm", "remove image", date="2026-03-01T00:00:00+00:00")
        removed = self.world.git(repo, "rev-parse", "HEAD")

        report = self.scan("--verify", "--dry-run", code=1)
        self.assertIn({"name": "jeu-a", "provider": "local", "catalogCommit": reference,
                       "remoteCommit": removed}, report["drift"])
        self.assertFalse((self.root / C.RAPPORT_VERIFY).exists())
        self.scan("--verify", "--no-fetch")
        self.scan()
        asset = C.assets(self.root)[asset_id]
        self.assertEqual(asset["updatedAt"], updated)
        self.assertTrue(any(loc["path"] == NIVEAU and loc["status"] == "removed" and
                            loc["removedAtCommit"] == removed for loc in asset["files"]["locations"]))
        self.scan("--verify")
        self.assertEqual(self.scan()["newAssets"], 0)

    def test_tags_classification_exclusions_et_job(self):
        from tools.core.schemas import schemas

        repo = self.world.depot("jeu-a")
        self.world.git(repo, "tag", "-a", "v1", "-m", "release")
        paths = {"src/games/minijeu/hero.png": picture("PNG"),
                 "src/games/minijeu/generated/image.png": picture("PNG", "RGBA"),
                 "public/legacy.psd": b"8BPS"}
        _ecrire(repo, paths)
        self.world.git(repo, "add", "--", *paths)
        self.world.git(repo, "commit", "-qm", "add files", date="2026-02-04T00:00:00+00:00")
        result = self.scan("--provider", "local", "--only", "jeu-a")
        job = C.lire_json(self.root / C.DOSSIER_JOBS / f"{result['jobId']}.json")
        self.assertTrue(schemas().validator("import-job").is_valid(job))
        self.assertEqual({entry["commit"] for entry in job["inputs"]},
                         {self.world.commits["jeu-a"], self.world.git(repo, "rev-parse", "HEAD")})
        self.assertTrue(C.contient_valeur(C.lire_json(C.rapport(self.root, "migration")), "v1"))
        for (path, classification) in zip(paths, ("game", "generated")):
            _, asset = C.asset_par_chemin(self.root, "jeu-a", path)
            loc = next(loc for loc in asset["files"]["locations"] if loc["path"] == path)
            self.assertEqual(loc["classification"], classification)
            self.assertEqual(loc["game"], "jeu-a/minijeu")
        for report in ("coverage", "scan-limits"):
            self.assertTrue(C.contient_valeur(C.lire_json(C.rapport(self.root, report)), "public/legacy.psd"))
        self.scan("--verify", "--only", "jeu-a")

    def test_cache_et_journal_necrivent_pas_dans_la_source(self):
        repo = self.world.depot("jeu-a")
        before = C.empreinte_arbre(repo)
        self.scan("--cache", str(repo / "mirrors"), code=3)
        self.scan("--log", str(repo / "scan.log"), code=3)
        self.assertEqual(before, C.empreinte_arbre(repo))

    def test_auth_headers_et_config_git_existante(self):
        from tools.discovery.repos import git_environment

        env = git_environment({"ASSETCTL_GITHUB_TOKEN": "example-github", "ASSETCTL_FORGEJO_TOKEN": "example-forge"})
        self.assertEqual(env["GIT_CONFIG_COUNT"], "2")
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "http.https://github.com/.extraheader")
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], "Authorization: Basic " +
                         base64.b64encode(b"x-access-token:example-github").decode())
        self.assertEqual(env["GIT_CONFIG_KEY_1"], "http.https://forgejo.pingfr.duckdns.org/.extraheader")
        self.assertEqual(env["GIT_CONFIG_VALUE_1"], "Authorization: token example-forge")
        existing = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraheader",
                    "GIT_CONFIG_VALUE_0": "existing"}
        env = git_environment({**existing, "ASSETCTL_GITHUB_TOKEN": "unused"})
        self.assertEqual({key: env[key] for key in existing}, existing)
        self.assertNotIn("GIT_CONFIG_KEY_1", env)

    def test_cache_d_un_autre_depot_est_refuse(self):
        self.scan("--only", "jeu-a")
        mirror = self.world.cache / "local" / "jeu-a.git"
        self.world.git(mirror, "config", "remote.origin.url", self.world.depot("intrus").as_uri())
        before = C.empreinte_arbre(self.root / "catalog")
        self.scan("--only", "jeu-a", code=3)
        self.assertEqual(before, C.empreinte_arbre(self.root / "catalog"))
