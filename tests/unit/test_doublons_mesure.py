"""Paires « similaires » statuées par une mesure de pixels (HL-538, P0-08 : jamais de fusion automatique)."""
import tempfile
from pathlib import Path
from unittest import TestCase

from PIL import Image, ImageDraw

from tools.index.dedup import PIXEL_NOISE, duplicates, fingerprints, rule


def dessin(decalage=0):
    image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((10 + decalage, 12, 72 + decalage, 90), fill=(200, 60, 30, 255))
    draw.rectangle((40, 70 - decalage, 95, 82 - decalage), fill=(95, 95, 95, 255))
    return image


class DoublonsParMesure(TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.root = Path(dossier.name)

    def asset(self, nom, image):
        image.save(self.root / f"{nom}.png")
        return {"id": nom, "family": {"type": "image"}, "sha256": nom, "variants": [],
                "files": {"locations": [], "registry": f"{nom}.png"},
                "dimensions": {"width": image.width, "height": image.height}, "perceptual": fingerprints(image)}

    def test_meme_dessin_reechantillonne_reste_a_decider_dessin_different_distinct(self):
        base = self.asset("a", dessin())
        meme = self.asset("b", dessin().resize((92, 92), Image.Resampling.LANCZOS))
        autre = self.asset("c", dessin(18))
        par_id = {x["id"]: x for x in (base, meme, autre)}
        proche = rule({"a": "a", "b": "b", "status": "needs-review"}, par_id, self.root, {})
        loin = rule({"a": "a", "b": "c", "status": "needs-review"}, par_id, self.root, {})
        self.assertLessEqual(proche["pixelDistance"], PIXEL_NOISE)
        self.assertEqual(proche["status"], "needs-review")
        self.assertGreater(loin["pixelDistance"], PIXEL_NOISE)
        self.assertEqual(loin["status"], "distinct")

    def test_rapport_statue_et_ne_fusionne_rien(self):
        assets = [self.asset("a", dessin()), self.asset("b", dessin().resize((92, 92), Image.Resampling.LANCZOS))]
        rapport = duplicates(assets, self.root)
        self.assertEqual([(p["a"], p["b"], p["status"]) for p in rapport["similar"]], [("a", "b", "needs-review")])
        self.assertTrue(all(a["variants"] == [] for a in assets))
        sans_binaire = duplicates(assets)
        self.assertNotIn("pixelDistance", sans_binaire["similar"][0])
