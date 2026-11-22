"""REG-08 (E108, HL-538) : les pages du catalogue sont refaites depuis le catalogue ; --check rend 2 dès qu'une page
n'est plus à jour (fiche modifiée, page retouchée à la main, page en trop), 0 après régénération."""
import importlib.util
import json
import tempfile
from pathlib import Path
from unittest import TestCase

_spec = importlib.util.spec_from_file_location("catalogue_pages",
                                               Path(__file__).resolve().parents[2] / "scripts/catalogue_pages.py")
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)


def monde(r: Path):
    (r / "catalog/assets").mkdir(parents=True)
    (r / "catalog/sheets").mkdir(parents=True)
    (r / "generated").mkdir()
    (r / "catalog/sources.json").write_text(json.dumps({"sources": [{"name": "jeu", "role": "game", "copies": []}]}))
    (r / "catalog/sheets/sheet-p-0001.json").write_text(json.dumps(
        {"id": "sheet-p-0001", "name": "p", "license": "MIT", "sha256": "0" * 64, "files": {"locations": []}}))
    (r / "catalog/assets/asset-image-a-0001.json").write_text(json.dumps(
        {"id": "asset-image-a-0001", "name": "a", "category": "image", "license": "MIT", "thumbnail": "thumbnails/aa/a.webp",
         "sourceSheetId": "sheet-p-0001", "provenance": {"author": "David"}}))
    (r / "thumbnails/aa").mkdir(parents=True)
    (r / "thumbnails/aa/a.webp").write_bytes(b"RIFF")
    (r / "generated/usage-index.json").write_text(json.dumps({"byAsset": {"asset-image-a-0001": [
        {"game": "jeu/sous", "commit": "c" * 40, "status": "active"}]}}))


class PagesDuCatalogue(TestCase):
    def test_rouge_puis_vert(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            monde(r)
            self.assertEqual(cp.main(["--racine", d, "--check"]), 2)          # absentes
            self.assertEqual(cp.main(["--racine", d]), 0)
            self.assertEqual(cp.main(["--racine", d, "--check"]), 0)
            pages = {p.relative_to(r / cp.SORTIE).as_posix() for p in (r / cp.SORTIE).rglob("*.md")}
            self.assertEqual(pages, {"index.md", "jeux/jeu--sous.md", "sources/jeu.md", "planches/sheet-p-0001.md",
                                     "licences/MIT.md"})
            jeu = (r / cp.SORTIE / "jeux/jeu--sous.md").read_text()
            self.assertIn("](../index.md)", jeu)
            self.assertIn("![](../../../thumbnails/aa/a.webp)", jeu)
            self.assertIn("](../licences/MIT.md)", jeu)
            self.assertIn("](../planches/sheet-p-0001.md)", jeu)
            self.assertIn("](../../../catalog/assets/asset-image-a-0001.json)", jeu)
            # fiche modifiée : la page du jeu n'est plus à jour → rouge, puis vert après régénération
            f = r / "catalog/assets/asset-image-a-0001.json"
            f.write_text(f.read_text().replace('"MIT"', '"CC0-1.0"'))
            self.assertEqual(cp.main(["--racine", d, "--check"]), 2)
            self.assertEqual(cp.main(["--racine", d]), 0)
            self.assertEqual(cp.main(["--racine", d, "--check"]), 0)
            self.assertFalse((r / cp.SORTIE / "licences/MIT.md").exists())   # page orpheline retirée
            # page retouchée à la main, puis page en trop
            p = r / cp.SORTIE / "index.md"
            p.write_text(p.read_text() + "retouche\n")
            self.assertEqual(cp.main(["--racine", d, "--check"]), 2)
            cp.main(["--racine", d])
            (r / cp.SORTIE / "jeux/fantome.md").write_text(cp.MARQUE + "\n")
            self.assertEqual(cp.main(["--racine", d, "--check"]), 2)
            cp.main(["--racine", d])
            self.assertEqual(cp.main(["--racine", d, "--check"]), 0)

    def test_deux_generations_identiques(self):
        with tempfile.TemporaryDirectory() as d:
            monde(Path(d))
            self.assertEqual(cp.construire(Path(d)), cp.construire(Path(d)))


class VignettesCitees(TestCase):
    """Vignette citée par une fiche mais absente : --check rouge ; la génération la produit depuis le fichier du
    registre (octets de l'asset), puis --check vert et la page l'affiche."""
    def test_vignette_produite(self):
        import hashlib
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            monde(r)
            (r / "sprites").mkdir()
            Image.new("RGBA", (200, 100), (255, 0, 0, 255)).save(r / "sprites/b.png")
            sha = hashlib.sha256((r / "sprites/b.png").read_bytes()).hexdigest()
            (r / "catalog/assets/asset-sprite-b-0001.json").write_text(json.dumps(
                {"id": "asset-sprite-b-0001", "name": "b", "category": "sprite", "license": "MIT", "sha256": sha,
                 "thumbnail": f"thumbnails/{sha[:2]}/{sha}.webp", "files": {"registry": "sprites/b.png"}}))
            u = json.loads((r / "generated/usage-index.json").read_text())
            u["byAsset"]["asset-sprite-b-0001"] = [{"game": "jeu", "commit": "d" * 40, "status": "active"}]
            (r / "generated/usage-index.json").write_text(json.dumps(u))
            self.assertEqual(cp.main(["--racine", d]), 0)
            v = r / f"thumbnails/{sha[:2]}/{sha}.webp"
            self.assertTrue(v.is_file())
            with Image.open(v) as im:
                self.assertEqual(im.size, (96, 48))
            self.assertIn(f"![](../../../thumbnails/{sha[:2]}/{sha}.webp)", (r / cp.SORTIE / "jeux/jeu.md").read_text())
            self.assertEqual(cp.main(["--racine", d, "--check"]), 0)
            v.unlink()
            self.assertEqual(cp.main(["--racine", d, "--check"]), 2)
