"""Monde de fixture des tests d'acceptation : dépôts git de jeux factices, construits dans un dossier
temporaire, et une copie du registre qui ne connaît qu'eux (`provider: local`).

Aucun dépôt réel n'est lu, aucun accès réseau. Les formats de `provenance.json` et `*.decoupe.json`
reprennent ceux des vrais dépôts (capsule-panic) : boîte `[w, h, x, y]`, `planche_sha256`,
`origine: "planche" | "redessiné (marque)"`, `element_remplace: "WxH+X+Y"`.

Disposition :

    <tmp>/home/                 HOME de fixture (cache des miroirs par défaut, config git)
    <tmp>/registre/             copie du registre, catalogue vidé, dépôt git `main`
    <tmp>/depots/jeu-a/         jeu autorisé : tous les formats, une scène Phaser, une planche découpée
    <tmp>/depots/jeu-b/         jeu autorisé : cible de réutilisation (AT-14)
    <tmp>/depots/intrus/        dépôt NON autorisé (dans `excluded`)
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import struct
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from . import _contrat as C

# Planche de fixture et sa table de découpe : boîte au format RÉEL [w, h, x, y], volontairement
# non symétrique pour qu'une inversion (x, y) ↔ (w, h) se voie.
PLANCHE = "assets/source/Planche_Test.png"
DECOUPE = "assets/source/Planche_Test.elements.decoupe.json"
PROVENANCE = "assets/provenance.json"
ATLAS_ELEMENTS = "public/assets/atlas/elements.json"
ATLAS_ELEMENTS_PNG = "public/assets/atlas/elements.png"
ATLAS_PIONS = "public/assets/atlas/pions.json"
ATLAS_PIONS_PNG = "public/assets/atlas/pions.png"
BOITE_ETOILE = [40, 24, 100, 60]   # w, h, x, y — vérifiable (RMSE 0)
BOITE_NUAGE = [30, 30, 300, 300]   # le cadre de l'atlas NE vient PAS de cette boîte (RMSE élevé)
REMPLACE_LUNE = "20x20+200+200"    # élément redessiné : aucune région sur la planche

FOUET = "public/assets/fouet.png"              # PNG avec alpha, utilisé par Cuisine, sans provenance
NIVEAU = "public/assets/niveau-1.png"          # PNG sans alpha, cible d'un gabarit `${}` (jamais devinée)
TRONQUE = "public/assets/casse.png"            # PNG tronqué → exceptions.json
EXCLU = "node_modules/lib/cache.png"           # sous une exclusion déclarée
SCENE = "src/scenes/Cuisine.ts"
TEXTURES = "src/textures.ts"                   # asset dessiné par code
BOUTON_B = "public/assets/bouton.png"

#: Fichiers des formats pris en charge présents dans jeu-a (hors exclusions) — AT-02.
FORMATS_JEU_A = (
    FOUET, NIVEAU, TRONQUE,
    "public/assets/photo.jpg", "public/assets/fond.webp", "public/assets/anim.gif",
    "public/assets/icone.svg", "public/assets/perso.aseprite",
    ATLAS_ELEMENTS, ATLAS_ELEMENTS_PNG, ATLAS_PIONS, ATLAS_PIONS_PNG,
    "public/assets/carte.tmj", "public/assets/son.wav", "public/assets/musique.ogg",
    "public/assets/police.ttf", "public/assets/eau.glsl",
    PLANCHE, "assets/source/svg/lune.svg",
)


def png(arr: np.ndarray) -> bytes:
    mode = "RGBA" if arr.shape[2] == 4 else "RGB"
    b = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8), mode).save(b, "PNG", optimize=False)
    return b.getvalue()


def motif_etoile() -> np.ndarray:
    """40×24 opaque, dégradé : chaque pixel distinct, pour qu'un décalage se mesure."""
    y, x = np.mgrid[0:24, 0:40]
    return np.dstack([50 + 4 * x, 60 + 6 * y, np.full_like(x, 120), np.full_like(x, 255)])


