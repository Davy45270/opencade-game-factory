"""REG-07 / E110 / EXT-12 : recherche visuelle CLIP et dédoublonnage expliqué — index DÉRIVÉ, reconstructible.

- `assetctl visual embed` calcule un vecteur par vignette (une par empreinte SHA-256 : un même fichier = un vecteur)
  et écrit `generated/visual/<modèle>.npz` + `.json` (modèle, empreintes, versions). Calcul GPU sur tank01 SEULEMENT
  (Intel Arc, `xpu`) : sur Zalman, le GPU est réservé à Jellyfin et la commande refuse tout autre appareil que `cpu`
  (arbitrage de David du 27/09). `--device cpu` est le mode de la CI.
- `assetctl visual search --text "…" | --image FICHIER` classe par cosinus CLIP et EXPLIQUE chaque résultat :
  score CLIP, distance perceptuelle (phash, image seulement), étiquettes communes, et `verdict` : identique (SHA-256),
  quasi-identique (phash ≤ 6), similaire (CLIP ≥ 0,90) ou proche. Une similarité ne vaut jamais identité (EXT-001 § 9).

Back-ends : `clip` (open_clip, ViT-B-32 laion2b_s34b_b79k ; dépendances dans requirements-visual.txt) et `couleurs`
(histogramme de couleurs, déterministe, sans dépendance : pour les tests hors ligne seulement).
"""

import hashlib
import json
import os
import socket
from pathlib import Path

import numpy as np
from PIL import Image

from tools.core.catalog import read_json, write_json
from tools.core.exit_codes import ExitCode

CLIP_MODEL, CLIP_PRETRAINED = "ViT-B-32", "laion2b_s34b_b79k"
HOTES_SANS_GPU = {"zalman"}


class Refus(RuntimeError):
    pass


def appareil(demande, hote=None):
    """`auto` : xpu (tank01) si présent, sinon cpu. Jamais un GPU sur Zalman (refus, pas de repli silencieux)."""
    hote = (hote or socket.gethostname()).split(".")[0].lower()
    if demande not in ("auto", "cpu", "xpu", "cuda"):
        raise Refus(f"appareil inconnu : {demande}")
    if hote in HOTES_SANS_GPU and demande not in ("auto", "cpu"):
        raise Refus(f"{hote} : GPU réservé à Jellyfin, calcul visuel en cpu seulement (GPU : tank01)")
    if demande != "auto":
        return demande
    if hote in HOTES_SANS_GPU:
        return "cpu"
    try:
        import torch

        if hasattr(torch, "xpu") and torch.xpu.is_available():
            return "xpu"
    except ImportError:
        pass
    return "cpu"


class Couleurs:
    """Back-end de test : histogramme 4×4×4 des couleurs opaques, normalisé. Aucun texte (pas de requête textuelle)."""

    nom, version = "couleurs", "1"

    def images(self, chemins):
        lignes = []
        for chemin in chemins:
            image = Image.open(chemin).convert("RGBA").resize((32, 32))
            px = np.asarray(image).reshape(-1, 4)
            px = px[px[:, 3] > 0][:, :3] // 64
            h = np.zeros(64, dtype=np.float32)
            np.add.at(h, px[:, 0] * 16 + px[:, 1] * 4 + px[:, 2], 1)
            lignes.append(h)
        return _normer(np.stack(lignes)) if lignes else np.zeros((0, 64), np.float32)

    def texte(self, requete):
        raise Refus("le back-end couleurs ne lit pas de texte (clip seulement)")


class Clip:
    nom = f"clip-{CLIP_MODEL.lower()}-{CLIP_PRETRAINED}"

    def __init__(self, device):
        import open_clip
        import torch

        self.torch, self.device = torch, device
        self.model, _, self.pre = open_clip.create_model_and_transforms(CLIP_MODEL, pretrained=CLIP_PRETRAINED,
                                                                        device=device)
        self.model.eval()
        self.tok = open_clip.get_tokenizer(CLIP_MODEL)
        self.version = f"open_clip {open_clip.__version__}, torch {torch.__version__}"

    def images(self, chemins, lot=64):
        sorties = []
        with self.torch.no_grad():
            for i in range(0, len(chemins), lot):
                tenseurs = [self.pre(_sur_blanc(Image.open(c))) for c in chemins[i:i + lot]]
                v = self.model.encode_image(self.torch.stack(tenseurs).to(self.device))
                sorties.append(v.float().cpu().numpy())
        return _normer(np.concatenate(sorties)) if sorties else np.zeros((0, 512), np.float32)

    def texte(self, requete):
        with self.torch.no_grad():
            v = self.model.encode_text(self.tok([requete]).to(self.device))
        return _normer(v.float().cpu().numpy())[0]


def _sur_blanc(image):
    image = image.convert("RGBA")
    fond = Image.new("RGBA", image.size, (255, 255, 255, 255))
    return Image.alpha_composite(fond, image).convert("RGB")


def _normer(m):
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return (m / np.where(n == 0, 1, n)).astype(np.float32)


