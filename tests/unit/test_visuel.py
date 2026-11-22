"""REG-07 / E110 / EXT-12 : index visuel dérivé, recherche par l'image expliquée, jamais de GPU sur Zalman.
Back-end `couleurs` (déterministe, hors ligne) ; le back-end CLIP réel est mesuré sur tank01 et en CI CPU (GitHub)."""
import json
from pathlib import Path
from unittest import TestCase

from tests.unit.test_ext001 import CC0, ExterneFixture, png


class Visuel(ExterneFixture, TestCase):
    def vignette(self, asset_id, couleur):
        fiche = self.root / "catalog" / "assets" / f"{asset_id}.json"
        a = json.loads(fiche.read_text())
        chemin = self.root / "thumbnails" / f"{a['sha256']}.png"
        chemin.parent.mkdir(exist_ok=True)
        chemin.write_bytes(png(couleur))
        a["thumbnail"] = chemin.relative_to(self.root).as_posix()
        fiche.write_text(json.dumps(a))
        return chemin

    def importer(self, pack_id, couleur):
        self.pack(pack_id, {f"{pack_id}.png": png(couleur), "License.txt": CC0})
        self.ext("import", "--plan", str(self.plan(pack_id)[0]))
        ident = next(i for i, a in self.externals().items() if a["provenance"]["external"]["externalPackId"] == pack_id)
        return ident, self.vignette(ident, couleur)

    def test_index_derive_et_resultats_expliques(self):
        rouge, chemin_rouge = self.importer("rouge", (220, 10, 10, 255))
        bleu, _ = self.importer("bleu", (10, 10, 220, 255))
        code, res = self.cli("visual", "embed", "--backend", "couleurs", "--device", "cpu", "--out", "couleurs")
        self.assertEqual((code, res["count"]), (0, 2), res)
        code, res = self.cli("visual", "search", "--backend", "couleurs", "--device", "cpu", "--image",
                             str(chemin_rouge), "--limit", "2")
        self.assertEqual(code, 0, res)
        premier, second = res["results"]
        self.assertEqual(premier["ids"], [rouge])
        self.assertTrue(premier["verdict"].startswith("identique"))
        self.assertIn("clipCosine", premier["explication"])
        self.assertIn("phashDistance", premier["explication"])
        self.assertEqual(second["ids"], [bleu])
        self.assertGreater(premier["score"], second["score"])

    def test_jamais_de_gpu_sur_zalman(self):
        from tools.index.visual import Refus, appareil
        for gpu in ("xpu", "cuda"):
            with self.assertRaises(Refus):
                appareil(gpu, hote="zalman")
        self.assertEqual(appareil("auto", hote="zalman"), "cpu")
        self.assertEqual(appareil("cpu", hote="zalman"), "cpu")
        self.assertEqual(appareil("xpu", hote="tank01"), "xpu")
