#!/usr/bin/env python3
"""Cadres LIVRÉS par un jeu à un commit → registre d'assets, avec leurs usages (HL-538, P17 de l'usine).

Un jeu livre ses images en atlas (une image + un JSON à `frames`). Le registre doit connaître chaque cadre livré par
ses PIXELS, et savoir que ce jeu l'emploie à ce commit. Le cadre livré n'est souvent pas la découpe brute de la
planche, mais sa forme normalisée par le jeu (taille, détourage, projection, encodage WebP).

Pour chaque cadre distinct (même empreinte de pixels que la barrière P17), l'outil :
  - réemploie l'asset du registre qui a déjà ces pixels, s'il existe ;
  - sinon l'enregistre avec `assetctl register` et un reçu de recherche (`assetctl search --receipt`) ; chaque
    candidat du reçu est rejeté avec son motif mesuré. La fiche devient `derived` : `derivedFrom` est l'asset brut
    du même élément (table de découpe du jeu). La recette (table au commit, élément, empreinte, sha du jeu,
    paramètres d'encodage) va dans la provenance.
Il enregistre aussi chaque image d'atlas livrée, que le jeu pourra citer dans son assets.lock.json.
Enfin il écrit les usages `<jeu>@<sha>` dans les fiches et lance `assetctl index rebuild`. Il ne matérialise aucun
fichier dans le jeu : les fichiers livrés y sont déjà.

Les usages qu'il a posés pour ce jeu (marque « importer_livre ») sont remplacés à chaque passage. Une seconde passe
au même sha ne change donc rien, et une passe à un nouveau sha déplace les usages (le commit du lock, par exemple).

`--lock FICHIER` écrit en plus le assets.lock.json du jeu (schéma lock 1.0) : une ligne par image d'atlas livrée,
avec `path` = son chemin dans le jeu et `sha256` = ses octets. Le registryCommit est le HEAD du registre, qui doit
être publié (contenu dans origin/main).

Monorepo (profil `monorepo`, ex. src/games) : un jeu = un sous-dossier, nommé `<dépôt>/<sous-dossier>` ; le jeu
`<dépôt>` seul est la coquille (tout ce qui n'est dans aucun sous-dossier de jeu). L'usage cite le jeu ET le sha du
dépôt. Les images livrées hors atlas (icônes, photos, sprites isolés) sont aussi enregistrées et employées.

Rien n'est inventé : sans règle de profil prouvée, une image est enregistrée `repo-file`, auteur et licence `unknown`,
et elle est listée dans `sans_origine`.

Usage : scripts/importer_livre.py <jeu> <sha> [--depot DÉPÔT] [--travail DOSSIER] [--lock FICHIER] [--dry-run]
"""
import argparse, hashlib, io, json, re, subprocess, sys, tempfile
from pathlib import Path, PurePosixPath

REG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REG))
from tools.core.catalog import write_json  # noqa: E402
from tools.discovery.snapshots import DELIVERED_MARK as MARQUE  # noqa: E402  (le scan garde ces usages)
from tools.discovery.formats import CODE, DRAW  # noqa: E402  (même détection « dessiné par le code » que le scan)
ASSETCTL = str(REG / "assetctl")

