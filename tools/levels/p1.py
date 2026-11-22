"""EXT-002 P1/P2 (`assetctl level …`) : similarité expliquée (LV-16), jeux libres à licence vérifiée par source
(LV-17), capture PNG et revue non bloquante (LV-18), bot de pilotage kart (LV-19), catalogue web statique (LV-20),
pipeline request → … → PR (E205) et adoption d'une version publiée par branche du jeu (E197).

Aucun algorithme nouveau n'est inventé : génération = générateurs existants (tools/levels/generate.py, BSP standard),
validation = validateurs existants, pilotage = poursuite pure (pure pursuit) sur un modèle cinématique de bicyclette,
recherche de trajectoire = Dijkstra sur la ligne médiane de la piste (ADR-0008).
"""

import heapq
import html
import io
import json
import math
import re
import subprocess
from argparse import Namespace
from pathlib import Path, PurePosixPath

from tools.core.catalog import json_text, read_json
from tools.levels import LevelExit, status_code
from tools.levels.formats import Unsupported, parse, semantics

# --- LV-16 : similarité expliquée -----------------------------------------------------------------------------------

POIDS = {"genre": 0.35, "dimensions": 0.2, "entites": 0.3, "structure": 0.15}


def _profil(record):
    level = record["content"]
    sem = semantics(level)
    types = {}
    for e in sem["entities"]:
        types[e["type"]] = types.get(e["type"], 0) + 1
    cells = max(1, level["width"] * level["height"])
    return {"kind": record["kind"], "w": level["width"], "h": level["height"], "types": types,
            "plein": len(sem["solid"]) / cells, "piste": len(sem["track"]) / cells,
            "mecaniques": set(record.get("mechanics", []))}


def _cos(a, b):
    keys = set(a) | set(b)
    num = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else (1.0 if not a and not b else 0.0)


def similarite(a, b):
    """Score dans [0, 1] et sa décomposition : chaque composante donne sa valeur, son poids et sa contribution."""
    pa, pb = _profil(a), _profil(b)
    valeurs = {
        "genre": 1.0 if pa["kind"] == pb["kind"] else 0.0,
        "dimensions": (min(pa["w"], pb["w"]) / max(pa["w"], pb["w"], 1)) * (min(pa["h"], pb["h"]) / max(pa["h"], pb["h"], 1)),
        "entites": _cos(pa["types"], pb["types"]),
        "structure": max(0.0, 1 - abs(pa["plein"] - pb["plein"]) - abs(pa["piste"] - pb["piste"])),
    }
    explication = {k: {"valeur": round(v, 4), "poids": POIDS[k], "contribution": round(v * POIDS[k], 4)}
                   for k, v in valeurs.items()}
    explication["entites"]["communes"] = sorted(set(pa["types"]) & set(pb["types"]))
    return round(sum(e["contribution"] for e in explication.values()), 4), explication


def similar(root, args, records, envelope):
    ref = records.get(args.similar_to)
    if ref is None:
        return envelope(LevelExit.MISSING_REFERENCE, "failed", diagnostics=[{
            "code": "level-not-found", "severity": "error", "message": f"niveau introuvable : {args.similar_to}"}])
    rows = []
    for record in records.values():
        if record["id"] == ref["id"] or (args.type and record["kind"] != args.type):
            continue
        score, explication = similarite(ref, record)
        rows.append({"id": record["id"], "kind": record["kind"], "name": record["name"],
                     "game": record["origin"]["game"], "score": score, "explication": explication})
    rows.sort(key=lambda r: (-r["score"], r["id"]))
    return envelope(LevelExit.OK, "ok", reference=ref["id"], results=rows[: args.limit])


# --- LV-18 / LV-20 : capture PNG sans écran ------------------------------------------------------------------------

COULEURS = {"fond": (246, 243, 236), "plein": (60, 60, 72), "piste": (170, 170, 170), "start": (40, 160, 70),
            "finish": (40, 160, 70), "spawn": (40, 160, 70), "goal": (230, 180, 30), "checkpoint": (60, 120, 220),
            "key": (220, 60, 60), "door": (150, 40, 40), "boss": (140, 40, 160), "hazard": (240, 120, 20)}