def damier(w: int, h: int, c1, c2) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w]
    m = ((x // 5 + y // 5) % 2).astype(bool)
    a = np.zeros((h, w, 4), np.int32)
    a[m] = c1
    a[~m] = c2
    return a


def uni(w: int, h: int, c) -> np.ndarray:
    a = np.zeros((h, w, 4), np.int32)
    a[:, :] = c
    return a


def image_fouet() -> np.ndarray:
    a = np.zeros((48, 32, 4), np.int32)          # fond transparent
    a[4:44, 14:18] = (180, 180, 190, 255)         # tige
    a[30:46, 12:20] = (200, 30, 30, 255)          # manche rouge
    a[2:14, 8:24] = (170, 170, 180, 200)          # boucles (alpha partiel)
    return a


def planche() -> np.ndarray:
    a = np.zeros((512, 512, 4), np.int32)
    w, h, x, y = BOITE_ETOILE
    a[y:y + h, x:x + w] = motif_etoile()
    w, h, x, y = BOITE_NUAGE
    a[y:y + h, x:x + w] = (30, 60, 220, 255)
    a[200:220, 200:220] = (240, 220, 40, 255)
    return a


def atlas_elements() -> tuple[bytes, dict]:
    img = np.zeros((32, 128, 4), np.int32)
    cadres = {}
    for cle, (x, motif) in {
        "etoile": (2, motif_etoile()),
        "nuage": (44, damier(30, 30, (220, 30, 30, 255), (30, 200, 30, 255))),
        "lune": (76, damier(20, 20, (120, 40, 160, 255), (250, 250, 250, 255))),
    }.items():
        h, w = motif.shape[:2]
        img[2:2 + h, x:x + w] = motif
        cadres[C.PREFIXE_CADRE + cle] = {
            "frame": {"x": x, "y": 2, "w": w, "h": h}, "rotated": False, "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h}, "sourceSize": {"w": w, "h": h},
            "duration": 100}
    return png(img), {"frames": cadres, "meta": {"app": "fixture", "image": "elements.png",
                                                 "format": "RGBA8888", "size": {"w": 128, "h": 32},
                                                 "scale": "1"}}


def atlas_pions() -> tuple[bytes, dict]:
    img = np.zeros((16, 32, 4), np.int32)
    img[2:14, 2:14] = (10, 120, 200, 255)
    img[2:14, 18:30] = (200, 120, 10, 255)
    cadres = [{"filename": f"pion-{i}", "frame": {"x": x, "y": 2, "w": 12, "h": 12}, "rotated": False,
               "trimmed": False, "spriteSourceSize": {"x": 0, "y": 0, "w": 12, "h": 12},
               "sourceSize": {"w": 12, "h": 12}} for i, x in ((1, 2), (2, 18))]
    return png(img), {"frames": cadres, "meta": {"image": "pions.png", "size": {"w": 32, "h": 16},
                                                 "format": "RGBA8888", "scale": "1"}}


def gif_anime() -> bytes:
    images = [Image.new("P", (8, 8), i) for i in (1, 2)]
    for im in images:
        im.putpalette([0, 0, 0, 255, 0, 0, 0, 255, 0] + [0] * 759)
    b = io.BytesIO()
    images[0].save(b, "GIF", save_all=True, append_images=images[1:], duration=100, loop=0)
    return b.getvalue()


def aseprite() -> bytes:
    """En-tête Aseprite (magic 0xA5E0), 1 cadre 16×16 sans bloc."""
    cadre = struct.pack("<IHHHHI", 16, 0xF1FA, 0, 100, 0, 0)
    entete = struct.pack("<IHHHHHIHIIB3sHBBhhHH84s", 128 + len(cadre), 0xA5E0, 1, 16, 16, 32, 1, 100,
                         0, 0, 0, b"\0" * 3, 0, 1, 1, 0, 0, 16, 16, b"\0" * 84)
    assert len(entete) == 128
    return entete + cadre


def wav() -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 4000)  # 0,5 s exactement
    return b.getvalue()


def texte_scene() -> str:
    return (
        "import Phaser from 'phaser';\n"
        "\n"
        "export class Cuisine extends Phaser.Scene {\n"
        "  constructor() {\n"
        "    super('Cuisine');\n"
        "  }\n"
        "\n"
        "  preload(n: number): void {\n"
        "    this.load.image('fouet', 'assets/fouet.png');\n"
        "    this.load.image('niveau', `assets/niveau-${n}.png`);\n"
        "    this.load.atlas('elements', 'assets/atlas/elements.png', 'assets/atlas/elements.json');\n"
        "  }\n"
        "}\n")


def ligne_de(texte: str, motif: str) -> int:
    for i, ligne in enumerate(texte.splitlines(), 1):
        if motif in ligne:
            return i
    raise ValueError(motif)


@dataclass
class Monde:
    racine: Path
    home: Path
    registre: Path
    depots: Path
    commits: dict[str, str] = field(default_factory=dict)

    @property
    def cache(self) -> Path:
        return self.home / C.SOUS_CHEMIN_CACHE

    def depot(self, nom: str) -> Path:
        return self.depots / nom

    def ctl(self, args: list[str]) -> C.Resultat:
        return C.assetctl(self.registre, self.home, args)

    def git(self, depot: Path, *args: str, date: str | None = None) -> str:
        return C.git(depot, self.home, *args, date=date)

    def scan(self, *extra: str) -> C.Resultat:
        return self.ctl(C.cmd_scan(self.cache, *extra))

    def commiter_registre(self, message: str) -> str:
        # Dépôt de fixture jetable : tout ce que la CLI a produit y entre.
        self.git(self.registre, "add", "--all", "--", ".")
        self.git(self.registre, "commit", "-q", "--allow-empty", "-m", message)
        return self.git(self.registre, "rev-parse", "HEAD")

    def nettoyer(self) -> None:
        shutil.rmtree(self.racine, ignore_errors=True)


def _ecrire(depot: Path, fichiers: dict[str, bytes | str]) -> None:
    for rel, contenu in fichiers.items():
        f = depot / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contenu, str):
            f.write_text(contenu, encoding="utf-8")
        else:
            f.write_bytes(contenu)


