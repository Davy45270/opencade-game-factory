"""E026 / E106 / E258 : la CI GitHub tourne sur la COPIE PUBLIQUE (Davy45270/opencade-game-factory), d'où la synchro
retire les fichiers des fiches sans licence libre (HL-538 7-3316). scripts/copie_publique.py rend validate et
build-index exacts sur cette copie sans rien relâcher ailleurs : fichier libre absent et fuite restent bloquants."""
import copy
import hashlib
import importlib.util
import io
import unittest

from tests.unit.test_oracles import ASSET, ROOT, CatalogueFixture


def _module(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, ROOT / "scripts" / fichier)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


cp = _module("copie_publique", "copie_publique.py")
visuel = _module("visuel_controle", "visuel-controle.py")


def _png(couleur):
    from PIL import Image
    image = Image.new("RGBA", (16, 16), couleur)
    image.putpixel((0, 0), (0, 0, 0, 0))  # alpha réel : la fiche dit alpha=True
    flux = io.BytesIO()
    image.save(flux, "PNG")
    return flux.getvalue()


class CopiePublique(CatalogueFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        (self.root / "catalog" / "assets" / f"{ASSET['id']}.json").unlink()
        (self.root / "sprites").mkdir()
        self.fiches = {}
        ids = {}
        for nom, licence, couleur in (("prive", "unknown", (200, 30, 30, 255)), ("prive2", "unknown", (30, 200, 30, 255)),
                                      ("libre", "CC0-1.0", (30, 30, 200, 255))):
            octets = _png(couleur)
            (self.root / "sprites" / f"{nom}.png").write_bytes(octets)
            fiche = copy.deepcopy(ASSET)
            fiche.update(id=f"asset-kitchen-{nom}-0001", license=licence, sha256=hashlib.sha256(octets).hexdigest(),
                         files={"locations": [], "registry": f"sprites/{nom}.png"})
            if licence != "unknown":
                fiche["licenseEvidence"] = ["LICENSE de fixture"]
            self.write(f"assets/{fiche['id']}.json", fiche)
            ids[f"file:sha256:{fiche['sha256']}"] = fiche["id"]
            self.fiches[nom] = fiche
        self.write("ids.json", ids)

    def retirer(self, *noms):
        for nom in noms:
            (self.root / "sprites" / f"{nom}.png").unlink()

    def test_arbre_complet_identique_a_validate(self):
        self.assertEqual(self.cli("validate")[0], 0)
        ok, rapport = cp.controle_validate(self.root)
        self.assertTrue(ok, rapport)
        self.assertEqual((rapport["toleres"], rapport["nFuites"]), (0, 0))

    def test_copie_publique_rouge_avec_validate_seul_verte_avec_le_controle(self):
        self.retirer("prive", "prive2")
        code, payload = self.cli("validate")
        self.assertEqual(code, 1)  # ce que faisait la CI GitHub depuis le 22/11
        self.assertEqual({i["code"] for i in payload["issues"]}, {"missing-registry-file"})
        ok, rapport = cp.controle_validate(self.root)
        self.assertTrue(ok, rapport)
        self.assertEqual(rapport["toleres"], 2)

    def test_fichier_libre_absent_reste_bloquant(self):
        self.retirer("prive", "prive2", "libre")
        ok, rapport = cp.controle_validate(self.root)
        self.assertFalse(ok)
        self.assertEqual([i["path"] for i in rapport["bloquants"]], ["catalog/assets/asset-kitchen-libre-0001.json"])

    def test_fuite_d_un_fichier_non_libre_bloquante(self):
        self.retirer("prive")  # copie publique, mais prive2 a fuité
        ok, rapport = cp.controle_validate(self.root)
        self.assertFalse(ok)
        self.assertEqual(rapport["fuites"], ["sprites/prive2.png"])
        self.assertEqual(rapport["nBloquants"], 0)

    def test_vignette_d_une_fiche_libre_aux_memes_octets_est_retiree_aussi(self):
        sha = self.fiches["prive"]["sha256"]
        jumelle = dict(self.fiches["libre"], id="asset-kitchen-jumelle-0001", sha256=sha,
                       thumbnail=f"thumbnails/{sha[:2]}/{sha}.webp")
        self.write(f"assets/{jumelle['id']}.json", jumelle)
        retires = cp.fiches_non_libres(self.root)
        self.assertEqual(retires["catalog/assets/asset-kitchen-jumelle-0001.json"]["fichiers"], [jumelle["thumbnail"]])
        self.assertTrue(retires["catalog/assets/asset-kitchen-jumelle-0001.json"]["libre"])


class DoublonsSansPixels(unittest.TestCase):
    AVANT = {"exact": [], "similar": [
        {"a": "x", "b": "y", "dhashDistance": 3, "phashDistance": 2, "pixelDistance": 30.4, "status": "distinct"},
        {"a": "y", "b": "z", "dhashDistance": 3, "phashDistance": 2, "pixelDistance": 1.0, "status": "needs-review"},
        {"a": "x", "b": "w", "dhashDistance": 1, "phashDistance": 1, "status": "linked-variant"}]}

    def public(self):
        return {"exact": [], "similar": [
            {"a": "x", "b": "y", "dhashDistance": 3, "phashDistance": 2, "status": "needs-review"},
            {"a": "y", "b": "z", "dhashDistance": 3, "phashDistance": 2, "pixelDistance": 1.0, "status": "needs-review"},
            {"a": "x", "b": "w", "dhashDistance": 1, "phashDistance": 1, "status": "linked-variant"}]}

    def test_seule_la_mesure_de_pixels_des_fiches_absentes_peut_differer(self):
        self.assertEqual(cp.normaliser_doublons(self.AVANT, {"x"}), cp.normaliser_doublons(self.public(), {"x"}))
        self.assertNotEqual(self.AVANT, self.public())  # sans normalisation : rouge, comme build-index sur GitHub

    def test_tout_autre_ecart_reste_rouge(self):
        hash_change = self.public()
        hash_change["similar"][0]["dhashDistance"] = 4
        self.assertNotEqual(cp.normaliser_doublons(self.AVANT, {"x"}), cp.normaliser_doublons(hash_change, {"x"}))
        # pixelDistance perdue sur une paire dont les deux binaires sont présents
        pixels_perdus = self.public()
        del pixels_perdus["similar"][1]["pixelDistance"]
        self.assertNotEqual(cp.normaliser_doublons(self.AVANT, {"x"}), cp.normaliser_doublons(pixels_perdus, {"x"}))


class VisuelSurCopiePublique(unittest.TestCase):
    def test_echantillon_ne_tire_que_les_vignettes_presentes(self):
        shas = [f"s{i}" for i in range(10)]
        presents = {"s1", "s4", "s7"}
        self.assertEqual(visuel.echantillon(shas, presents, 40), [1, 4, 7])
        self.assertEqual(visuel.echantillon(shas, set(shas), 5), [0, 2, 4, 6, 8])


if __name__ == "__main__":
    unittest.main()
