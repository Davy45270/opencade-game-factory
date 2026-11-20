#!/usr/bin/env python3
"""Gabarit CI commun des jeux (Woodpecker) : un jeu INCLUT la CI de l'usine au lieu de recopier son checks.yml.

Woodpecker n'a pas d'inclusion distante : l'inclusion se fait par GÉNÉRATION vérifiée. L'usine rend, pour un jeu, les
fichiers `.woodpecker/checks.yml`, `.woodpecker/e2e.yml` et `.woodpecker/usine/*.mjs` depuis `ci/gabarit/` et
`ci/scripts/`, avec les seuls paramètres du jeu (`.woodpecker/usine.json`). `verifier` refuse toute dérive : un fichier
modifié à la main, un gabarit de l'usine plus récent, ou une image Playwright qui n'est plus celle du package-lock.

usage : woodpecker.py rendre <dépôt> [--ecrire] [--json]   affiche (ou écrit) les fichiers générés
        woodpecker.py verifier <dépôt> [--json]            0 = la CI du jeu est celle du gabarit ; 1 = dérive (liste)
Codes (table commune de l'usine) : 0 succès, 1 contrôle en échec, 2 usage, 4 source indisponible (lock, paramètres).

Paramètres du jeu, `.woodpecker/usine.json` (tous facultatifs) :
  node_image     image Node des contrôles (défaut : NODE_IMAGE ci-dessous)
  checks_extra   étapes YAML propres au jeu, ajoutées APRÈS les contrôles communs (liste « - name: » à 2 espaces ;
                 ni privileged, ni volumes, ni attribut glissé dans une étape commune)
  e2e_commande   commande des specs Playwright, une seule ligne (défaut : npx playwright test)
  e2e            false = pas d'e2e.yml (jeu sans Playwright)
Ce qui est COMMUN et non négociable : SBOM CycloneDX vérifié, image Playwright lue au package-lock, e2e de démarrage
sous la CSP de production, audit, licences, secrets.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

ICI = pathlib.Path(__file__).resolve().parent
GABARIT = ICI / "gabarit"
SCRIPTS = ICI / "scripts"
# Revue Codex 6 (19/11) : les sorties sont PUBLIQUES (dépôts GitHub des jeux) — ni nom d'hôte ni adresse du miroir du
# homelab ; images publiques et aucune étiquette d'agent (le seul agent sans étiquette obligatoire prend le travail).
NODE_IMAGE = "docker.io/library/node:26"
GITLEAKS_IMAGE = "docker.io/zricethezav/gitleaks:v8.30.1"
E2E_COMMANDE = "npx playwright test"
# revue Codex 9 : + toute adresse IPv4 privée (RFC 1918), tailnet (100.64/10) ou de boucle, avec ou sans port
PRIVE_RE = re.compile(r"homelab|tank01|zalman|contabo|harbor|pingfr|duckdns|dav123|\.lan\b|\.local\b|\.internal\b|localhost"
                      r"|(?<![0-9.:])(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01])|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])|127\.\d{1,3})\.\d{1,3}\.\d{1,3}(?!\d|\.\d)", re.I)
# revue Codex 10 : une adresse = 4 octets, jamais précédée de « : » (un tag `node:10.24.1` n'est pas une adresse) ;
# revue Codex 11 : suivie d'un point et d'une lettre (10.24.1.2.sslip.io), c'est encore une adresse privée
CLES = {"node_image", "checks_extra", "e2e_commande", "e2e", "projet"}


class Indisponible(Exception):
    """Source indisponible (code 4) : lock ou paramètres illisibles."""


class Refus(Exception):
    """Contrôle en échec (code 1) : écriture refusée (lien symbolique, chemin hors du jeu)."""


# Revue Codex 3 (19/11) : les paramètres du jeu ne peuvent ni sortir de leur scalaire, ni ajouter d'attribut à une étape commune.
IMAGE_RE = re.compile(r"[a-z0-9][a-z0-9._/:@-]{0,254}")
INTERDITS_EXTRA = re.compile(r"^\s*-?\s*(privileged|volumes|network_mode|devices|pull|failure)\s*:", re.M)


def _ligne_simple(cle: str, v) -> str:
    if not isinstance(v, str) or not v.strip() or any(c in v for c in "\r\n\t\0") or len(v) > 500:
        raise Indisponible(f"usine.json : {cle} doit être une chaîne d'une seule ligne, non vide")
    return v


def _checks_extra(v) -> str:
    """Étapes propres au jeu : une liste d'étapes `  - name: …` à 2 espaces, rien d'autre (pas d'attribut glissé dans
    l'étape précédente, pas de clé de premier niveau, pas de privilège)."""
    if v in (None, ""):
        return ""
    if not isinstance(v, str) or "\t" in v or "\r" in v:
        raise Indisponible("usine.json : checks_extra doit être un texte YAML sans tabulation")
    lignes = [l for l in v.rstrip("\n").split("\n")]
    pleines = [l for l in lignes if l.strip()]
    if not pleines or not pleines[0].startswith("  - name: "):
        raise Indisponible("usine.json : checks_extra doit commencer par « - name: » (indentation 2)")
    for l in pleines:
        if not (l.startswith("  - name: ") or l.startswith("    ")):
            raise Indisponible(f"usine.json : checks_extra, ligne hors d'une étape : {l!r}")
    if INTERDITS_EXTRA.search(v):
        raise Indisponible("usine.json : checks_extra ne peut pas demander privileged, volumes, network_mode, devices, pull, failure")
    return "\n".join(lignes)


def empreinte_gabarit() -> str:
    """Empreinte de TOUT ce qui fait la CI commune : un gabarit ou un script changé ⇒ chaque jeu est en dérive."""
    h = hashlib.sha256()
    for f in sorted([*GABARIT.glob("*"), *SCRIPTS.glob("*")]):
        h.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def version_playwright(lock: dict) -> str | None:
    """Même règle que scripts/version-playwright.mjs : la PREMIÈRE valeur présente, qui doit être exacte (revue Codex 3 :
    Python sautait une première valeur inexacte que le script JS, lui, refuse)."""
    p, d = lock.get("packages") or {}, lock.get("dependencies") or {}
    for v in ((p.get("node_modules/@playwright/test") or {}).get("version"), (p.get("node_modules/playwright") or {}).get("version"),
              (d.get("@playwright/test") or {}).get("version"), (d.get("playwright") or {}).get("version")):
        if v is not None:
            return v if isinstance(v, str) and re.fullmatch(r"\d+\.\d+\.\d+", v) else None
    return None


def parametres(depot: pathlib.Path) -> dict:
    f = depot / ".woodpecker" / "usine.json"
    if not f.is_file():
        return {}
    try:
        p = json.loads(f.read_text(encoding="utf-8"))
    except ValueError as e:
        raise Indisponible(f"{f} illisible : {e}") from e
    if not isinstance(p, dict) or set(p) - CLES:
        raise Indisponible(f"{f} : clés inconnues {sorted(set(p) - CLES) if isinstance(p, dict) else '(pas un objet)'}")
    return p


def rendre(depot: pathlib.Path) -> dict[str, str]:
    """{chemin relatif au dépôt : contenu} — ce que la CI du jeu DOIT être."""
    p = parametres(depot)
    emp = empreinte_gabarit()
    entete = (f"# GÉNÉRÉ par l'usine (ci/woodpecker.py, gabarit {emp[:12]}) : ne pas éditer à la main.\n"
              "# Paramètres propres au jeu : .woodpecker/usine.json ; puis régénérer.")
    extra = _checks_extra(p.get("checks_extra"))
    image = _ligne_simple("node_image", p["node_image"]) if "node_image" in p else NODE_IMAGE
    if not IMAGE_RE.fullmatch(image):
        raise Indisponible(f"usine.json : node_image invalide {image!r}")
    # revue Codex 7 (19/11) : la sortie est PUBLIQUE — un node_image qui nomme le miroir ou un hôte du réseau privé fuirait
    if PRIVE_RE.search(image):
        raise Indisponible(f"usine.json : node_image nomme une infrastructure privée ({image!r}) : image publique seulement")
    commande = _ligne_simple("e2e_commande", p["e2e_commande"]) if "e2e_commande" in p else E2E_COMMANDE
    if "e2e" in p and not isinstance(p["e2e"], bool):
        raise Indisponible("usine.json : e2e doit être true ou false")
    # json.dumps = scalaire YAML entre guillemets doubles : « a: b », « # », « & » restent du texte
    valeurs = {"@ENTETE@": entete, "@NODE_IMAGE@": image, "@GITLEAKS_IMAGE@": GITLEAKS_IMAGE,
               "@CHECKS_EXTRA@": extra, "@E2E_COMMANDE@": json.dumps(commande, ensure_ascii=False)}
    fichiers = {"checks.yml": True, "e2e.yml": p.get("e2e", True) is not False}
    if fichiers["e2e.yml"]:
        try:
            lock = json.loads((depot / "package-lock.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise Indisponible(f"package-lock.json absent ou illisible : {e}") from e
        v = version_playwright(lock)
        if v is None:
            raise Indisponible("Playwright absent du package-lock (ou version non exacte) ; `\"e2e\": false` pour un jeu sans e2e")
        valeurs["@PLAYWRIGHT_IMAGE@"] = f"mcr.microsoft.com/playwright:v{v}-noble"
    out = {}
    for nom, garder in fichiers.items():
        if not garder:
            continue
        texte = (GABARIT / nom).read_text(encoding="utf-8")
        for cle, val in valeurs.items():
            texte = texte.replace(cle + "\n", val + "\n" if val else "") if cle == "@CHECKS_EXTRA@" else texte.replace(cle, val)
        reste = re.search(r"@[A-Z0-9_]+@", texte)
        if reste:
            raise Indisponible(f"gabarit {nom} : paramètre non remplacé {reste.group(0)}")
        out[f".woodpecker/{nom}"] = texte
    for s in sorted(SCRIPTS.glob("*.mjs")):
        out[f".woodpecker/usine/{s.name}"] = s.read_text(encoding="utf-8")
    out[".woodpecker/usine/spec.json"] = json.dumps(_resolution(depot, p), ensure_ascii=False, indent=1) + "\n"
    return out


def _resolution(depot: pathlib.Path, p: dict) -> dict:
    """REG-06 : résolution de la spec du jeu par `specctl resolve` (registre de l'usine, USINE_RACINE respecté). Seuls
    projet, identifiant, version et statut sortent : le fichier part dans un dépôt public. Statut ≠ ok = CI rouge."""
    projet = p.get("projet")
    if projet is None:
        try:
            projet = json.loads((depot / "package.json").read_text(encoding="utf-8")).get("name")
        except (OSError, ValueError):
            projet = None
    if not isinstance(projet, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", projet):
        return {"project": projet if isinstance(projet, str) else None, "status": "projet-invalide"}
    try:
        r = subprocess.run([str(ICI.parent / "specctl"), "--json", "resolve", "--project", projet], capture_output=True,
                           text=True, timeout=60)
        v = json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        raise Indisponible(f"specctl resolve indisponible : {e.__class__.__name__}") from e
    if r.returncode == 4:
        raise Indisponible("specctl resolve : source indisponible (code 4)")
    specs = v.get("specs") if isinstance(v, dict) else None
    if r.returncode == 0 and isinstance(specs, list) and len(specs) == 1 and specs[0].get("version"):
        return {"project": projet, "specId": specs[0].get("specId"), "version": specs[0]["version"], "status": "ok"}
    return {"project": projet, "specId": v.get("specId") if isinstance(v, dict) else None,
            "status": (v.get("status") if isinstance(v, dict) else None) or f"code-{r.returncode}"}


def _liens(depot: pathlib.Path, chemin: str) -> str | None:
    """Premier composant de `chemin` (dans le dépôt) qui est un lien symbolique, ou None."""
    c = depot
    for part in pathlib.PurePosixPath(chemin).parts:
        c = c / part
        if c.is_symlink():
            return str(c.relative_to(depot))
    return None


def derives(depot: pathlib.Path) -> list[str]:
    """Écarts entre la CI du jeu et le gabarit ; vide = conforme. Revue Codex 3 (19/11) : un workflow ou un script
    SURNUMÉRAIRE (ancien e2e.yml d'un jeu passé à `e2e: false`, autre .yml, ancien .mjs) est aussi une dérive, car
    Woodpecker exécute tout `.woodpecker/*.yml` ; un fichier généré en lien symbolique aussi."""
    out = []
    attendus = rendre(depot)
    wp = depot / ".woodpecker"
    if wp.is_dir() and not wp.is_symlink():
        presents = {str(f.relative_to(depot)) for f in wp.rglob("*") if (f.is_file() or f.is_symlink()) and f.name != "usine.json"}
        for chemin in sorted(presents - set(attendus)):
            out.append(f"{chemin} surnuméraire (non généré par l'usine : le retirer)")
    for chemin, attendu in attendus.items():
        f = depot / chemin
        lien = _liens(depot, chemin)
        if lien:
            out.append(f"{chemin} : {lien} est un lien symbolique (fichier réel exigé)")
        elif not f.is_file():
            out.append(f"{chemin} absent")
        elif f.read_text(encoding="utf-8") != attendu:
            out.append(f"{chemin} diffère du gabarit (modifié à la main, gabarit plus récent ou lock changé)")
    return out


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    drapeaux = {a for a in argv if a.startswith("--")}
    if len(args) != 2 or args[0] not in ("rendre", "verifier") or drapeaux - {"--ecrire", "--json"}:
        print(__doc__, file=sys.stderr)
        return 2
    depot = pathlib.Path(args[1]).resolve()
    if not depot.is_dir():
        print(f"dépôt introuvable : {depot}", file=sys.stderr)
        return 2
    try:
        if args[0] == "verifier":
            d = derives(depot)
            if "--json" in drapeaux:
                print(json.dumps({"ok": not d, "derives": d, "gabarit": empreinte_gabarit()}, ensure_ascii=False))
            else:
                print("\n".join(d) if d else f"CI conforme au gabarit {empreinte_gabarit()[:12]}")
            return 1 if d else 0
        fichiers = rendre(depot)
        if "--ecrire" in drapeaux:
            for chemin in fichiers:   # tout vérifier AVANT d'écrire quoi que ce soit
                lien = _liens(depot, chemin)
                if lien:
                    raise Refus(f"{lien} est un lien symbolique : écriture refusée (elle sortirait peut-être du jeu)")
            for chemin, texte in fichiers.items():
                f = depot / chemin
                f.parent.mkdir(parents=True, exist_ok=True)
                tmp = f.with_name(f".{f.name}.usine-tmp")
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
                with os.fdopen(fd, "w", encoding="utf-8") as h:
                    h.write(texte)
                os.replace(tmp, f)
        if "--json" in drapeaux:
            print(json.dumps({"ok": True, "fichiers": sorted(fichiers), "ecrit": "--ecrire" in drapeaux}, ensure_ascii=False))
        else:
            for chemin in sorted(fichiers):
                print(("écrit " if "--ecrire" in drapeaux else "") + chemin)
        return 0
    except Indisponible as e:
        print(f"source indisponible : {e}", file=sys.stderr)
        return 4
    except Refus as e:
        print(f"REFUS : {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