def _depot(monde: Monde, nom: str, fichiers: dict[str, bytes | str], date: str) -> str:
    d = monde.depot(nom)
    d.mkdir(parents=True)
    monde.git(d, "init", "-q", "-b", "main")
    _ecrire(d, fichiers)
    monde.git(d, "add", "--", *sorted(fichiers))
    monde.git(d, "commit", "-q", "-m", f"{nom} : premier commit", date=date)
    return monde.git(d, "rev-parse", "HEAD")


def fichiers_jeu_a() -> dict[str, bytes | str]:
    planche_png = png(planche())
    sha_planche = hashlib.sha256(planche_png).hexdigest()
    elements_png, elements_json = atlas_elements()
    pions_png, pions_json = atlas_pions()
    decoupe = {"planche": "Planche_Test.png", "marge": 4, "taille": [40, 24], "elements": [
        {"id": "etoile", "boite": BOITE_ETOILE, "ancre": "centre", "taille": [40, 24]},
        {"id": "nuage", "boite": BOITE_NUAGE, "ancre": "centre", "taille": [30, 30]},
    ]}
    provenance = {"schemaVersion": 1, "outils": {"magick": "fixture"}, "assets": [
        {"id": C.PREFIXE_CADRE + "etoile", "origine": "planche", "planche": "Planche_Test.png",
         "planche_sha256": sha_planche, "boite": BOITE_ETOILE, "marge": 4, "ancre": "centre",
         "transformations": ["crop", "alpha<4%=0", "trim", "resize", "extent+ancre", "atlas json-hash"]},
        {"id": C.PREFIXE_CADRE + "nuage", "origine": "planche", "planche": "Planche_Test.png",
         "planche_sha256": sha_planche, "boite": BOITE_NUAGE, "marge": 4, "ancre": "centre",
         "transformations": ["crop", "alpha<4%=0", "trim", "resize", "extent+ancre", "atlas json-hash"]},
        {"id": C.PREFIXE_CADRE + "lune", "origine": "redessiné (marque)", "raison": "fixture",
         "svg": "assets/source/svg/lune.svg", "planche": "Planche_Test.png",
         "element_remplace": REMPLACE_LUNE, "transformations": ["rendu SVG", "atlas json-hash"],
         "planche_sha256": sha_planche},
    ]}
    tronque = png(uni(16, 16, (1, 2, 3, 255)))
    return {
        "package.json": json.dumps({"name": "jeu-a", "private": True}, indent=2) + "\n",
        "LICENSE": "MIT License\n\nCopyright (c) 2026 Fixture\n\nPermission is hereby granted, free of charge, "
                   "to any person obtaining a copy of this software and associated documentation files (the "
                   "\"Software\"), to deal in the Software without restriction, including without limitation "
                   "the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies "
                   "of the Software, and to permit persons to whom the Software is furnished to do so, subject "
                   "to the following conditions:\n\nThe above copyright notice and this permission notice shall "
                   "be included in all copies or substantial portions of the Software.\n\nTHE SOFTWARE IS "
                   "PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND.\n",
        SCENE: texte_scene(),
        TEXTURES: ("export function dessiner(scene: Phaser.Scene): void {\n"
                   "  const g = scene.add.graphics();\n"
                   "  g.fillStyle(0xff0000, 1);\n"
                   "  g.fillRect(0, 0, 8, 8);\n"
                   "  g.generateTexture('carre-rouge', 8, 8);\n"
                   "}\n"),
        FOUET: png(image_fouet()),
        NIVEAU: png(np.dstack([np.full((16, 16), v) for v in (90, 140, 60)])),
        TRONQUE: tronque[: len(tronque) // 2],
        "public/assets/photo.jpg": _jpeg(),
        "public/assets/fond.webp": _webp(),
        "public/assets/anim.gif": gif_anime(),
        "public/assets/icone.svg": ('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
                                    'viewBox="0 0 16 16"><rect x="2" y="2" width="12" height="12" '
                                    'fill="#3a7"/></svg>\n'),
        "public/assets/perso.aseprite": aseprite(),
        ATLAS_ELEMENTS_PNG: elements_png,
        ATLAS_ELEMENTS: json.dumps(elements_json, indent=2) + "\n",
        ATLAS_PIONS_PNG: pions_png,
        ATLAS_PIONS: json.dumps(pions_json, indent=2) + "\n",
        "public/assets/carte.tmj": json.dumps({
            "tiledversion": "1.10.2", "version": "1.10", "type": "map", "orientation": "orthogonal",
            "renderorder": "right-down", "infinite": False, "width": 2, "height": 2, "tilewidth": 16,
            "tileheight": 16, "tilesets": [], "layers": [
                {"type": "tilelayer", "name": "sol", "width": 2, "height": 2, "data": [0, 0, 0, 0],
                 "opacity": 1, "visible": True, "x": 0, "y": 0, "id": 1}],
            "nextlayerid": 2, "nextobjectid": 1}, indent=2) + "\n",
        "public/assets/son.wav": wav(),
        "public/assets/musique.ogg": b"OggS\x00\x02" + b"\x00" * 20 + b"\x01\x1e\x01vorbis" + b"\x00" * 23,
        "public/assets/police.ttf": b"\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
        "public/assets/eau.glsl": "precision mediump float;\nvoid main() { gl_FragColor = vec4(0.0, 0.3, 1.0, 1.0); }\n",
        PLANCHE: planche_png,
        "assets/source/svg/lune.svg": ('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
                                       '<circle cx="10" cy="10" r="9" fill="#7828a0"/></svg>\n'),
        DECOUPE: json.dumps(decoupe, ensure_ascii=False, indent=2) + "\n",
        PROVENANCE: json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        EXCLU: png(uni(8, 8, (9, 9, 9, 255))),
    }


def _jpeg() -> bytes:
    b = io.BytesIO()
    Image.fromarray(np.dstack([np.full((12, 20), v, np.uint8) for v in (200, 100, 50)]), "RGB").save(
        b, "JPEG", quality=90)
    return b.getvalue()


def _webp() -> bytes:
    b = io.BytesIO()
    Image.fromarray(uni(20, 10, (10, 200, 90, 128)).astype(np.uint8), "RGBA").save(b, "WEBP", lossless=True)
    return b.getvalue()


def fichiers_jeu_b() -> dict[str, bytes | str]:
    return {
        "package.json": json.dumps({"name": "jeu-b", "private": True}, indent=2) + "\n",
        "src/scenes/Menu.ts": ("export class Menu extends Phaser.Scene {\n"
                               "  constructor() {\n    super({ key: 'Menu' });\n  }\n"
                               "  preload(): void {\n    this.load.image('bouton', 'assets/bouton.png');\n  }\n}\n"),
        BOUTON_B: png(uni(24, 12, (40, 40, 200, 255))),
    }


def creer_monde(fantome: bool = False) -> Monde:
    """Construit le monde de fixture. `fantome=True` ajoute à la liste d'autorisation un dépôt
    autorisé mais inaccessible (chemin absent)."""
    racine = Path(tempfile.mkdtemp(prefix="oracle-assetctl-"))
    monde = Monde(racine=racine, home=racine / "home", registre=racine / "registre", depots=racine / "depots")
    monde.home.mkdir()
    (monde.home / ".gitconfig").write_text("[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    monde.commits["jeu-a"] = _depot(monde, "jeu-a", fichiers_jeu_a(), "2026-02-01T10:00:00+00:00")
    monde.git(monde.depot("jeu-a"), "tag", "v1.0")
    monde.commits["jeu-b"] = _depot(monde, "jeu-b", fichiers_jeu_b(), "2026-02-02T10:00:00+00:00")
    monde.commits["intrus"] = _depot(monde, "intrus", {
        "public/intrus-secret.png": png(uni(8, 8, (255, 0, 255, 255))),
        "README.md": "hors périmètre\n"}, "2026-02-03T10:00:00+00:00")

    C.copier_registre(monde.registre, monde.home)
    entrees = [C.source_locale("jeu-a", monde.depot("jeu-a")), C.source_locale("jeu-b", monde.depot("jeu-b"))]
    if fantome:
        entrees.append(C.source_locale("fantome", monde.depots / "fantome-absent"))
    C.ecrire_sources(monde.registre, entrees,
                     [{"name": "intrus", "reason": "fixture : dépôt hors périmètre"}])
    monde.commiter_registre("Registre de fixture : catalogue vide")
    return monde


def ajouter_commit(monde: Monde, nom: str, ecrire: dict[str, bytes | str], supprimer: tuple[str, ...],
                   date: str, message: str) -> str:
    d = monde.depot(nom)
    _ecrire(d, ecrire)
    if ecrire:
        monde.git(d, "add", "--", *sorted(ecrire))
    if supprimer:
        monde.git(d, "rm", "-q", "--", *supprimer)
    monde.git(d, "commit", "-q", "-m", message, date=date)
    monde.commits[nom] = monde.git(d, "rev-parse", "HEAD")
    return monde.commits[nom]