# Profil d'un DÉPÔT : où trouver la table de découpe d'un atlas (`parents`), la décision de licence de ses dessins
# bruts, et, pour un monorepo, le dossier des jeux. Un dépôt sans profil : tout en repo-file, auteur et licence inconnus.
PROFILS = {
    "pestouille-rpg": {
        "parents": "manifestes",
        "manifestes": "assets/export/*.manifest.json",      # {source: table, frames: json de l'atlas}
        "prefixe_cadre": "sprite-",                          # cadre « sprite-<élément> » → élément de la table
        "planches": "~/Projets/homelab-docs/specs/pestouille-rpg-sources/planches",
        "univers": "pestouille",
        "licence": "LicenseRef-David-Prive-Tous-Droits-Reserves",
        "licence_preuve": {"method": "décision du propriétaire", "ref": "HL-538 7-3162",
                           "decision": "Dessins de Pestouille fournis par David : privé, tous droits réservés ; "
                                       "publiables à travers tout jeu de David qui les emploie (HL-538, 2026-11-21)."},
        "auteur": "David (dessin fourni par David ; auteur ou outil de création non déclaré)",
        # Images isolées DÉCLARÉES par assets/provenance.json du jeu (`assets` par source/élément, `hors_atlas` par
        # fichier avec son SHA-256), chaque famille avec ses origines admises et les preuves exigées dans l'entrée.
        # Absente du fichier, origine non admise ou preuve manquante : inconnue, listée dans sans_origine.
        "provenance_images": "assets/provenance.json",
        "images": [
            *({"prefixe": prefixe, "declaree": True, "origines": ["planche"],
               "licence": "LicenseRef-David-Prive-Tous-Droits-Reserves",
               "auteur": "David (dessin fourni par David ; découpé par le jeu, assets/provenance.json)",
               "licence_preuve": {"method": "décision du propriétaire", "ref": "HL-538 7-3162",
                                  "decision": "Dessins de Pestouille fournis par David (héros, créatures, variantes) : "
                                              "privé, tous droits réservés ; publiables à travers tout jeu de David "
                                              "qui les emploie."}}
              for prefixe in ("assets/cutouts/",)),
            # Redessins : dérivés d'une planche de David dans un jeu de David, ils gardent sa licence privée ; la
            # planche source et son SHA-256 doivent être cités (décision du coordinateur, HL-537, 2026-11-21).
            *({"prefixe": prefixe, "declaree": True, "origines": ["redessiné (marque)"],
               "exige": ["planche", "planche_sha256"],
               "licence": "LicenseRef-David-Prive-Tous-Droits-Reserves",
               "auteur": "redessin dans le style des planches de Davy45270 (assets/provenance.json)",
               "licence_preuve": {"method": "décision du propriétaire", "ref": "HL-538 7-3162 ; HL-537",
                                  "decision": "Dessins de David = licence privée ; une dérivation dans un jeu de "
                                              "David garde cette licence (redessin citant sa planche source et son "
                                              "SHA-256, 2026-11-21)."}}
              for prefixe in ("assets/redessine/", "public/assets/redessine/")),
            # Hors atlas : tuiles découpées de la planche 02, icônes dessinées dans le dépôt ; le SHA-256 déclaré du
            # fichier doit être celui des octets livrés.
            *({"prefixe": prefixe, "declaree": True, "origines": origines, "exige": ["sha256"],
               "licence": "LicenseRef-David-Prive-Tous-Droits-Reserves",
               "auteur": auteur,
               "licence_preuve": {"method": "décision du propriétaire", "ref": "HL-538 7-3162 ; HL-537",
                                  "decision": "Images hors atlas déclarées avec leur origine et leur SHA-256 dans "
                                              "assets/provenance.json (hors_atlas) : licence privée de David "
                                              "(2026-11-21)."}}
              for prefixe, origines, auteur in (
                  ("assets/cartes/", ["planche"], "David (planche découpée par le jeu, assets/provenance.json)"),
                  ("public/assets/cartes/", ["planche"], "David (planche découpée par le jeu, assets/provenance.json)"),
                  ("public/icons/", ["dessiné dans le dépôt"], None))),
        ],
    },
    "cozy-room-sort": {
        "parents": "provenance",
        "provenance": "content/assets/provenance.json",     # [{id, atlas, origine: {planche, sha256, boite, marge}}]
        "prefixe_cadre": "sprite-",
        "planches": "~/Projets/homelab-docs/specs/cozy-room-sort-sources/planches",
        "univers": "cozy-room-sort",
        "licence": "CC-BY-4.0",
        "licence_preuve": {"method": "déclaration du titulaire, découpe vérifiée",
                           "ref": "cozy-room-sort README.md (« Illustrations de Davy45270 sous licence CC BY 4.0 ») ; "
                                  "content/assets/provenance.json (licence par dessin) ; HL-538",
                           "decision": "Illustrations de Cozy Room Sort par Davy45270 : CC-BY-4.0, déclarée par lui dans "
                                       "le dépôt et rétablie sur sa consigne (HL-538, 2026-11-21), après découpe "
                                       "refaite depuis la planche (empreinte identique à provenance.json)."},
        "auteur": "Davy45270 (illustrations ; README du jeu)",
        # Images dérivées d'un dessin de David (icônes depuis un cadre, état normal recoloré), déclarées par
        # provenance.json (`derives[].fichier` ou `fichiers`) avec la planche source et son SHA-256 : elles prennent la
        # licence de la planche (consigne du 2026-11-21), si la planche citée est bien celle, aux mêmes octets.
        "provenance_images": "content/assets/provenance.json",
        "images": [{"prefixe": prefixe, "declaree": True, "origines": ["dérivé"], "exige": ["planche", "planche_sha256"],
                    "planche_verifiee": True, "licence": "CC-BY-4.0",
                    "auteur": "Davy45270 (dessin de la planche, dérivé par le jeu ; content/assets/provenance.json)",
                    "licence_preuve": {"method": "déclaration du titulaire, dérivation d'une planche vérifiée",
                                       "ref": "cozy-room-sort README.md ; HL-538",
                                       "decision": "Image dérivée d'une illustration de Davy45270 (CC-BY-4.0) sans trait "
                                                   "nouveau : elle garde la licence de sa planche source (2026-11-21)."}}
                   for prefixe in ("apps/web/public/icons/", "content/assets/planches/derives/")],
    },
    "capsule-panic": {
        "parents": "inventaire",
        "inventaire": "packages/assets/assets.inventaire.json",   # fichiers[{chemin d'atlas, decoupe: table}]
        "prefixe_cadre": "sprite-",
        "planches": "~/Projets/jeux/assets/planches/capsule-panic",
        "univers": "capsule-panic",
        "licence": "CC-BY-4.0",
        "licence_preuve": {"method": "déclaration du titulaire",
                           "ref": "capsule-panic packages/assets/LICENCES.md (« Davy45270 est l'auteur des visuels de "
                                  "Capsule Panic […] distribués sous Creative Commons Attribution 4.0 ») ; "
                                  "packages/assets/assets.inventaire.json (licence par fichier) ; HL-538",
                           "decision": "Visuels de Capsule Panic par Davy45270 : CC-BY-4.0, déclarée par lui pour les "
                                       "sprites, atlas, planche transparente et sources graphiques."},
        "auteur": "Davy45270 (LICENCES.md du jeu)",
        # Cadres redessinés ou dérivés (recettes .redessines/.retouches.json) : aucun élément de découpe ; enregistrés
        # tels que livrés (repo-file), sous la licence que le titulaire déclare pour les sprites et atlas.
        "sans_element": True,
        # Images livrées hors atlas : licence DÉCLARÉE par le titulaire dans le jeu. assets.inventaire.json déclare
        # chaque fichier (chemin, SHA-256 des octets, licence, planche source et son SHA-256 : planche vérifiée) ;
        # licences.json déclare la licence de chaque sprite par son identifiant (version encodée runtime/<id>.webp).
        "declarations_licence": [{"fichier": "packages/assets/assets.inventaire.json", "format": "inventaire"},
                                 {"fichier": "packages/assets/licences.json", "format": "liste"}],
        "images": [
            {"prefixe": "apps/web/public/icons/capsule-panic-", "licence": "MIT",
             "auteur": "Davy45270 (icônes dessinées par scripts/make-icons.js du jeu)",
             "licence_preuve": {"method": "historique git : licence de la source",
                                "ref": "capsule-panic 1bf4f05 (scripts/make-icons.js dessine les icônes en SVG) ; "
                                       "91d3a18 (oxipng sans perte) ; LICENSE (MIT, Davy45270) ; HL-538",
                                "decision": "Icônes PWA produites par le code du dépôt : elles prennent la licence du "
                                            "code qui les dessine, MIT (2026-11-22)."}},
            {"prefixe": "packages/assets/planche-transparente.png", "licence": "CC-BY-4.0",
             "auteur": "Davy45270 (LICENCES.md du jeu)",
             "licence_preuve": {"method": "déclaration du titulaire",
                                "ref": "capsule-panic packages/assets/LICENCES.md (« les sprites, les atlas, la planche "
                                       "transparente et les sources graphiques sont distribués sous CC BY 4.0 ») ; HL-538",
                                "decision": "Planche transparente de Capsule Panic, nommée par LICENCES.md : CC BY 4.0."}},
            {"prefixe": "packages/assets/runtime/", "declaree": True, "origines": ["licences.json"],
             "licence_declaree": "CC BY 4.0", "titulaire": "Davy45270", "licence": "CC-BY-4.0",
             "auteur": "Davy45270 (packages/assets/licences.json du jeu)",
             "licence_preuve": {"method": "déclaration du titulaire",
                                "ref": "capsule-panic packages/assets/licences.json ; LICENCES.md ; HL-538",
                                "decision": "Sprite de Capsule Panic (version encodée runtime) dont licences.json "
                                            "déclare l'identifiant : titulaire Davy45270, CC BY 4.0."}},
            {"prefixe": "packages/assets/", "declaree": True, "origines": ["inventaire"], "licence_declaree": "CC BY 4.0",
             "exige": ["planche", "planche_sha256", "sha256"], "planche_verifiee": True, "licence": "CC-BY-4.0",
             "auteur": "Davy45270 (packages/assets/assets.inventaire.json et LICENCES.md du jeu)",
             "licence_preuve": {"method": "déclaration du titulaire, fichier et planche vérifiés",
                                "ref": "capsule-panic packages/assets/LICENCES.md ; HL-538",
                                "decision": "Visuel de Capsule Panic par Davy45270, déclaré CC BY 4.0 fichier par "
                                            "fichier (SHA-256 identique aux octets livrés, planche source vérifiée)."}},
        ],
        # Fiches `derived` du scan sans parent (cadres redessinés ou dérivés réemployés) : provenance.json du jeu donne
        # la source de chaque cadre — le SVG d'un redessin (asset aux mêmes octets), la boîte de planche d'un dérivé
        # (découpe brute importée si absente). Le parent devient `derivedFrom`, avec un reçu de recherche.
        "provenance_derives": "packages/assets/provenance.json",
        # SVG source d'un redessin (parent d'un cadre livré) : « sources graphiques » nommées par LICENCES.md.
        "regle_sources": {"licence": "CC-BY-4.0", "auteur": "Davy45270 (LICENCES.md du jeu)",
                          "licence_preuve": {"method": "déclaration du titulaire",
                                             "ref": "capsule-panic packages/assets/LICENCES.md (« les sources graphiques "
                                                    "sont distribuées sous CC BY 4.0 ») ; provenance.json (svg du "
                                                    "redessin) ; HL-538",
                                             "decision": "Source SVG d'un redessin de Capsule Panic par Davy45270 : "
                                                         "CC BY 4.0."}},
        # Cadres d'atlas réemployés (fiche du scan sans licence, redessin ou dérivé) : licence établie si licences.json
        # déclare l'identifiant du cadre et que la fiche n'est employée que par ce dépôt.
        "cadres_declares": {"prefixe": "", "declaree": True, "origines": ["licences.json"],
                            "licence_declaree": "CC BY 4.0", "titulaire": "Davy45270", "licence": "CC-BY-4.0",
                            "auteur": "Davy45270 (packages/assets/licences.json du jeu)",
                            "licence_preuve": {"method": "déclaration du titulaire",
                                               "ref": "capsule-panic packages/assets/licences.json ; LICENCES.md ; HL-538",
                                               "decision": "Cadre d'atlas de Capsule Panic dont licences.json déclare "
                                                           "l'identifiant : titulaire Davy45270, CC BY 4.0."}},
    },
    "echecs-kid": {
        # Icônes PWA : la tour blanche de src/art/pieces.ts rastérisée par scripts/make-icons.js (commit 419b6f6).
        "images": [{"prefixe": "public/icons/echecs-", "licence": "MIT",
                    "auteur": "Davy45270 (icônes dessinées par scripts/make-icons.js depuis src/art/pieces.ts)",
                    "licence_preuve": {"method": "historique git : licence de la source",
                                       "ref": "echecs-kid 419b6f6 (« icônes PWA régénérées depuis la tour » : "
                                              "scripts/make-icons.js rastérise pieceSvg de src/art/pieces.ts) ; "
                                              "LICENSE (MIT, Davy45270) ; HL-538",
                                       "decision": "Icônes PWA produites par le code du dépôt : elles prennent la "
                                                   "licence du code qui les dessine, MIT (2026-11-22)."}}],
    },
    "six-de-chaque": {
        # README (depuis le socle 20e10f5) : « Art original (galets, glyphes …, motifs et icônes) : CC BY 4.0, David
        # Sevin. Dessiné pour ce jeu, aucun emprunt. » ; glyphes ajoutés par ef2edac, icônes par scripts/make-icons.js.
        "images": [{"prefixe": prefixe, "licence": "CC-BY-4.0", "auteur": "Davy45270 (README du jeu)",
                    "licence_preuve": {"method": "déclaration du titulaire",
                                       "ref": "six-de-chaque README.md, section Licences (20e10f5) ; ef2edac (glyphes) ; "
                                              "HL-538",
                                       "decision": "Art original de Six de chaque (glyphes, motifs, icônes) dessiné "
                                                   "pour le jeu par Davy45270 : CC BY 4.0."}}
                   for prefixe in ("apps/web/public/art/", "apps/web/public/icons/six-de-chaque-")],
    },
    "opencade": {"monorepo": "src/games"},
    "opencadkid": {"monorepo": "src/games"},
}
SOURCES_BRUTES = {"source", "sources"}      # dossiers de planches brutes : ni livrés, ni employés
IMAGES = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".svg", ".avif")


