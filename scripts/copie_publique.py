#!/usr/bin/env python3
"""Contrôles du registre sur sa COPIE PUBLIQUE GitHub (Davy45270/opencade-game-factory), E026 / E106 / E258.

La copie publique est la forge moins les fichiers des fiches SANS LICENCE LIBRE (HL-538 7-3316, décision de David :
forge/usine-github-public.py de homelab-diag les retire de l'arbre ; la fiche texte reste). Depuis le 22/11, les
workflows GitHub qui lisent les binaires échouaient donc tous sur cette copie : `validate` (missing-registry-file),
`build-index` (`pixelDistance` absente de generated/duplicates.json) et `visual` (vignettes absentes).

Ce script rend ces contrôles exacts sur la copie publique SANS les affaiblir ailleurs :
  validate : `assetctl validate` ; seul un `missing-registry-file` d'une fiche NON LIBRE dont le fichier est absent
             est toléré. Tout autre problème bloque, y compris un fichier absent d'une fiche libre.
             Garde de fuite : dès qu'un fichier non libre manque (on est sur la copie publique), un fichier non libre
             PRÉSENT est une fuite et bloque.
  index    : `assetctl index`, puis generated/ doit être identique au commit, à une seule différence près :
             `pixelDistance` retirée des paires de generated/duplicates.json qui touchent une fiche dont le binaire
             est absent (cette distance se calcule sur les pixels).
Sur l'arbre complet de la forge, aucun fichier ne manque : les deux contrôles valent exactement `assetctl validate`
et le contrôle de build-index de Woodpecker.
Codes : 0 conforme, 1 écart, 2 usage. Rapport JSON sur stdout.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
# MÊME règle que LIBRES dans homelab-diag/forge/usine-github-public.py (la synchro qui retire les fichiers).
LIBRES = re.compile(r"^(CC0-1\.0|CC-BY(-SA)?-(2\.0|2\.5|3\.0|4\.0)|MIT|MIT-0|Apache-2\.0|ISC|BSD-[23]-Clause|0BSD|Unlicense"
                    r"|Zlib|OFL-1\.1|MPL-2\.0|LicenseRef-OGA-BY-3\.0)$")


def _fichiers(d):
    """Fichiers d'une fiche lus par les contrôles : `files.*` (chaînes) et la vignette."""
    fichiers = [v for v in d["files"].values() if isinstance(v, str)] if isinstance(d.get("files"), dict) else []
    if isinstance(d.get("thumbnail"), str):
        fichiers.append(d["thumbnail"])
    return fichiers