def backend(nom, device):
    if nom == "couleurs":
        return Couleurs()
    if nom == "clip":
        return Clip(device)
    raise Refus(f"back-end inconnu : {nom}")


def vignettes(root):
    """{sha256 de l'asset: (chemin de la vignette, [ids])} pour chaque fiche qui cite une vignette présente."""
    rows = {}
    for path in sorted((Path(root) / "catalog" / "assets").glob("*.json")):
        asset = read_json(path)
        thumb = asset.get("thumbnail")
        if thumb and (Path(root) / thumb).is_file():
            rows.setdefault(asset["sha256"], (Path(root) / thumb, []))[1].append(asset["id"])
    return rows


def _fichiers(root, nom):
    base = Path(root) / "generated" / "visual"
    return base / f"{nom}.npz", base / f"{nom}.json"


def embed(root, args):
    try:
        device = appareil(args.device)
        b = backend(args.backend, device)
    except (Refus, ImportError) as exc:
        return ExitCode.USAGE, {"ok": False, "error": "visual-refused", "message": str(exc)}
    rows = vignettes(root)
    shas = sorted(rows)[: args.limit] if args.limit else sorted(rows)
    vecteurs = b.images([rows[s][0] for s in shas])
    meta = {"schemaVersion": "1.0", "backend": b.nom, "version": b.version, "device": device,
            "count": len(shas), "dimensions": int(vecteurs.shape[1]) if len(shas) else 0,
            "thumbnailsSha256": hashlib.sha256("\n".join(shas).encode()).hexdigest()}
    if not args.dry_run:
        npz, js = _fichiers(root, args.out or b.nom)
        npz.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(npz, sha256=np.array(shas), vecteurs=vecteurs.astype(np.float16))
        write_json(js, meta)
    return ExitCode.OK, {"ok": True, **meta}


def _charger(root, nom):
    npz, js = _fichiers(root, nom)
    if not npz.is_file():
        raise Refus(f"index visuel {nom} absent : assetctl visual embed")
    data = np.load(npz)
    return list(data["sha256"]), _normer(data["vecteurs"].astype(np.float32)), read_json(js)


def search(root, args):
    from tools.index.dedup import fingerprints

    try:
        shas, matrice, meta = _charger(root, args.index or ("couleurs" if args.backend == "couleurs" else Clip.nom))
        b = backend(args.backend, appareil(args.device))
        if args.text:
            q, phash, sha_q, tags_q = b.texte(args.text), None, None, set(args.text.casefold().split())
        else:
            q = b.images([args.image])[0]
            raw = Path(args.image).read_bytes()
            sha_q = hashlib.sha256(raw).hexdigest()
            phash = int(fingerprints(Image.open(args.image))["phash"], 16)
            tags_q = set()
    except (Refus, ImportError, OSError) as exc:
        return ExitCode.USAGE, {"ok": False, "error": "visual-refused", "message": str(exc)}
    scores = matrice @ q
    rows = vignettes(root)
    fiches = {}
    resultats = []
    for i in np.argsort(-scores)[: args.limit]:
        sha = shas[i]
        ids = rows.get(sha, (None, []))[1]
        asset = fiches.setdefault(sha, read_json(Path(root) / "catalog" / "assets" / f"{ids[0]}.json")) if ids else {}
        explication = {"clipCosine": round(float(scores[i]), 4), "backend": meta["backend"]}
        if phash is not None and asset.get("perceptual", {}).get("phash"):
            explication["phashDistance"] = (phash ^ int(asset["perceptual"]["phash"], 16)).bit_count()
        communes = sorted(tags_q & set(asset.get("tags", [])))
        if communes:
            explication["etiquettesCommunes"] = communes
        if sha_q and sha == sha_q:
            verdict = "identique (SHA-256)"
        elif explication.get("phashDistance", 64) <= 6:
            verdict = "quasi-identique (phash ≤ 6) : à revoir, jamais fusionné"
        elif scores[i] >= 0.90:
            verdict = "similaire (CLIP ≥ 0,90) : une similarité ne vaut pas identité"
        else:
            verdict = "proche"
        resultats.append({"sha256": sha, "ids": ids, "score": explication["clipCosine"], "verdict": verdict,
                          "explication": explication})
    return ExitCode.OK, {"ok": True, "index": meta["backend"], "requete": args.text or str(args.image),
                         "results": resultats}


def configure(parser, caller_path):
    import argparse

    sub = parser.add_subparsers(dest="visual_command", required=True)
    e = sub.add_parser("embed", allow_abbrev=False)
    s = sub.add_parser("search", allow_abbrev=False)
    for c in (e, s):
        c.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        c.add_argument("--backend", choices=("clip", "couleurs"), default="clip")
        c.add_argument("--device", default="auto")
        c.add_argument("--dry-run", action="store_true")
    e.add_argument("--limit", type=int)
    e.add_argument("--out")
    q = s.add_mutually_exclusive_group(required=True)
    q.add_argument("--text")
    q.add_argument("--image", type=caller_path)
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--index")


def run(root, args):
    return (embed if args.visual_command == "embed" else search)(root, args)
