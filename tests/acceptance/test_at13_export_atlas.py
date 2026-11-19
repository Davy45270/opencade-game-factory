"""AT-13 (matrice E123) : « l'export d'un atlas PNG/JSON valide la transparence, les dimensions et les références. »"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from . import _contrat as C
from ._base import MondeScanne
from ._monde import BOUTON_B, FOUET

SORTIE = "atlases/oracle-at13"


class AT13ExportAtlas(MondeScanne):
    """AT-13 / E123 — « AT-13 : l'export d'un atlas PNG/JSON valide la transparence, les dimensions et les
    références. »

    Intention : `export-atlas` de deux assets rend 0 et produit un PNG RGBA (alpha réel) + un JSON hash
    dont chaque cadre a les dimensions de son asset ; `validate-atlas` rend 0 sur ce JSON, et 1 sur
    chaque version trafiquée : cadre hors image, référence pendante, dimensions fausses, PNG aplati
    sans transparence."""

    def _exporter(self) -> tuple[Path, dict, dict[str, dict]]:
        self.exiger_scan_ok()
        ids = {i: a for i, a in (self.asset("jeu-a", FOUET), self.asset("jeu-b", BOUTON_B))}
        r = self.ctl(C.cmd_export_atlas(sorted(ids), SORTIE))
        self.exiger_code(r, C.OK)
        dossier = self.reg / SORTIE
        candidats = [self.reg / f"{SORTIE}.json", *(sorted(dossier.glob("*.json")) if dossier.is_dir() else [])]
        json_atlas = next((p for p in candidats if p.is_file()), None)
        self.assertIsNotNone(json_atlas, f"JSON d'atlas introuvable parmi {candidats}")
        return json_atlas, C.lire_json(json_atlas), ids

    def _image(self, json_atlas: Path, atlas: dict) -> Path:
        return json_atlas.parent / atlas["meta"]["image"]

    def _cadres(self, atlas: dict, ids: dict[str, dict]) -> dict[str, dict]:
        """asset_id → frame, que le cadre soit nommé par l'ID ou le porte dans une valeur."""
        cadres = atlas["frames"]
        self.assertIsInstance(cadres, dict, "format hash attendu (Phaser load.atlas)")
        sortie = {}
        for cle, val in cadres.items():
            aid = cle if cle in ids else next((v for v in C.parcourir(val) if v in ids), None)
            self.assertIsNotNone(aid, f"cadre {cle} sans référence d'asset")
            sortie[aid] = val["frame"]
        return sortie

    def _trafiquer(self, nom: str, json_atlas: Path, atlas: dict, modifier) -> Path:
        dossier = self.reg / "atlases" / f"trafique-{nom}"
        dossier.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self._image(json_atlas, atlas), dossier / atlas["meta"]["image"])
        copie = json.loads(json.dumps(atlas))
        modifier(copie, dossier)
        cible = dossier / json_atlas.name
        cible.write_text(json.dumps(copie, indent=2), encoding="utf-8")
        return cible

    def test_export_valide(self):
        json_atlas, atlas, ids = self._exporter()
        img = Image.open(self._image(json_atlas, atlas))
        self.assertEqual(img.mode, "RGBA")
        self.assertLess(int(np.asarray(img)[..., 3].min()), 255, "transparence réelle attendue")
        cadres = self._cadres(atlas, ids)
        self.assertEqual(set(cadres), set(ids))
        for aid, f in cadres.items():
            d = ids[aid]["dimensions"]
            self.assertEqual((f["w"], f["h"]), (d["width"], d["height"]), aid)
            self.assertLessEqual(f["x"] + f["w"], img.width)
            self.assertLessEqual(f["y"] + f["h"], img.height)
        self.exiger_code(self.ctl(C.cmd_validate_atlas(json_atlas)), C.OK)

    def test_atlas_trafiques_refuses(self):
        json_atlas, atlas, ids = self._exporter()
        largeur = Image.open(self._image(json_atlas, atlas)).width
        premiere = next(iter(atlas["frames"]))

        def hors_image(a, _d):
            a["frames"][premiere]["frame"]["x"] = largeur

        def pendante(a, _d):
            texte = json.dumps(a)
            for aid in ids:
                texte = texte.replace(aid, aid.rsplit("-", 1)[0] + "-inexistant-9999")
            a.clear()
            a.update(json.loads(texte))

        def dimensions(a, _d):
            a["frames"][premiere]["frame"]["w"] -= 1

        def aplati(a, d):
            png = d / a["meta"]["image"]
            Image.open(png).convert("RGB").save(png)

        for nom, modif in (("hors-image", hors_image), ("pendante", pendante), ("dimensions", dimensions),
                           ("aplati", aplati)):
            with self.subTest(trafic=nom):
                cible = self._trafiquer(nom, json_atlas, atlas, modif)
                self.exiger_code(self.ctl(C.cmd_validate_atlas(cible)), C.ECHEC)