def fiches_non_libres(racine):
    """{chemin de fiche: {"id", "libre", "fichiers", "absents"}} : fichiers que la synchro publique RETIRE.

    Comme `_non_libres()` de usine-github-public.py : une fiche sans licence libre perd ses fichiers `files.*`, et
    tout chemin dont le nom porte son SHA-256 disparaît aussi, y compris la vignette d'une fiche LIBRE qui a les mêmes
    octets (`libre: True`, seuls ces chemins-là sont comptés)."""
    fiches = {}
    for f in sorted((racine / "catalog").rglob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(d, dict) and "license" in d:
            fiches[f.relative_to(racine).as_posix()] = d
    shas = {str(d.get("sha256")).lower() for d in fiches.values()
            if not LIBRES.match(str(d.get("license"))) and isinstance(d.get("sha256"), str)}
    out = {}
    for chemin, d in fiches.items():
        libre = bool(LIBRES.match(str(d.get("license"))))
        sha = str(d.get("sha256")).lower()
        if libre and sha not in shas:
            continue
        fichiers = [c for c in _fichiers(d) if not libre or sha in c.rsplit("/", 1)[-1].lower()]
        if fichiers:
            out[chemin] = {"id": d.get("id"), "libre": libre, "fichiers": fichiers,
                           "absents": [c for c in fichiers if not (racine / c).exists()]}
    return out


def trier(issues, non_libres):
    """(tolérés, bloquants) : seul un missing-registry-file d'une fiche non libre dont un fichier manque est toléré."""
    toleres, bloquants = [], []
    for i in issues:
        n = non_libres.get(i.get("path"))
        if i.get("code") == "missing-registry-file" and n and n["absents"]:
            toleres.append(i)
        else:
            bloquants.append(i)
    return toleres, bloquants


def fuites(non_libres):
    """Copie publique (au moins un fichier non libre absent) : chaque fichier non libre encore présent est une fuite."""
    if not any(n["absents"] for n in non_libres.values()):
        return []
    return sorted(c for n in non_libres.values() if not n["libre"] for c in n["fichiers"] if c not in n["absents"])


def _sans_pixels(paire):
    """Ce que tools/index/dedup.rule() rend quand un binaire est illisible : la paire sans `pixelDistance`, et le statut
    tiré des pixels (`distinct` ou `needs-review`) ramené à `needs-review` ; `linked-variant` ne dépend pas des pixels."""
    if "pixelDistance" not in paire:
        return paire
    return {**{k: v for k, v in paire.items() if k != "pixelDistance"}, "status": "needs-review"}


def normaliser_doublons(doublons, ids):
    """generated/duplicates.json tel que la copie publique doit le recalculer : les paires qui touchent `ids` (fiches
    dont le binaire est absent) passent par _sans_pixels. Le reste est comparé tel quel."""
    out = {}
    for cle, paires in doublons.items():
        if not isinstance(paires, list):
            out[cle] = paires
            continue
        out[cle] = [_sans_pixels(p) if isinstance(p, dict) and (p.get("a") in ids or p.get("b") in ids) else p
                    for p in paires]
    return out


def _assetctl(racine, *args):
    """`assetctl <args> --json` en processus, sur la racine donnée (comme la fixture des tests) : (code, rapport)."""
    import contextlib
    import io
    sys.path.insert(0, str(RACINE))
    from tools.cli import main
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(io.StringIO()):
        code = main([*args, "--json"], root=racine)
    try:
        return code, json.loads(sortie.getvalue())
    except ValueError:
        return code, {"ok": False, "stdout": sortie.getvalue()[-2000:]}


def controle_validate(racine):
    non_libres = fiches_non_libres(racine)
    code, rapport = _assetctl(racine, "validate")
    toleres, bloquants = trier(rapport.get("issues", []), non_libres)
    fuite = fuites(non_libres)
    if code != 0 and not rapport.get("issues"):
        bloquants.append({"code": "validate-sans-rapport", "message": f"assetctl validate code {code}", "detail": rapport})
    ok = not bloquants and not fuite
    return ok, {"controle": "validate", "ok": ok, "assetctlCode": code, "toleres": len(toleres),
                "bloquants": bloquants[:50], "nBloquants": len(bloquants), "fuites": fuite[:50], "nFuites": len(fuite)}


def _git(racine, *args):
    return subprocess.run(["git", *args], cwd=racine, capture_output=True, text=True, check=True).stdout


def controle_index(racine):
    non_libres = fiches_non_libres(racine)
    ids = {n["id"] for n in non_libres.values() if n["absents"]}
    code, _ = _assetctl(racine, "index")
    ecarts = []
    if code != 0:
        ecarts.append(f"assetctl index code {code}")
    for ligne in _git(racine, "status", "--porcelain", "--untracked-files=all", "--", "generated/").splitlines():
        chemin = ligne[3:]
        if chemin != "generated/duplicates.json" or ligne[:2] != " M":
            ecarts.append(ligne)
            continue
        avant = json.loads(_git(racine, "show", "HEAD:generated/duplicates.json"))
        apres = json.loads((racine / chemin).read_text(encoding="utf-8"))
        if normaliser_doublons(avant, ids) != normaliser_doublons(apres, ids):
            ecarts.append(" M generated/duplicates.json (au-delà de pixelDistance des fiches absentes)")
    ok = not ecarts
    return ok, {"controle": "index", "ok": ok, "fichesAbsentes": len(ids), "ecarts": ecarts[:50]}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("controle", choices=("validate", "index"))
    p.add_argument("--racine", type=Path, default=RACINE)
    a = p.parse_args(argv)
    ok, rapport = (controle_validate if a.controle == "validate" else controle_index)(a.racine.resolve())
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