def capture(record, maximum=512):
    """PNG déterministe du niveau (cellules pleines, piste, entités) : mêmes octets pour le même contenu."""
    from PIL import Image, ImageDraw

    level = record["content"]
    sem = semantics(level)
    w, h = max(1, level["width"]), max(1, level["height"])
    k = max(2, min(16, maximum // max(w, h)))
    image = Image.new("RGB", (w * k, h * k), COULEURS["fond"])
    draw = ImageDraw.Draw(image)
    for (x, y) in sorted(sem["track"]):
        draw.rectangle([x * k, y * k, x * k + k - 1, y * k + k - 1], fill=COULEURS["piste"])
    for (x, y) in sorted(sem["solid"]):
        draw.rectangle([x * k, y * k, x * k + k - 1, y * k + k - 1], fill=COULEURS["plein"])
    for e in sem["entities"]:
        couleur = COULEURS.get(e["type"], (120, 120, 120))
        boite = [e["x"] * k + 1, e["y"] * k + 1, (e["x"] + e["w"]) * k - 2, (e["y"] + e["h"]) * k - 2]
        if e["w"] == 1 and e["h"] == 1:
            draw.ellipse(boite, fill=couleur)
        else:
            draw.rectangle(boite, outline=couleur, width=max(1, k // 4))
    sortie = io.BytesIO()
    image.save(sortie, format="PNG", optimize=False)
    return sortie.getvalue()


def review(root, args, record, run_validators, envelope):
    """Rapport de revue multimodale NON bloquant : capture + mesures automatiques + questions pour un relecteur
    (humain ou modèle de vision). Il ne juge jamais l'amusement et ne bloque jamais une PR."""
    from tools.core.catalog import write_json

    rapport_auto = run_validators(record, None)
    dossier = Path(args.out)
    png = capture(record)
    rapport = {"id": record["id"], "bloquant": False, "capture": f"{record['id']}.png",
               "contentSha256": record["contentSha256"], "validation": rapport_auto["status"],
               "diagnostics": rapport_auto["diagnostics"],
               "revueHumaine": ["Lisibilité : départ, objectif et dangers se repèrent-ils sur la capture ?",
                                "Cohérence du style avec le jeu demandeur ?",
                                "Zones vides ou couloirs sans intérêt ?",
                                "Difficulté perçue cohérente avec la place du niveau dans le jeu ?"],
               "note": "revue non bloquante : aide à la décision, jamais un verdict d'amusement (EXT-002 LV-18)"}
    if not args.dry_run:
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / f"{record['id']}.png").write_bytes(png)
        write_json(dossier / f"{record['id']}.json", rapport)
    return envelope(LevelExit.OK, "report", [str(dossier / f"{record['id']}.png"),
                                              str(dossier / f"{record['id']}.json")], rapport=rapport)


# --- LV-19 : bot kart (modèle de bicyclette, poursuite pure) -------------------------------------------------------

def _clairance(track, width, height):
    def libre(cx, cy):
        return (cx, cy) in track

    def f(px, py):
        best = 3.0
        for cy in range(int(py) - 3, int(py) + 4):
            for cx in range(int(px) - 3, int(px) + 4):
                if libre(cx, cy):
                    continue
                dx = max(cx - px, 0, px - (cx + 1))
                dy = max(cy - py, 0, py - (cy + 1))
                best = min(best, math.hypot(dx, dy))
        return best
    return f


def ligne_mediane(level, sem, stops, pas=0.5, marge=0.3):
    """Boucle départ → points de contrôle → départ sur un réseau de pas 0,5 case, coût qui préfère la ligne médiane
    de la piste (Dijkstra) ; chaque étape évite les autres arrêts. Rend la liste des points, ou None."""
    width, height, track = level["width"], level["height"], sem["track"]
    clair = _clairance(track, width, height)
    noeuds = {}
    for j in range(0, int(height / pas) + 1):
        for i in range(0, int(width / pas) + 1):
            p = (i * pas, j * pas)
            c = clair(*p)
            if c >= marge:
                noeuds[(i, j)] = c

    def cellule(n):
        return (int(n[0] * pas), int(n[1] * pas))

    trajet = []
    for (_, a), (_, b) in zip(stops, stops[1:]):
        autres = set().union(set(), *[cells for _, cells in stops if cells is not a and cells is not b])
        depart = [n for n in noeuds if cellule(n) in a] if not trajet else [trajet[-1]]
        cible = {n for n in noeuds if cellule(n) in b}
        dist = {n: 0.0 for n in depart}
        prec = {}
        tas = [(0.0, n) for n in depart]
        fin = None
        while tas:
            d, n = heapq.heappop(tas)
            if d > dist.get(n, math.inf):
                continue
            if n in cible and d > 0:
                fin = n
                break
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    m = (n[0] + di, n[1] + dj)
                    if m == n or m not in noeuds or (cellule(m) in autres and m not in cible):
                        continue
                    nd = d + math.hypot(di, dj) * pas * (1 + 1.5 / noeuds[m])
                    if nd < dist.get(m, math.inf):
                        dist[m], prec[m] = nd, n
                        heapq.heappush(tas, (nd, m))
        if fin is None:
            return None
        morceau = [fin]
        while morceau[-1] not in depart:
            morceau.append(prec[morceau[-1]])
        morceau.reverse()
        trajet += morceau if not trajet else morceau[1:]
    return [(i * pas, j * pas) for i, j in trajet]


def bot_kart(level, kart, limite_s=None):
    """Simule un tour. `kart` : turningRadius (cases), maxSpeed (cases/s), grip (accélération latérale, cases/s²).
    Rend les mesures : sortiesDePiste, tourSecondes, pointsDeControle franchis (dans l'ordre), vitesse moyenne."""
    sem = semantics(level)
    track = sem["track"]
    start = set().union(set(), *[{(e["x"] + i, e["y"] + j) for i in range(e["w"]) for j in range(e["h"])}
                                 for e in sem["entities"] if e["type"] in {"start", "finish"}])
    groupes = {}
    for e in sem["entities"]:
        if e["type"] == "checkpoint":
            groupes.setdefault(int(e["props"].get("order", 0)), set()).update(
                {(e["x"] + i, e["y"] + j) for i in range(e["w"]) for j in range(e["h"])})
    stops = [("départ", start), *((str(o), groupes[o]) for o in sorted(groupes)), ("arrivée", start)]
    chemin = ligne_mediane(level, sem, stops)
    if not chemin or len(chemin) < 3:
        return {"status": "fail", "code": "kart-no-line", "message": "aucune ligne de course continue sur la piste"}
    rayon = float(kart["turningRadius"])
    vmax, grip = float(kart.get("maxSpeed", 5.0)), float(kart.get("grip", 6.0))
    kmax = 1 / max(rayon, 1e-3)
    ld = max(0.8, min(2.0, rayon))
    x, y = chemin[0]
    theta = math.atan2(chemin[1][1] - y, chemin[1][0] - x)
    longueur = sum(math.dist(a, b) for a, b in zip(chemin, chemin[1:]))
    limite_s = limite_s or 30 + 4 * longueur / max(vmax, 0.1)
    dt, t, i, distance = 0.02, 0.0, 0, 0.0
    vus, quitte_depart, sorties = [], False, 0
    while t < limite_s:
        while i < len(chemin) - 1 and math.dist((x, y), chemin[i]) < ld:
            i += 1
        cx, cy = chemin[i]
        alpha = math.atan2(cy - y, cx - x) - theta
        alpha = (alpha + math.pi) % (2 * math.pi) - math.pi
        k = 2 * math.sin(alpha) / max(ld, math.dist((x, y), (cx, cy)), 1e-6)
        k = max(-kmax, min(kmax, k))
        v = min(vmax, math.sqrt(grip / max(abs(k), 1e-6)))
        x += v * math.cos(theta) * dt
        y += v * math.sin(theta) * dt
        theta += v * k * dt
        t += dt
        distance += v * dt
        cellule = (math.floor(x), math.floor(y))
        if cellule not in track:
            sorties += 1
            return {"status": "fail", "code": "kart-off-track", "sortiesDePiste": sorties, "t": round(t, 2),
                    "position": [round(x, 2), round(y, 2)],
                    "message": f"le kart (rayon de braquage {rayon} cases) sort de la piste en "
                               f"({x:.1f}, {y:.1f}) après {t:.1f} s"}
        for ordre in sorted(groupes):
            if cellule in groupes[ordre] and (not vus or vus[-1] != ordre) and ordre not in vus:
                vus.append(ordre)
        if cellule not in start:
            quitte_depart = True
        elif quitte_depart and len(vus) == len(groupes):
            return {"status": "pass", "sortiesDePiste": 0, "tourSecondes": round(t, 2),
                    "pointsDeControle": vus, "vitesseMoyenne": round(distance / t, 2),
                    "ligneDeCourse": round(longueur, 1), "modele": "bicyclette cinématique, poursuite pure",
                    "kart": {"turningRadius": rayon, "maxSpeed": vmax, "grip": grip}}
    return {"status": "fail", "code": "kart-lap-timeout", "pointsDeControle": vus,
            "message": f"tour non bouclé en {limite_s:.0f} s (points franchis : {vus})"}


# --- LV-17 : jeux libres, licence vérifiée par source --------------------------------------------------------------

def niveaux_libres(root):
    path = Path(root) / "external" / "niveaux-libres.json"
    return read_json(path)["sources"] if path.is_file() else []


def libre(root, args, store, envelope):
    from tools.external.adapters import ProviderUnavailable
    from tools.external.client import Client
    from tools.external.licenses import LicenseEvaluator

    sources = [s for s in niveaux_libres(root) if args.id in (None, s["id"])]
    if not sources:
        return envelope(LevelExit.MISSING_REFERENCE, "failed", diagnostics=[{
            "code": "source-not-found", "severity": "error",
            "message": f"source absente de external/niveaux-libres.json : {args.id}"}])
    client = Client()
    total = {"created": [], "observed": [], "unchanged": [], "artifacts": [], "diagnostics": []}
    for src in sources:
        repo, ref = src["repo"], src["ref"]
        review = src.get("review") or {}
        if not re.fullmatch(r"[0-9a-f]{40}", ref) or not all(str(review.get(k, "")).strip()
                                                              for k in ("licence", "securite", "par", "date", "pr")):
            return envelope(LevelExit.INVALID_INPUT, "failed", diagnostics=[{
                "code": "source-unreviewed", "severity": "error",
                "message": f"{src['id']} : commit figé (40 hex) et revue complète obligatoires"}])
        raw = f"https://raw.githubusercontent.com/{repo}/{ref}"
        cache = {}

        def lire(chemin):
            if chemin not in cache:
                try:
                    cache[chemin] = client.get(f"{raw}/{chemin}")[1]
                except ProviderUnavailable:
                    cache[chemin] = None
            return cache[chemin]

        try:
            arbre = json.loads(client.get(f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1")[1])
        except ProviderUnavailable as exc:
            return envelope(LevelExit.INFRASTRUCTURE, "failed", diagnostics=[{
                "code": "source-unavailable", "severity": "error", "message": str(exc)}])
        motif = re.compile(src.get("paths", r".*"))
        texte = lire(src["licenceFile"])
        verdict = LicenseEvaluator().verify(src["licence"], {src["licenceFile"]: texte.decode("utf-8", "replace")}
                                            if texte else {})
        candidats = []
        for noeud in arbre.get("tree", []):
            chemin = noeud.get("path", "")
            if noeud.get("type") != "blob" or not motif.search(chemin):
                continue
            contenu = lire(chemin)
            if contenu is None:
                continue
            dossier = PurePosixPath(chemin).parent

            def lecteur(relatif, dossier=dossier):
                cible = (dossier / relatif).as_posix()
                return None if ".." in PurePosixPath(cible).parts else lire(cible)
            try:
                niveaux = parse(chemin, contenu, lecteur)
            except (Unsupported, ValueError, KeyError, TypeError):
                continue
            candidats += [(chemin, contenu, n) for n in niveaux]
        ns = Namespace(game=src.get("game") or src["id"], kind=src.get("kind"), universe=src.get("universe", "libre"),
                       author=src.get("author"), source_url=f"https://github.com/{repo}/tree/{ref}",
                       dry_run=args.dry_run)
        code, res = store(root, ns, candidats, {"provider": "github", "repo": f"https://github.com/{repo}",
                                                "commit": ref}, verdict)
        if code != LevelExit.OK:
            return code, res
        for k in ("created", "observed", "unchanged", "artifacts", "diagnostics"):
            total[k] += res.get(k, [])
        total["diagnostics"].append({"code": "code-licence-distincte", "severity": "info", "message":
                                     f"{src['id']} : licence du code ({src.get('codeLicence', 'non précisée')}) ≠ licence "
                                     f"des cartes ({verdict['spdx']}, preuve : {verdict['evidence']})"})
    return envelope(LevelExit.OK, "ok", total["artifacts"], total["diagnostics"], created=total["created"],
                    observed=total["observed"], unchanged=total["unchanged"], dryRun=args.dry_run)


# --- LV-20 : catalogue web statique ---------------------------------------------------------------------------------

STYLE = ("body{font-family:system-ui,sans-serif;margin:16px;background:#f6f3ec;color:#222}"
         "li{margin:4px 0}img{image-rendering:pixelated;max-width:100%;border:1px solid #999}"
         "@media (prefers-color-scheme:dark){body{background:#1d1d22;color:#eee}}")
FILTRE = ("<script>function f(){const g=document.getElementById('g').value;for(const li of "
          "document.querySelectorAll('li[data-genre]'))li.hidden=g&&li.dataset.genre!==g}</script>")


def pages(records):
    """{nom de fichier: octets} du site : index filtrable par genre + une page et une capture par niveau."""
    genres = sorted({r["kind"] for r in records})
    sorties = {}
    lignes = []
    for r in sorted(records, key=lambda r: r["id"]):
        o = r["origin"]
        lignes.append(f'<li data-genre="{html.escape(r["kind"])}" data-licence="{html.escape(o["license"])}">'
                      f'<a href="{r["id"]}.html">{html.escape(r["id"])}</a> — {html.escape(r["name"])} '
                      f'({html.escape(r["kind"])}, {html.escape(o["game"])}, {html.escape(o["license"])})</li>')
        detail = (f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                  f'<title>{html.escape(r["id"])}</title><style>{STYLE}</style><p><a href="index.html">← catalogue</a>'
                  f'<h1>{html.escape(r["name"])}</h1><img src="{r["id"]}.png" alt="capture du niveau">'
                  f'<ul><li>genre : {html.escape(r["kind"])}</li><li>jeu : {html.escape(o["game"])}</li>'
                  f'<li>licence : {html.escape(o["license"])} ({html.escape(o["licenseStatus"])})</li>'
                  f'<li>source : {html.escape(str(o["sourceRepo"]))} @ {html.escape(str(o["sourceCommit"])[:12])} — '
                  f'{html.escape(str(o["sourcePath"]))}</li>'
                  f'<li>dimensions : {r["geometry"]["width"]}×{r["geometry"]["height"]}</li>'
                  f'<li>mécaniques : {html.escape(", ".join(r.get("mechanics", [])) or "—")}</li>'
                  f'<li>versions publiées : {html.escape(", ".join(v["version"] for v in r.get("versions", [])) or "—")}'
                  f'</li><li>contenu : <code>{r["contentSha256"][:16]}</code></li></ul>\n')
        sorties[f"{r['id']}.html"] = detail.encode()
        sorties[f"{r['id']}.png"] = capture(r)
    options = "".join(f'<option value="{html.escape(g)}">{html.escape(g)}</option>' for g in genres)
    index = (f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
             f'<title>Catalogue des niveaux</title><style>{STYLE}</style>{FILTRE}<h1>Niveaux ({len(records)})</h1>'
             f'<label>Genre <select id="g" onchange="f()"><option value="">tous</option>{options}</select></label>'
             f'<ul>{"".join(lignes)}</ul>\n')
    sorties["index.html"] = index.encode()
    return sorties


def site(root, args, records, envelope):
    attendu = pages(list(records.values()))
    dossier = Path(args.out)
    nb_pages = sum(1 for n in attendu if n.endswith(".html"))
    if args.check:
        present = {p.name for p in dossier.glob("*")} if dossier.is_dir() else set()
        perimes = sorted(n for n, b in attendu.items() if not (dossier / n).is_file() or (dossier / n).read_bytes() != b)
        en_trop = sorted(present - set(attendu))
        if perimes or en_trop:
            return envelope(LevelExit.VALIDATION_FAILED, "perime", diagnostics=[{
                "code": "site-stale", "severity": "error",
                "message": f"catalogue web périmé : {len(perimes)} fichier(s) à régénérer, {len(en_trop)} en trop "
                           f"(assetctl level site --out {args.out})"}], perimes=perimes[:20], enTrop=en_trop[:20],
                pages=nb_pages)
        return envelope(LevelExit.OK, "a-jour", pages=nb_pages)
    ecrits = []
    if not args.dry_run:
        dossier.mkdir(parents=True, exist_ok=True)
        for p in dossier.glob("*"):
            if p.name not in attendu and p.suffix in (".html", ".png"):
                p.unlink()
        for nom, octets in attendu.items():
            cible = dossier / nom
            if not cible.is_file() or cible.read_bytes() != octets:
                cible.write_bytes(octets)
                ecrits.append(nom)
    return envelope(LevelExit.OK, "ecrit", [str(dossier / n) for n in ecrits[:50]], pages=nb_pages,
                    ecrits=len(ecrits))


# --- Git sans toucher l'arbre de travail : une branche, un commit -------------------------------------------------

GIT_ID = ["-c", "user.name=opencade-asset-registry", "-c", "user.email=registre@opencade.invalid",
          "-c", "commit.gpgsign=false"]


def commit_sur_branche(depot, branche, fichiers, message, base="HEAD"):
    """Commit de `fichiers` ({chemin: octets}) sur `branche` créée depuis `base`, par la plomberie git : ni l'arbre de
    travail ni la branche courante ne bougent. Rend le sha du commit."""
    import os
    import tempfile

    def git(*a, entree=None, env=None):
        return subprocess.run(["git", "-C", str(depot), *GIT_ID, *a], input=entree, capture_output=True, check=True,
                              env=env).stdout.decode().strip()

    parent = git("rev-parse", "--verify", f"{base}^{{commit}}")
    if subprocess.run(["git", "-C", str(depot), "rev-parse", "--verify", "--quiet", f"refs/heads/{branche}"],
                      capture_output=True).returncode == 0:
        raise ValueError(f"la branche {branche} existe déjà")
    with tempfile.TemporaryDirectory(prefix="registre-index-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git("read-tree", parent, env=env)
        for chemin, octets in sorted(fichiers.items()):
            blob = git("hash-object", "-w", "--stdin", entree=octets)
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{chemin}", env=env)
        arbre = git("write-tree", env=env)
    commit = git("commit-tree", arbre, "-p", parent, "-m", message)
    git("update-ref", f"refs/heads/{branche}", commit)
    return commit


# --- E197 : adoption d'une version publiée par PR du jeu ------------------------------------------------------------

def adopt(root, args, envelope):
    publie = Path(root) / "published" / "levels" / args.level_id / f"{args.version}.json"
    if not re.fullmatch(r"level-[a-z0-9-]+", args.level_id) or not publie.is_file():
        return envelope(LevelExit.MISSING_REFERENCE, "failed", diagnostics=[{
            "code": "level-not-found", "severity": "error",
            "message": f"{args.level_id}@{args.version} n'est pas publiée (assetctl level publish)"}])
    version = read_json(publie)
    depot = Path(args.repo)
    base = args.base or "HEAD"
    try:
        actuel = subprocess.run(["git", "-C", str(depot), "show", f"{base}:level.lock.json"], capture_output=True,
                                check=True).stdout
        verrou = json.loads(actuel)
    except subprocess.CalledProcessError:
        verrou = {"schemaVersion": "1.0", "game": args.game, "levels": []}
    entree = {"id": version["id"], "version": version["version"], "sha256": version["sha256"]}
    autres = [e for e in verrou.get("levels", []) if e.get("id") != version["id"]]
    avant = next((e for e in verrou.get("levels", []) if e.get("id") == version["id"]), None)
    if avant == entree:
        return envelope(LevelExit.OK, "unchanged", lock=entree)
    verrou["levels"] = sorted([*autres, entree], key=lambda e: e["id"])
    branche = args.branch or f"niveaux/{args.level_id}-{args.version}"
    message = (f"Niveau {version['id']} {version['version']} (registre EXT-002)\n\n"
               f"{'mise à jour depuis ' + avant['version'] if avant else 'adoption'} ; sha256 {version['sha256']}")
    if args.dry_run:
        return envelope(LevelExit.OK, "dry-run", branch=branche, lock=entree, previous=avant)
    commit = commit_sur_branche(depot, branche, {"level.lock.json": (json_text(verrou)).encode()}, message, base)
    return envelope(LevelExit.OK, "branch-ready", branch=branche, commit=commit, lock=entree, previous=avant,
                    next="pousser la branche et ouvrir la PR du jeu (revue humaine avant fusion)")


# --- E205 : pipeline request → … → PR --------------------------------------------------------------------------------

ETAPES = ("request", "search", "candidate-scoring", "reuse/derive/generate", "normalize", "validators",
          "simulated-playtest", "visual-render", "pr")
SEUIL_REUTILISATION = 0.8


def _score_demande(record, demande):
    c = demande.get("constraints") or {}
    genre = 1.0 if record["kind"] == demande.get("genre") else 0.0
    w, h = record["geometry"]["width"], record["geometry"]["height"]
    if c.get("width") and c.get("height"):
        dims = (min(w, c["width"]) / max(w, c["width"])) * (min(h, c["height"]) / max(h, c["height"]))
    else:
        dims = 1.0
    termes = set(re.findall(r"\w+", str(demande.get("query", "")).lower()))
    texte = set(re.findall(r"\w+", " ".join([record["id"], record["name"], *record.get("mechanics", [])]).lower()))
    requete = len(termes & texte) / len(termes) if termes else 1.0
    score = round(0.5 * genre + 0.3 * dims + 0.2 * requete, 4)
    return score, {"genre": genre, "dimensions": round(dims, 4), "requete": round(requete, 4)}


def pipeline(root, args, ctx):
    """ctx : load_all, generate_record, run_validators, validators, agents, envelope, write_check."""
    envelope = ctx["envelope"]
    trace = []

    def etape(nom, **detail):
        trace.append({"etape": nom, **detail})

    demande = read_json(args.request)
    if demande.get("genre") not in ctx["kinds"]:
        return envelope(LevelExit.INVALID_INPUT, "failed", diagnostics=[{
            "code": "request", "severity": "error", "message": f"genre attendu parmi {ctx['kinds']}"}])
    etape("request", genre=demande["genre"], query=demande.get("query", ""), constraints=demande.get("constraints"))
    records = ctx["load_all"](root)
    candidats = [r for r in records.values() if r["kind"] == demande["genre"]]
    etape("search", candidats=len(candidats))
    notes = sorted(((*_score_demande(r, demande), r) for r in candidats), key=lambda t: (-t[0], t[2]["id"]))
    etape("candidate-scoring", meilleurs=[{"id": r["id"], "score": s, "detail": d} for s, d, r in notes[:5]],
          seuil=SEUIL_REUTILISATION)
    decision, record = None, None
    for score, _, r in notes:
        if score < SEUIL_REUTILISATION:
            break
        if ctx["run_validators"](r, demande.get("profile"))["status"] == "pass":
            decision, record = {"action": "reuse", "id": r["id"], "score": score}, r
            break
    if record is None and notes and demande.get("transforms"):
        parent = notes[0][2]
        decision = {"action": "derive", "from": parent["id"], "transforms": demande["transforms"]}
        record = ctx["derive_record"](parent, demande["transforms"], args.seed)
    if record is None:
        try:
            record = ctx["generate_record"](demande, args.seed)
        except KeyError:
            etape("reuse/derive/generate", action="none")
            return envelope(LevelExit.INVALID_INPUT, "failed", diagnostics=[{
                "code": "no-generator", "severity": "error",
                "message": f"aucun candidat ≥ {SEUIL_REUTILISATION} et aucun générateur pour {demande['genre']} : "
                           "importer un niveau existant (ADR-0008)"}], etapes=trace)
        decision = {"action": "generate", "id": record["id"], "algorithm": record["generation"]["algorithm"],
                    "algorithmVersion": record["generation"]["algorithmVersion"], "seed": args.seed}
    etape("reuse/derive/generate", **decision)
    erreur = ctx["write_check"](record)
    etape("normalize", contentSha256=record["contentSha256"], schema="ok" if erreur is None else erreur)
    if erreur is not None:
        return envelope(LevelExit.INVALID_INPUT, "failed", diagnostics=[{
            "code": "invalid-record", "severity": "error", "message": erreur}], etapes=trace, decision=decision)
    rapport = ctx["run_validators"](record, demande.get("profile"))
    etape("validators", status=rapport["status"], diagnostics=len(rapport["diagnostics"]))
    agent = next((a for a, k in ctx["agents"].items() if k == record["kind"]), None)
    jeu = ctx["validators"][record["kind"]](record["content"], demande.get("profile") or {}, None) \
        if record["kind"] in ctx["validators"] else {"status": "inconclusive", "metrics": {}}
    etape("simulated-playtest", agent=agent, status=jeu["status"], metrics=jeu.get("metrics"))
    png = capture(record)
    etape("visual-render", octets=len(png))
    code = status_code(rapport["status"], rapport["diagnostics"])
    if code != LevelExit.OK:
        etape("pr", status="refusée : validation " + rapport["status"])
        return envelope(code, rapport["status"], diagnostics=rapport["diagnostics"], etapes=trace, decision=decision)
    if decision["action"] == "reuse":
        etape("pr", status="rien à proposer : niveau existant réutilisé")
        return envelope(LevelExit.OK, "reuse", etapes=trace, decision=decision, pr=None)
    corps = (f"Demande : {demande['genre']} « {demande.get('query', '')} », contraintes "
             f"{json.dumps(demande.get('constraints'), ensure_ascii=False)}\n"
             f"Décision : {decision['action']} ({decision.get('algorithm', decision.get('from'))}), seed {args.seed}\n"
             f"Validation : {rapport['status']} ; playtest simulé : {jeu['status']}\n"
             "Candidats examinés : " + (", ".join(f"{r['id']} ({s})" for s, _, r in notes[:5]) or "aucun") + "\n")
    branche = args.branch or f"niveaux/{record['id']}"
    if args.dry_run:
        etape("pr", status="dry-run", branch=branche)
        return envelope(LevelExit.OK, "dry-run", etapes=trace, decision=decision,
                        pr={"branch": branche, "body": corps})
    fichiers = {f"catalog/levels/{record['id']}.json": json_text(record).encode(),
                f"generated/levels-review/{record['id']}.png": png}
    commit = commit_sur_branche(root, branche, fichiers, f"Niveau {record['id']} (pipeline EXT-002)\n\n{corps}")
    etape("pr", status="branch-ready", branch=branche, commit=commit)
    return envelope(LevelExit.OK, "branch-ready", etapes=trace, decision=decision,
                    pr={"branch": branche, "commit": commit, "body": corps})