# --- Empreinte de pixels : MÊME définition que la barrière P17 (homelab-diag arcade-lab/qualite-jeu.py) ---------------

def empreinte_pixels(im):
    """RGBA rogné à la boîte des pixels opaques, RGB des pixels transparents mis à 0, dimensions comprises."""
    import numpy as np
    a = np.asarray(im.convert("RGBA")).copy()
    a[a[..., 3] == 0] = 0
    ys, xs = np.nonzero(a[..., 3])
    if not len(xs):
        return "vide"
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return hashlib.sha256(f"{a.shape[1]}x{a.shape[0]}|".encode() + a.tobytes()).hexdigest()


def cadres_d_atlas(image, frames):
    """[(nom, PIL)] des cadres d'un atlas TexturePacker/Phaser (hash ou tableau ; `rotated` restitué)."""
    items = frames.items() if isinstance(frames, dict) else ((f.get("filename"), f) for f in frames if isinstance(f, dict))
    out = []
    for nom, f in items:
        r = (f or {}).get("frame") or {}
        try:
            x, y, w, h = (int(r[k]) for k in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError):
            continue
        c = image.crop((x, y, x + (h if f.get("rotated") else w), y + (w if f.get("rotated") else h)))
        if f.get("rotated"):
            c = c.rotate(90, expand=True)
        out.append((str(nom), c))
    return out


# --- Outils ------------------------------------------------------------------------------------------------------

def sh(*cmd, cwd=None, ok=(0,)):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode not in ok:
        raise SystemExit(f"{' '.join(map(str, cmd))[:200]} → {r.returncode}\n{r.stdout[-1500:]}\n{r.stderr[-800:]}")
    return r


def assetctl(*args):
    r = sh(ASSETCTL, *args, "--json", cwd=REG)
    return json.loads(r.stdout)


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def lire(p):
    return json.loads(Path(p).read_text())


def ecrire_si_change(p, doc, compte):
    if not Path(p).exists() or lire(p) != doc:
        write_json(Path(p), doc)
        compte["fiches_ecrites"] += 1


def mots(texte):
    return " ".join(re.findall(r"[a-z0-9]+", texte.lower())) or "cadre"


# --- Lecture du jeu au commit ---------------------------------------------------------------------------------------

def cloner(jeu, sha, depot, travail):
    if depot is None:
        sources = lire(REG / "catalog/sources.json")["sources"]
        entree = next((s for s in sources if s["name"] == jeu), None)
        if entree is None:
            raise SystemExit(f"{jeu} absent de catalog/sources.json : dépôt non autorisé.")
        locale = next((c for c in entree.get("copies") or [] if c.get("provider") == "local"), None)
        depot = Path(locale.get("path") or locale.get("url")) if locale else None
        if depot is None:
            raise SystemExit(f"{jeu} : aucune copie locale ; passer --depot.")
    clone = travail / f"{jeu}-{sha[:12]}"
    if not clone.exists():
        sh("git", "clone", "-q", "--no-local", "--no-checkout", str(depot), str(clone))
    complet = sh("git", "rev-parse", "--verify", f"{sha}^{{commit}}", cwd=clone).stdout.strip()
    sh("git", "checkout", "-q", "--force", complet, cwd=clone)
    return clone, complet


def portee(jeu, profil, fichiers):
    """Prédicat « ce fichier appartient au jeu » : tout le dépôt, ou le sous-dossier du jeu dans un monorepo."""
    racine = profil.get("monorepo")
    if not racine:
        return lambda f: True
    sous = {PurePosixPath(f).parts[len(PurePosixPath(racine).parts)] for f in fichiers
            if f.startswith(racine + "/") and len(PurePosixPath(f).parts) > len(PurePosixPath(racine).parts) + 1}
    if "/" in jeu:
        g = jeu.split("/", 1)[1]
        if g not in sous:
            raise SystemExit(f"{jeu} : aucun dossier {racine}/{g}/ au commit.")
        return lambda f: f.startswith(f"{racine}/{g}/")
    return lambda f: not any(f.startswith(f"{racine}/{g}/") for g in sous)


IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*)['"](?P<chemin>\.{1,2}/[^'"]+)['"]""")
HORS_LIVRAISON = ("tests/", "test/", "docs/", "scripts/", "tools/", "e2e/")


def modules_de_dessin(clone, fichiers, dans):
    """Modules qui dessinent l'image du jeu (détection DRAW du scan) : ceux du jeu, et ceux qu'il importe, de proche en
    proche par chemins relatifs (un jeu d'un monorepo dessine aussi par les modules partagés de la coquille)."""
    connus = set(fichiers)
    code = lambda f: PurePosixPath(f).suffix[1:] in CODE and ".test." not in f and ".spec." not in f \
        and "node_modules/" not in f and not f.startswith(HORS_LIVRAISON) and not f.endswith(".d.ts")
    texte = {}

    def lire_code(f):
        if f not in texte:
            texte[f] = (clone / f).read_text(encoding="utf-8-sig", errors="replace")
        return texte[f]

    def resoudre(depuis, rel):
        base = PurePosixPath(depuis).parent
        parts = []
        for x in (base / rel).parts:
            if x == "..":
                if parts:
                    parts.pop()
            elif x != ".":
                parts.append(x)
        cible = "/".join(parts)
        for c in (cible, *(cible + s for s in (".ts", ".tsx", ".js", ".mjs", "/index.ts", "/index.js"))):
            if c in connus and code(c):
                return c
        if cible.endswith(".js") and cible[:-3] + ".ts" in connus:
            return cible[:-3] + ".ts"
        return None

    a_voir = [f for f in fichiers if dans(f) and code(f)]
    vus = set(a_voir)
    while a_voir:
        f = a_voir.pop()
        for m in IMPORT.finditer(lire_code(f)):
            c = resoudre(f, m["chemin"])
            if c and c not in vus:
                vus.add(c)
                a_voir.append(c)
    return sorted(f for f in vus if DRAW.search(lire_code(f)))


def atlas_livres(clone, dans=lambda f: True):
    """[{json, image, cadres: [(nom, PIL, empreinte)]}] : même découverte que P17 (tout JSON à `frames` du commit)."""
    from PIL import Image
    fichiers = sh("git", "ls-files", cwd=clone).stdout.split()
    connus, out = set(fichiers), []
    for f in fichiers:
        if not f.endswith(".json") or "node_modules/" in f or not dans(f):
            continue
        try:
            doc = json.loads((clone / f).read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        pages = [doc] if doc.get("frames") else [t for t in doc.get("textures") or [] if isinstance(t, dict)]
        for page in pages:
            nom_img = page.get("image") or (doc.get("meta") or {}).get("image")
            cand = [PurePosixPath(f).parent / nom_img] if nom_img else []
            cand += [PurePosixPath(f).with_suffix(s) for s in (".png", ".webp")]
            img = next((str(c) for c in cand if str(c) in connus), None)
            if img is None or not page.get("frames"):
                continue
            with Image.open(clone / img) as im:
                im.load()
                cadres = [(n, c, empreinte_pixels(c)) for n, c in cadres_d_atlas(im, page["frames"])]
            lignes = (clone / f).read_text().splitlines()
            out.append({"json": f, "image": img, "cadres": cadres,
                        "ligne": {n: next((i + 1 for i, l in enumerate(lignes) if f'"{n}"' in l), 1) for n, _, _ in cadres}})
    return out


# --- Registre ------------------------------------------------------------------------------------------------------

def charger_registre():
    from PIL import Image
    fiches, par_empreinte, par_octets = {}, {}, {}
    for p in sorted((REG / "catalog/assets").glob("*.json")):
        a = lire(p)
        fiches[a["id"]] = a
        par_octets.setdefault(a["sha256"].lower(), []).append(a["id"])
        chemin = (a.get("files") or {}).get("registry")
        if chemin and (REG / chemin).is_file() and a["family"]["type"] in ("sprite", "image"):
            try:
                with Image.open(REG / chemin) as im:
                    par_empreinte.setdefault(empreinte_pixels(im), []).append(a["id"])
            except OSError:
                pass
    return fiches, par_empreinte, par_octets


def tables_des_atlas(clone, profil):
    """{atlas (stem) → (chemin de la table au commit, nom de la table, table, SHA-256)} : d'où vient chaque cadre."""
    out = {}
    if profil.get("parents") == "manifestes":       # manifestes {source: table de découpe, frames: atlas}
        for m in sorted(clone.glob(profil["manifestes"])):
            d = lire(m)
            if not d.get("source") or not d.get("frames"):
                continue
            table = clone / d["source"]
            out[PurePosixPath(d["frames"]).stem] = (d["source"], PurePosixPath(d["source"]).name, lire(table),
                                                   sha256(table.read_bytes()))
    elif profil.get("parents") == "provenance":     # un fichier de provenance par dessin → une table par atlas
        chemin = clone / profil["provenance"]
        par_atlas = {}
        for e in lire(chemin):
            o = e.get("origine")
            if not isinstance(o, dict) or not e.get("atlas") or not o.get("boite"):
                continue
            t = par_atlas.setdefault(e["atlas"], {"planche": o["planche"], "elements": []})
            if t["planche"] != o["planche"]:
                raise SystemExit(f"{profil['provenance']} : l'atlas {e['atlas']} mêle deux planches.")
            t["elements"].append({"id": e["id"], "boite": o["boite"], "marge": o.get("marge", 0),
                                  "transformations": o.get("transformations") or []})
        empreinte = sha256(chemin.read_bytes())
        for atlas, t in par_atlas.items():
            out[atlas] = (profil["provenance"], f"{atlas}.provenance.json", t, empreinte)
    elif profil.get("parents") == "inventaire":     # inventaire du jeu : atlas → table de découpe
        for f in lire(clone / profil["inventaire"]).get("fichiers") or []:
            if f.get("type") != "atlas" or not str(f.get("chemin", "")).endswith(".json") or not f.get("decoupe"):
                continue
            table = clone / f["decoupe"]
            if table.is_file():
                out[PurePosixPath(f["chemin"]).stem] = (f["decoupe"], PurePosixPath(f["decoupe"]).name, lire(table),
                                                        sha256(table.read_bytes()))
    return out


def brut_de(fiches, table_nom, element, boite=None, planche_sha=None):
    """Asset brut (découpe de la planche) du même élément de la même table. À défaut, quand la boîte et la planche
    sont données : la découpe brute du même élément, à la même boîte, de la même planche, importée par une autre
    table du jeu (deux atlas qui reprennent le même dessin — l'import-sheet refuse un doublon d'octets)."""
    def brute(a):
        return ((a.get("family") or {}).get("sprite") or {}).get("frameName") == element \
            and a["provenance"]["type"] == "original-sheet-cut"
    ids = [i for i, a in fiches.items()
           if brute(a)
           and (str((a.get("sourceRegion") or {}).get("evidence", "")).startswith(
               (f"{table_nom} ·", f"{PurePosixPath(table_nom).stem}.{element}.decoupe.json ·"))
                or re.match(re.escape(PurePosixPath(table_nom).stem) + r"\.lot-[0-9a-f]{12}\.decoupe\.json · ",
                            str((a.get("sourceRegion") or {}).get("evidence", ""))))]
    if not ids and isinstance(boite, (list, tuple)) and len(boite) == 4 and planche_sha:
        w, h, x, y = boite
        ids = [i for i, a in fiches.items()
               if brute(a) and [(a.get("sourceRegion") or {}).get(k) for k in "whxy"] == [w, h, x, y]
               and str((a.get("sourceRegion") or {}).get("evidence", "")).endswith(f"· planche {planche_sha}")]
    return sorted(ids)[0] if ids else None


def importer_bruts(jeu, sha, profil, table_rel, nom, table, elements, recus, compte):
    """Éléments sans découpe brute au registre : UN `assetctl import-sheet` par table, réduite à ces éléments (boîtes du
    jeu reprises telles quelles, sans redécoupe), puis chaque fiche reçoit la licence et l'auteur du profil du jeu.
    Rend {élément: assetId}."""
    planche = Path(profil["planches"]).expanduser() / table["planche"]
    garde = [{k: v for k, v in e.items() if k != "transformations"} for e in table["elements"] if e["id"] in elements]
    reduite = {**table, "elements": garde, "planche_sha256": sha256(planche.read_bytes())}
    texte = json.dumps(reduite, ensure_ascii=False, indent=1) + "\n"
    lot = sha256(texte.encode())[:12]
    copie = REG / "sources/editable" / f"{jeu.replace('/', '-')}-livre" / f"{PurePosixPath(nom).stem}.lot-{lot}.decoupe.json"
    copie.parent.mkdir(parents=True, exist_ok=True)
    copie.write_text(texte)
    avant = {f.name for f in (REG / "catalog/assets").glob("*.json")}
    d = assetctl("import-sheet", str(planche), "--decoupe", str(copie))
    out = {}
    for e, r in zip(garde, d["assets"]):
        element, aid = e["id"], r["assetId"]
        p = REG / "catalog/assets" / f"{aid}.json"
        if p.name in avant:
            raise SystemExit(f"import-sheet : {element} rendu sur la fiche existante {aid} (doublon d'octets) ; "
                             "elle n'est pas réécrite. Chercher la découpe par boîte et planche (brut_de).")
        a = lire(p)
        if (a.get("family") or {}).get("sprite", {}).get("frameName") != element:
            raise SystemExit(f"import-sheet : {aid} n'est pas l'élément {element} (ordre des résultats inattendu).")
        ev = f"{jeu}@{sha[:12]}:{table_rel} · élément {element} ; copie {copie.relative_to(REG)} (SHA-256 {sha256(copie.read_bytes())})"
        a["description"] = f"{jeu} — élément « {element} » de la table {nom} (planche {table['planche']}) : découpe brute"
        a["tags"] = list(dict.fromkeys([profil["univers"], jeu, PurePosixPath(nom).stem.split(".")[0]]))
        for champ in ("description", "tags"):
            a.setdefault("inference", {})[champ] = {"method": "proven", "confidence": 1, "evidence": [ev]}
        a["originUniverse"] = profil["univers"]
        a["inference"]["originUniverse"] = {"method": "proven", "confidence": 1, "evidence": [f"{table['planche']} · planche du jeu"]}
        a["license"], a["licenseEvidence"] = profil["licence"], profil["licence_preuve"]
        a["provenance"].update(type="original-sheet-cut", author=profil["auteur"])
        a["provenance"]["evidence"] = [a["provenance"]["evidence"][0], ev]
        recu = recus[element]
        rejets = [{"assetId": c, "reason": f"pas la découpe de l'élément {element} de {nom} (autre élément ou autre boîte)"}
                  for c in recu["results"]]
        a["creation"] = {"searchReceipt": {**recu, "rejectedCandidates": rejets}, "rejectedCandidates": rejets}
        write_json(p, a)
        compte["bruts_importes"] += 1
        out[element] = aid
    return out


def recu_motive(requete, jeu, motifs, travail, n):
    """Recherche avec reçu ; chaque candidat reçoit son motif de rejet MESURÉ (rend la liste des --reject)."""
    recu = travail / f"recu-{n}.json"
    assetctl("search", requete, "--tag", jeu, "--receipt", str(recu))
    rejets = []
    for cand in lire(recu)["results"]:
        rejets += ["--reject", f"{cand}:{motifs(cand)}"]
    return recu, rejets


def enregistrer(nom, png, recu, rejets):
    d = assetctl("register", str(png), "--name", nom, "--category", "sprite", "--receipt", str(recu), *rejets)
    return d["id"]


# --- Passe ---------------------------------------------------------------------------------------------------------

def module_connu(f, clone, fiches, par_octets):
    """(asset, version) code-generated du registre dont une version a les octets de ce module au sha, ou None."""
    d = sha256((clone / f).read_bytes())
    trouves = sorted((i, v.get("version", n + 1)) for i, a in fiches.items()
                     if (a.get("family") or {}).get("type") == "code-generated"
                     for n, v in enumerate(a.get("versions") or [{"sha256": a["sha256"]}])
                     if str(v.get("sha256", "")).lower() == d)
    return trouves[0] if trouves else None


def fournisseur(depot):
    sources = lire(REG / "catalog/sources.json")["sources"]
    entree = next((s for s in sources if s["name"] == depot), {})
    return "forgejo" if any(c.get("provider") == "forgejo" for c in entree.get("copies") or []) else "github"


def regle_image(profil, chemin, declarees=None, octets=None):
    """Provenance PROUVÉE d'une image isolée par le profil, sinon None (inconnue — jamais inventée). Une règle à
    `declaree` ne vaut que si le fichier de provenance du jeu déclare l'image (même id que son nom, ou son chemin),
    avec une origine admise et les champs que la règle `exige`. Un SHA-256 déclaré doit être celui des octets livrés.
    La règle porte alors la référence de cette entrée, et l'auteur qu'elle déclare."""
    for r in profil.get("images") or ():
        if not chemin.startswith(r["prefixe"]):
            continue
        if not r.get("declaree"):
            return r
        e = (declarees or {}).get(chemin) or (declarees or {}).get(PurePosixPath(chemin).stem)
        if not e or e.get("origine") not in r["origines"] or not all(e.get(c) for c in r.get("exige", ())):
            return None
        if r.get("licence_declaree") and e.get("licence") != r["licence_declaree"]:
            return None
        if r.get("titulaire") and e.get("titulaire") != r["titulaire"]:
            return None
        if e.get("sha256") and (octets is None or e["sha256"] != sha256(octets)):
            return None
        if r.get("planche_verifiee"):
            f = Path(profil.get("planches") or "/nonexistent").expanduser() / str(e.get("planche"))
            if not f.is_file() or sha256(f.read_bytes()) != e.get("planche_sha256"):
                return None
        ref = f"{e.get('declare_par') or profil['provenance_images']} · {e.get('id') or e.get('fichier')} (origine « {e['origine']} »"
        ref += f", planche {e['planche']} SHA-256 {e.get('planche_sha256')}" if e.get("planche") else ""
        ref += f", fichier SHA-256 {e['sha256']}" if e.get("sha256") else ""
        ref += ")"
        auteur = e.get("auteur") or r.get("auteur") or "unknown"
        return {**r, "auteur": auteur,
                "licence_preuve": {**r["licence_preuve"], "ref": r["licence_preuve"]["ref"] + " ; " + ref}}
    return None


def declarations_derivees(e):
    """Fichiers dérivés qu'une entrée de provenance déclare (`fichiers` d'une entrée dérivée, `derives[].fichier` d'un
    dessin), avec la planche source et son SHA-256 de l'entrée (`origine`). Origine « dérivé »."""
    if not isinstance(e, dict) or not isinstance(e.get("origine"), dict):
        return []
    o = e["origine"]
    base = {"origine": "dérivé", "planche": o.get("planche"), "planche_sha256": o.get("sha256")}
    out = [{**base, "id": e.get("id"), "fichier": f} for f in e.get("fichiers") or () if isinstance(f, str)]
    out += [{**base, "id": f"{e.get('id')} → {d['fichier']}", "fichier": d["fichier"]}
            for d in e.get("derives") or () if isinstance(d, dict) and isinstance(d.get("fichier"), str)]
    return out


def declarations_licence(clone, profil):
    """Licences déclarées par le jeu, hors provenance_images : `inventaire` (fichiers[] : chemin, sha256, licence,
    planche {fichier, sha256}) indexé par chemin ; `liste` ({titulaire, licence, assets: [id]}) indexé par id.
    Origine = format de la déclaration (« inventaire », « licences.json »)."""
    out = {}
    for d in profil.get("declarations_licence") or ():
        f = clone / d["fichier"]
        if not f.is_file():
            continue
        doc = lire(f)
        if d["format"] == "inventaire":
            for e in doc.get("fichiers") or ():
                if isinstance(e, dict) and isinstance(e.get("chemin"), str):
                    pl = e.get("planche") if isinstance(e.get("planche"), dict) else {}
                    out.setdefault(e["chemin"], {"origine": "inventaire", "fichier": e["chemin"], "declare_par": d["fichier"],
                                                 "sha256": e.get("sha256"), "licence": e.get("licence"),
                                                 "planche": pl.get("fichier"), "planche_sha256": pl.get("sha256")})
        elif d["format"] == "liste":
            for i in doc.get("assets") or ():
                if isinstance(i, str):
                    out.setdefault(i, {"origine": "licences.json", "id": i, "declare_par": d["fichier"],
                                       "licence": doc.get("licence"), "titulaire": doc.get("titulaire")})
    return out


def tracer_derives(args, sha, profil, clone, travail, fiches, par_octets, cadres_reemployes, compte):
    """Fiche `derived` du scan sans `derivedFrom` réemployée pour un cadre livré : son parent est la source que
    provenance.json du jeu déclare au commit. Redessin (« redessiné (marque) », `svg`) : l'asset aux octets du SVG.
    Dérivé (« dérivé », `planche`, `planche_sha256`, `boite`) : la découpe brute de cette boîte de cette planche
    (planche vérifiée par SHA-256), importée si absente. Sans source prouvée : la fiche reste telle quelle."""
    if not profil.get("provenance_derives") or not (clone / profil["provenance_derives"]).is_file():
        return
    doc = lire(clone / profil["provenance_derives"])
    prov = {e["id"]: e for e in (doc.get("assets") if isinstance(doc, dict) else doc) or [] if isinstance(e, dict) and e.get("id")}
    a_tracer, bruts = {}, {}
    for cadre, aid in cadres_reemployes:
        p = fiches[aid].get("provenance") or {}
        if p.get("type") != "derived" or aid in a_tracer:
            continue
        if p.get("derivedFrom"):
            # Déjà tracé : seule la licence d'un SVG parent encore inconnue est (r)établie.
            par = fiches.get(p["derivedFrom"]) or {}
            src = (prov.get(cadre.rsplit("#", 1)[1]) or {}).get("svg")
            if src and par.get("license") in (None, "", "unknown") and profil.get("regle_sources") and \
                    appliquer_regle(p["derivedFrom"], profil["regle_sources"], fiches, args.jeu.split("/")[0], src):
                compte["licences_etablies"] += 1
            continue
        nom = cadre.rsplit("#", 1)[1]
        e = prov.get(nom) or {}
        if e.get("origine") == "redessiné (marque)" and e.get("svg") and (clone / e["svg"]).is_file():
            ids = par_octets.get(sha256((clone / e["svg"]).read_bytes())) or []
            if ids:
                parent = sorted(ids)[0]
                if fiches[parent].get("license") in (None, "", "unknown") and profil.get("regle_sources") and \
                        appliquer_regle(parent, profil["regle_sources"], fiches, args.jeu.split("/")[0], e["svg"]):
                    compte["licences_etablies"] += 1
                a_tracer[aid] = (cadre, nom, parent, f"redessin : rendu de {e['svg']} (provenance.json)")
        elif e.get("origine") == "dérivé" and e.get("planche") and e.get("planche_sha256") and e.get("boite"):
            planche = Path(profil["planches"]).expanduser() / e["planche"]
            if not planche.is_file() or sha256(planche.read_bytes()) != e["planche_sha256"]:
                continue
            tnom = f"{PurePosixPath(e['planche']).stem}.provenance-derives.json"
            parent = brut_de(fiches, tnom, nom, e["boite"], e["planche_sha256"])
            if parent:
                a_tracer[aid] = (cadre, nom, parent, f"dérivé : boîte {e['boite']} de {e['planche']} (provenance.json)")
            else:
                bruts.setdefault(e["planche"], {})[nom] = (aid, cadre, e)
    for planche, elements in sorted(bruts.items()):
        tnom = f"{PurePosixPath(planche).stem}.provenance-derives.json"
        table = {"planche": planche, "elements": [{"id": nom, "boite": e["boite"], "marge": 0}
                                                  for nom, (_, _, e) in sorted(elements.items())]}
        recus = {}
        for nom in sorted(elements):
            compte["n"] = compte.get("n", 0) + 1
            recu, _ = recu_motive(mots(nom), args.jeu, lambda c: "", travail, f"brut-derive-{compte['n']}")
            recus[nom] = lire(recu)
        for nom, parent in importer_bruts(args.jeu, sha, profil, profil["provenance_derives"], tnom, table,
                                          set(elements), recus, compte).items():
            fiches[parent] = lire(REG / "catalog/assets" / f"{parent}.json")
            aid, cadre, e = elements[nom]
            a_tracer[aid] = (cadre, nom, parent, f"dérivé : boîte {e['boite']} de {planche} (provenance.json)")
    for aid, (cadre, nom, parent, raison) in sorted(a_tracer.items()):
        compte["n"] = compte.get("n", 0) + 1

        def motif(c, parent=parent):
            return f"source du cadre {nom} : {raison} (parent derivedFrom)" if c == parent \
                else f"autre asset : pixels différents du cadre livré {cadre}"
        recu, _ = recu_motive(mots(nom), args.jeu, motif, travail, f"derive-{compte['n']}")
        r = lire(recu)
        rejets = [{"assetId": c, "reason": motif(c)} for c in r["results"]]
        a, pa = lire(REG / "catalog/assets" / f"{aid}.json"), fiches[parent]
        a["provenance"].update(derivedFrom=parent, parentId=parent, parentVersion=pa.get("version", 1),
                               parentSha256=pa["sha256"])
        a["provenance"]["evidence"] = list(dict.fromkeys([*(a["provenance"].get("evidence") or []),
                                                          f"{MARQUE} : cadre {cadre} de {args.jeu}@{sha} ; {raison}"]))
        a.setdefault("creation", {})["searchReceipt"] = {**r, "rejectedCandidates": rejets}
        a["creation"]["rejectedCandidates"] = rejets
        write_json(REG / "catalog/assets" / f"{aid}.json", a)
        fiches[aid] = a
        if aid not in (pa.get("variants") or []):
            pa["variants"] = sorted({*(pa.get("variants") or []), aid})
            write_json(REG / "catalog/assets" / f"{parent}.json", pa)
        compte["derives_traces"] = compte.get("derives_traces", 0) + 1
    compte.pop("n", None)


def materialiser(aid, octets, fiches, compte):
    """Fiche réemployée par octets sans fichier au registre (le scan ne copie pas les images) : ses octets y sont
    déposés à l'emplacement que `register` emploierait (sprites/<id>.<format>), pour que ses PIXELS soient connus
    (critère (a) de P17). Seulement si le SHA-256 est bien celui de la fiche ; jamais une fiche qui a déjà un fichier."""
    a = fiches[aid]
    if (a.get("files") or {}).get("registry") or a.get("sha256") != sha256(octets) or a.get("format") != "png":
        return False
    relatif = f"sprites/{aid}.png"
    (REG / relatif).write_bytes(octets)
    doc = lire(REG / "catalog/assets" / f"{aid}.json")
    doc.setdefault("files", {"locations": []})["registry"] = relatif
    write_json(REG / "catalog/assets" / f"{aid}.json", doc)
    fiches[aid] = doc
    compte["materialises"] = compte.get("materialises", 0) + 1
    return True


def appliquer_regle_cadre(aid, regle, fiches, depot):
    """Cadre réemployé dont la fiche (du scan) est sans licence : la licence déclarée pour l'identifiant du cadre
    n'est établie que si la fiche n'est employée que par ce dépôt (aucune fiche partagée avec un autre jeu)."""
    p = REG / "catalog/assets" / f"{aid}.json"
    a = lire(p)
    if a.get("license") not in (None, "", "unknown") or not a.get("usages") or any(
            u.get("repo") != depot for u in a["usages"]):
        return False
    a["license"], a["licenseEvidence"] = regle["licence"], regle["licence_preuve"]
    a.setdefault("provenance", {})["author"] = regle["auteur"]
    write_json(p, a)
    fiches[aid] = a
    return True


def appliquer_regle(aid, regle, fiches, depot, chemin):
    """Image déjà au registre en licence inconnue, dont la provenance est désormais prouvée : la licence, sa preuve et
    l'auteur sont établis. Seulement pour une fiche `repo-file` de CE fichier de CE dépôt (marque de l'importeur, ou
    preuve du scan `<dépôt>@<commit>:<chemin>`) : une fiche d'une autre origine n'est pas touchée. Le scan remet la
    licence à unknown si les octets changent (nouvelle version), ce qui est voulu : la preuve vaut pour ces octets."""
    p = REG / "catalog/assets" / f"{aid}.json"
    a = lire(p)
    prov = a.get("provenance") or {}
    if prov.get("type") != "repo-file" or not any(
            MARQUE in ev or (ev.startswith(f"{depot}@") and ev.endswith(f":{chemin}")) for ev in prov.get("evidence") or ()):
        return False
    a["license"], a["licenseEvidence"] = regle["licence"], regle["licence_preuve"]
    a["provenance"]["author"] = regle["auteur"]
    write_json(p, a)
    fiches[aid] = a
    return True


def enregistrer_brut_du_jeu(args, sha, profil, chemin, octets, categorie, travail, n, fiches, par_octets, compte,
                            declarees=None):
    """Image livrée (ou cadre sans table de découpe) inconnue du registre : register, provenance repo-file."""
    regle = regle_image(profil, chemin, declarees, octets) if categorie != "sprite" else None
    regle = regle or ({"licence": profil["licence"], "licence_preuve": profil["licence_preuve"], "auteur": profil["auteur"]}
                      if categorie == "sprite" and profil.get("licence") else None)
    fichier = travail / f"image-{n}{PurePosixPath(chemin).suffix if categorie != 'sprite' else '.png'}"
    fichier.write_bytes(octets)
    recu, rejets = recu_motive(mots(PurePosixPath(chemin).stem), args.jeu,
                               lambda c: "autre image : octets ou pixels différents de l'image livrée", travail, n)
    aid = assetctl("register", str(fichier), "--name", f"{args.jeu} {PurePosixPath(chemin).stem}",
                   "--category", categorie, "--receipt", str(recu), *rejets)["id"]
    p = REG / "catalog/assets" / f"{aid}.json"
    a = lire(p)
    a["provenance"] = {"type": "repo-file", "author": (regle or {}).get("auteur", "unknown"),
                       "evidence": [f"{MARQUE} : {chemin} livré par {args.jeu}@{sha}"]}
    if regle:
        a["license"], a["licenseEvidence"] = regle["licence"], regle["licence_preuve"]
    else:
        a["license"] = "unknown"
        a.pop("licenseEvidence", None)
        compte["sans_origine"].append(chemin)
    a["description"] = f"{args.jeu} — {chemin} livré par le jeu"
    a["tags"] = list(dict.fromkeys([profil.get("univers") or args.jeu.split("/")[0], args.jeu, "livre"]))
    ev = f"{args.jeu}@{sha[:12]}:{chemin}"
    for champ in ("description", "tags"):
        a.setdefault("inference", {})[champ] = {"method": "proven", "confidence": 1, "evidence": [ev]}
    write_json(p, a)
    fiches[aid] = a
    return aid


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("jeu", help="<dépôt> ou, dans un monorepo, <dépôt>/<sous-dossier du jeu>")
    ap.add_argument("sha")
    ap.add_argument("--depot", help="chemin local ou URL du dépôt (défaut : copie locale de catalog/sources.json)")
    ap.add_argument("--travail", type=Path)
    ap.add_argument("--lock", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verifier", action="store_true",
                    help="sans rien écrire : le jeu est-il relié ? (chaque cadre, image et module de dessin livré au sha "
                         "a un asset du registre dont l'index d'usage cite CE jeu à CE sha)")
    args = ap.parse_args(argv)
    depot_nom = args.jeu.split("/", 1)[0]
    profil = PROFILS.get(depot_nom, {})
    if "/" in args.jeu and not profil.get("monorepo"):
        raise SystemExit(f"{args.jeu} : {depot_nom} n'est pas déclaré monorepo dans PROFILS.")
    travail = args.travail or Path(tempfile.mkdtemp(prefix="importer-livre-"))
    travail.mkdir(parents=True, exist_ok=True)
    clone, sha = cloner(depot_nom, args.sha, args.depot, travail)
    fichiers = sh("git", "ls-files", cwd=clone).stdout.split()
    dans = portee(args.jeu, profil, fichiers)
    atlas = atlas_livres(clone, dans)
    images_atlas = {a["image"] for a in atlas}
    isolees = sorted(f for f in fichiers if f.lower().endswith(IMAGES) and dans(f) and f not in images_atlas
                     and "node_modules/" not in f and not f.startswith(("docs/", "tests/"))
                     and not SOURCES_BRUTES & set(PurePosixPath(f).parts[:-1]))
    racine = profil.get("monorepo")
    # un module d'un AUTRE jeu du monorepo, atteint par import (la coquille importe tous les jeux), n'est pas à celui-ci
    modules = [f for f in modules_de_dessin(clone, fichiers, dans) if dans(f) or not (racine and f.startswith(racine + "/"))]
    tables = tables_des_atlas(clone, profil)
    fiches, par_empreinte, par_octets = charger_registre()
    compte = {"atlas": len(atlas), "cadres": sum(len(a["cadres"]) for a in atlas), "cadres_distincts": 0,
              "reemployes": 0, "enregistres": 0, "bruts_importes": 0, "atlas_enregistres": 0,
              "images": len(isolees), "images_enregistrees": 0, "modules_dessin": len(modules),
              "modules_hors_registre": [], "usages": 0, "fiches_ecrites": 0, "sans_origine": [], "licences_etablies": 0}
    if args.verifier:
        index = lire(REG / "generated/usage-index.json").get("byAsset") or {}
        employe = lambda ids: any(u.get("game") == args.jeu and u.get("commit") == sha and u.get("status") == "active"
                                  for i in ids for u in index.get(i, ()))
        manque = [f"cadre {at['image']}#{nom}" for at in atlas for nom, _, e in at["cadres"]
                  if not employe(par_empreinte.get(e, ()))]
        manque += [f"image {f}" for f in isolees if not employe(par_octets.get(sha256((clone / f).read_bytes()), ()))]
        manque += [f"module {f}" for f in modules if not employe([m[0]] if (m := module_connu(f, clone, fiches, par_octets)) else [])]
        print(json.dumps({"jeu": args.jeu, "sha": sha, "relie": not manque, "cadres": compte["cadres"],
                          "images": len(isolees), "modules": len(modules), "manquants": manque}, ensure_ascii=False))
        return 0 if not manque else 1
    if args.dry_run:
        manquants = {e for a in atlas for _, _, e in a["cadres"] if e not in par_empreinte}
        inconnues = [f for f in isolees if not par_octets.get(sha256((clone / f).read_bytes()))]
        compte["modules_hors_registre"] = [f for f in modules if not module_connu(f, clone, fiches, par_octets)]
        print(json.dumps({**compte, "a_enregistrer": len(manquants), "images_a_enregistrer": len(inconnues)},
                         ensure_ascii=False))
        return 0

    # 1 a. découpes brutes manquantes : un import-sheet par table (un import par élément coûte ~1 min chacun)
    besoins, vus, prevus = {}, set(), set()
    planches_sha = {}

    def sha_planche(table):
        nom_p = table["planche"]
        if nom_p not in planches_sha:
            f = Path(profil.get("planches") or "/nonexistent").expanduser() / nom_p
            planches_sha[nom_p] = sha256(f.read_bytes()) if f.is_file() else None
        return planches_sha[nom_p]
    for at in atlas:
        stem = PurePosixPath(at["json"]).stem
        for nom, _, emp in at["cadres"]:
            if emp in vus or par_empreinte.get(emp) or not profil.get("parents") or stem not in tables:
                continue
            vus.add(emp)
            _, table_nom, table, _ = tables[stem]
            element = nom[len(profil["prefixe_cadre"]):] if nom.startswith(profil["prefixe_cadre"]) else nom
            entree = next((e for e in table["elements"] if e["id"] == element), None)
            if entree is None:
                continue
            cle = (table["planche"], element, str(entree["boite"]))
            if cle in prevus or brut_de(fiches, table_nom, element, entree["boite"], sha_planche(table)):
                continue
            prevus.add(cle)
            besoins.setdefault(stem, set()).add(element)
    n = 0
    for stem, elements in sorted(besoins.items()):
        table_rel, table_nom, table, _ = tables[stem]
        recus = {}
        for element in sorted(elements):
            n += 1
            recu_brut, _ = recu_motive(mots(element), args.jeu, lambda c: "", travail, f"brut-{n}")
            recus[element] = lire(recu_brut)
        for element, aid in importer_bruts(args.jeu, sha, profil, table_rel, table_nom, table, elements, recus,
                                           compte).items():
            fiches[aid] = lire(REG / "catalog/assets" / f"{aid}.json")

    # 1. un asset par cadre distinct
    cible = {}
    cadres_reemployes = []      # (cadre, asset) réemployés par octets : leur licence se juge après 2 bis
    for at in atlas:
        stem = PurePosixPath(at["json"]).stem
        for nom, image, emp in at["cadres"]:
            if emp in cible:
                continue
            if par_empreinte.get(emp):
                # Un atlas d'un seul cadre a les pixels de ce cadre : l'asset du cadre passe avant celui de l'atlas,
                # sinon le second passage déplacerait l'usage (non idempotent).
                cible[emp] = min(par_empreinte[emp], key=lambda i: (fiches[i].get("category") == "atlas", i))
                cadres_reemployes.append((f"{at['image']}#{nom}", cible[emp]))
                compte["reemployes"] += 1
                continue
            n += 1
            table_rel, table_nom, table, sha_table = tables.get(stem, (None, None, {"elements": []}, None))
            element = nom[len(profil.get("prefixe_cadre", "")):] if nom.startswith(profil.get("prefixe_cadre", "")) else nom
            entree = next((e for e in table["elements"] if e["id"] == element), None)
            if not profil.get("parents") or (entree is None and profil.get("sans_element")):
                # Aucune découpe connue pour ce cadre : il est enregistré tel que livré (repo-file).
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                deja = par_octets.get(sha256(buf.getvalue()))
                if deja:
                    # Mêmes octets qu'une fiche sans fichier au registre (le scan n'a pas matérialisé l'image : pas
                    # d'empreinte de pixels) : réemploi, comme en 2 bis ; register la refuserait (« déjà enregistré »).
                    cible[emp] = min(deja, key=lambda i: (fiches[i].get("category") == "atlas", i))
                    materialiser(cible[emp], buf.getvalue(), fiches, compte)
                    par_empreinte.setdefault(emp, []).append(cible[emp])
                    cadres_reemployes.append((f"{at['image']}#{nom}", cible[emp]))
                    compte["reemployes"] += 1
                    continue
                aid = enregistrer_brut_du_jeu(args, sha, profil, f"{at['image']}#{nom}", buf.getvalue(), "sprite",
                                              travail, n, fiches, par_octets, compte)
                cible[emp] = aid
                par_empreinte.setdefault(emp, []).append(aid)
                compte["enregistres"] += 1
                continue
            if stem not in tables:
                raise SystemExit(f"{at['json']} : aucune table de découpe ; parent inconnu.")
            if entree is None:
                raise SystemExit(f"{at['json']} : cadre {nom} absent de {table_rel}.")
            parent = brut_de(fiches, table_nom, element, entree["boite"], sha_planche(table))
            if parent is None:
                raise SystemExit(f"{at['json']} : découpe brute de {element} introuvable après import.")
            png = travail / f"cadre-{n}.png"
            image.save(png, format="PNG")
            region = {k: (fiches[parent].get("sourceRegion") or {}).get(k) for k in ("x", "y", "w", "h")}

            def motif(c, parent=parent):
                if c == parent:
                    return f"découpe brute de l'élément {element} : le jeu livre le cadre normalisé (parent derivedFrom)"
                return f"pixels différents du cadre livré {nom} (empreinte {emp[:12]})"
            recu, rejets = recu_motive(mots(element), args.jeu, motif, travail, n)
            aid = enregistrer(f"{args.jeu} {element} (cadre livré)", png, recu, rejets)
            p = REG / "catalog/assets" / f"{aid}.json"
            a, pa = lire(p), fiches[parent]
            parametres = {k: table.get(k) for k in ("taille", "marge", "detoure", "modele", "unique") if k in table}
            parametres.update({k: entree[k] for k in ("marge", "transformations") if entree.get(k)})
            recette = {"table": f"{args.jeu}@{sha}:{table_rel}", "tableSha256": sha_table, "element": element,
                       "boite": entree.get("boite"), "regionDuBrut": region, "parametres": parametres,
                       "atlas": f"{at['image']} ({PurePosixPath(at['image']).suffix[1:]})", "cadre": nom,
                       "empreintePixels": emp}
            a["provenance"] = {"type": "derived", "derivedFrom": parent, "parentId": parent,
                               "parentVersion": pa.get("version", 1), "parentSha256": pa["sha256"],
                               "author": pa["provenance"]["author"],
                               "evidence": [f"{MARQUE} : cadre {nom} livré par {args.jeu}@{sha} dans {at['image']}",
                                            "recette " + json.dumps(recette, ensure_ascii=False, sort_keys=True)]}
            a["license"], a["licenseEvidence"] = pa["license"], pa.get("licenseEvidence")
            if a["licenseEvidence"] is None:
                a.pop("licenseEvidence")
            a["description"] = f"{args.jeu} — cadre livré « {nom} » ({at['image']}), forme normalisée par le jeu de l'élément {element}"
            a["tags"] = list(dict.fromkeys([profil["univers"], args.jeu, PurePosixPath(table_nom).stem, "cadre-livre"]))
            ev = f"{args.jeu}@{sha[:12]}:{at['json']} · cadre {nom}"
            for champ in ("description", "tags"):
                a.setdefault("inference", {})[champ] = {"method": "proven", "confidence": 1, "evidence": [ev]}
            if pa.get("originUniverse"):
                a["originUniverse"] = pa["originUniverse"]
                a["inference"]["originUniverse"] = {"method": "proven", "confidence": 1, "evidence": [f"parent {parent}"]}
            write_json(p, a)
            fiches[aid] = a
            if aid not in pa["variants"]:
                pa["variants"] = sorted({*pa["variants"], aid})
                write_json(REG / "catalog/assets" / f"{parent}.json", pa)
            cible[emp] = aid
            par_empreinte.setdefault(emp, []).append(aid)
            compte["enregistres"] += 1
    compte["cadres_distincts"] = len(cible)

    # 2. les images d'atlas livrées (ce que le assets.lock.json du jeu cite)
    atlas_ids = {}
    for at in atlas:
        brut = (clone / at["image"]).read_bytes()
        d = sha256(brut)
        if par_octets.get(d):
            atlas_ids[at["image"]] = sorted(par_octets[d])[0]
            continue
        n += 1
        licences = {fiches[cible[e]]["license"] for _, _, e in at["cadres"]}
        recu, rejets = recu_motive(mots(PurePosixPath(at["image"]).stem + " atlas"), args.jeu,
                                   lambda c: "autre image : octets différents de l'atlas livré", travail, n)
        aid = assetctl("register", str(clone / at["image"]), "--name", f"{args.jeu} atlas {PurePosixPath(at['image']).stem}",
                       "--category", "atlas", "--receipt", str(recu), *rejets)["id"]
        p = REG / "catalog/assets" / f"{aid}.json"
        a = lire(p)
        sources = {fiches[cible[e]]["provenance"].get("author") for _, _, e in at["cadres"]}
        a["provenance"] = {"type": "repo-file", "author": profil.get("auteur") or (sources.pop() if len(sources) == 1 else "unknown"),
                           "evidence": [f"{MARQUE} : atlas {at['image']} livré par {args.jeu}@{sha}, cadres de {at['json']}"]}
        if len(licences) == 1:
            unique = next(iter(licences))
            src = next(fiches[cible[e]] for _, _, e in at["cadres"])
            a["license"] = unique
            if src.get("licenseEvidence"):
                a["licenseEvidence"] = src["licenseEvidence"]
        a["description"] = f"{args.jeu} — atlas livré {at['image']} ({len(at['cadres'])} cadres)"
        a["tags"] = list(dict.fromkeys([profil.get("univers") or depot_nom, args.jeu, "atlas-livre"]))
        ev = f"{args.jeu}@{sha[:12]}:{at['image']}"
        for champ in ("description", "tags"):
            a.setdefault("inference", {})[champ] = {"method": "proven", "confidence": 1, "evidence": [ev]}
        write_json(p, a)
        fiches[aid] = a
        par_octets.setdefault(d, []).append(aid)
        atlas_ids[at["image"]] = aid
        compte["atlas_enregistres"] += 1

    # 2 bis. les images livrées hors atlas : réemploi par octets, sinon enregistrement (provenance prouvée ou inconnue)
    declarees = {}
    if profil.get("provenance_images") and (clone / profil["provenance_images"]).is_file():
        doc = lire(clone / profil["provenance_images"])
        entrees = ((doc.get("assets") or []) + (doc.get("hors_atlas") or [])) if isinstance(doc, dict) else doc
        for e in entrees or []:
            for cle in (e.get("id"), e.get("source"), e.get("element"), e.get("fichier")):
                if isinstance(cle, str) and cle:
                    declarees.setdefault(cle, e)
            for derive in declarations_derivees(e):
                declarees.setdefault(derive["fichier"], derive)
    for cle, e in declarations_licence(clone, profil).items():
        declarees.setdefault(cle, e)
    image_ids = {}
    for f in isolees:
        octets = (clone / f).read_bytes()
        d = sha256(octets)
        if par_octets.get(d):
            image_ids[f] = min(par_octets[d], key=lambda i: (fiches[i].get("category") == "atlas", i))
            if fiches[image_ids[f]].get("license") in (None, "", "unknown"):
                regle = regle_image(profil, f, declarees, octets)
                if regle and appliquer_regle(image_ids[f], regle, fiches, args.jeu.split("/")[0], f):
                    compte["licences_etablies"] += 1
                elif fiches[image_ids[f]].get("license") in (None, "", "unknown"):
                    compte["sans_origine"].append(f)
            continue
        n += 1
        categorie = "icon" if "icons/" in f or "icon" in PurePosixPath(f).stem else "image"
        image_ids[f] = enregistrer_brut_du_jeu(args, sha, profil, f, octets, categorie, travail, n, fiches,
                                               par_octets, compte, declarees)
        par_octets.setdefault(d, []).append(image_ids[f])
        compte["images_enregistrees"] += 1

    tracer_derives(args, sha, profil, clone, travail, fiches, par_octets, cadres_reemployes, compte)
    regle_cadres = profil.get("cadres_declares")
    for c, aid in cadres_reemployes:
        if fiches[aid].get("license") not in (None, "", "unknown"):
            continue
        nom = c.rsplit("#", 1)[1]
        regle = regle_image({**profil, "images": [regle_cadres]}, nom, declarees) if regle_cadres else None
        if regle and appliquer_regle_cadre(aid, regle, fiches, depot_nom):
            compte["licences_etablies"] += 1
        else:
            compte["sans_origine"].append(c)

    # 2 ter. les modules qui dessinent par le code : l'asset code-generated du scan (mêmes octets au sha). register
    # refuse le code ; un module absent du registre se règle par `assetctl scan-repos` du dépôt à ce sha, d'abord.
    module_ids = {}
    for f in modules:
        trouve = module_connu(f, clone, fiches, par_octets)
        if trouve:
            module_ids[f] = trouve
        else:
            compte["modules_hors_registre"].append(f)
    if compte["modules_hors_registre"]:
        raise SystemExit(f"{len(compte['modules_hors_registre'])} module(s) de dessin absents du registre à {sha[:12]} "
                         f"(lancer scan-repos du dépôt) : {compte['modules_hors_registre'][:5]}")

    # 3. usages <jeu>@<sha> : ceux de cet outil pour ce jeu sont remplacés (idempotent, et un nouveau sha les déplace)
    base = {"repo": depot_nom, "game": args.jeu, "provider": fournisseur(depot_nom), "commit": sha, "status": "active",
            "releases": []}
    nouveaux = {}
    for at in atlas:
        for nom, _, emp in at["cadres"]:
            aid = cible[emp]
            nouveaux.setdefault(aid, []).append({
                **base, "scene": at["json"], "role": "atlas-frame", "importName": nom,
                "assetPath": at["image"], "assetVersion": fiches[aid].get("version", 1),
                "codeRef": {"path": at["json"], "line": at["ligne"][nom]},
                "evidence": [f"{MARQUE} : cadre {nom} de {at['image']} (empreinte de pixels {emp[:16]})"],
                "inference": {"role": {"method": "proven", "confidence": 1, "evidence": [f"{at['json']} · frames"]}}})
        aid = atlas_ids[at["image"]]
        nouveaux.setdefault(aid, []).append({
            **base, "scene": at["json"], "role": "atlas", "importName": PurePosixPath(at["image"]).stem,
            "assetPath": at["image"], "assetVersion": fiches[aid].get("version", 1),
            "codeRef": {"path": at["json"], "line": 1},
            "evidence": [f"{MARQUE} : image d'atlas {at['image']} livrée"],
            "inference": {"role": {"method": "proven", "confidence": 1, "evidence": [f"{at['json']} · meta.image"]}}})
    for f, aid in image_ids.items():
        role = "icon" if fiches[aid].get("category") == "icon" else "image"
        nouveaux.setdefault(aid, []).append({
            **base, "scene": f, "role": role, "importName": PurePosixPath(f).stem,
            "assetPath": f, "assetVersion": fiches[aid].get("version", 1), "codeRef": {"path": f, "line": 1},
            "evidence": [f"{MARQUE} : image {f} livrée (fichier suivi au commit)"],
            "inference": {"role": {"method": "proven", "confidence": 1, "evidence": [f"{f} · fichier livré"]}}})
    for f, (aid, version) in module_ids.items():
        nouveaux.setdefault(aid, []).append({
            **base, "scene": f, "role": "dessin-code", "importName": PurePosixPath(f).stem,
            "assetPath": f, "assetVersion": version, "codeRef": {"path": f, "line": 1},
            "evidence": [f"{MARQUE} : module {f} dessine l'image du jeu (code-generated, octets identiques au sha)"],
            "inference": {"role": {"method": "proven", "confidence": 1, "evidence": [f"{f} · motif de dessin du scan"]}}})
    cle = lambda u: (u["scene"], u["importName"], u["assetPath"], u["role"])
    for aid, a in fiches.items():
        anciens = [u for u in a.get("usages") or []
                   if u.get("game") == args.jeu and any(str(e).startswith(MARQUE) for e in u.get("evidence") or [])]
        if not anciens and aid not in nouveaux:
            continue
        garde = [u for u in a.get("usages") or [] if u not in anciens]
        doc = {**a, "usages": garde + sorted(nouveaux.get(aid, []), key=cle)}
        compte["usages"] += len(nouveaux.get(aid, []))
        ecrire_si_change(REG / "catalog/assets" / f"{aid}.json", doc, compte)
    assetctl("index", "rebuild")

    # 4. assets.lock.json du jeu (facultatif) : les fichiers livrés (images d'atlas et images isolées)
    if args.lock:
        tete = sh("git", "rev-parse", "HEAD", cwd=REG).stdout.strip()
        publie = sh("git", "merge-base", "--is-ancestor", tete, "origin/main", cwd=REG, ok=(0, 1)).returncode == 0
        if not publie or sh("git", "status", "--porcelain", "--", "catalog", cwd=REG).stdout.strip():
            raise SystemExit("--lock : le catalogue doit être celui d'un commit publié (origin/main), sans modification.")
        lignes = [{"assetId": atlas_ids[at["image"]], "assetVersion": str(fiches[atlas_ids[at["image"]]].get("version", 1)),
                   "sha256": sha256((clone / at["image"]).read_bytes()), "scene": at["json"], "role": "atlas",
                   "path": at["image"]} for at in atlas]
        lignes += [{"assetId": aid, "assetVersion": str(fiches[aid].get("version", 1)),
                    "sha256": sha256((clone / f).read_bytes()), "scene": f,
                    "role": "icon" if fiches[aid].get("category") == "icon" else "image", "path": f}
                   for f, aid in image_ids.items()]
        lock = {"schemaVersion": "1.0", "game": args.jeu, "registryCommit": tete,
                "assets": sorted(lignes, key=lambda r: (r["scene"], r["role"], r["path"], r["assetId"]))}
        args.lock.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.lock, lock)
        compte["lock"] = {"fichier": str(args.lock), "lignes": len(lignes), "registryCommit": tete}
    compte["sha"] = sha
    print(json.dumps(compte, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
