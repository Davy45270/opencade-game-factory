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
  checks_extra   étapes YAML propres au jeu, insérées après `build` (texte, indentation de `steps:` à 2 espaces)
  e2e_commande   commande des specs Playwright (défaut : npx playwright test)
  e2e            false = pas d'e2e.yml (jeu sans Playwright)
Ce qui est COMMUN et non négociable : SBOM CycloneDX vérifié, image Playwright lue au package-lock, e2e de démarrage
sous la CSP de production, audit, licences, secrets.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

ICI = pathlib.Path(__file__).resolve().parent
GABARIT = ICI / "gabarit"
SCRIPTS = ICI / "scripts"
NODE_IMAGE = "harbor.pingfr.duckdns.org/dockerhub/library/node:26"
GITLEAKS_IMAGE = "harbor.pingfr.duckdns.org/dockerhub/zricethezav/gitleaks:v8.30.1"
E2E_COMMANDE = "npx playwright test"
CLES = {"node_image", "checks_extra", "e2e_commande", "e2e"}


class Indisponible(Exception):
    """Source indisponible (code 4) : lock ou paramètres illisibles."""


def empreinte_gabarit() -> str:
    """Empreinte de TOUT ce qui fait la CI commune : un gabarit ou un script changé ⇒ chaque jeu est en dérive."""
    h = hashlib.sha256()
    for f in sorted([*GABARIT.glob("*"), *SCRIPTS.glob("*")]):
        h.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def version_playwright(lock: dict) -> str | None:
    """Même règle que scripts/version-playwright.mjs."""
    p, d = lock.get("packages") or {}, lock.get("dependencies") or {}
    for v in ((p.get("node_modules/@playwright/test") or {}).get("version"), (p.get("node_modules/playwright") or {}).get("version"),
              (d.get("@playwright/test") or {}).get("version"), (d.get("playwright") or {}).get("version")):
        if isinstance(v, str) and re.fullmatch(r"\d+\.\d+\.\d+", v):
            return v
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
    extra = str(p.get("checks_extra") or "").rstrip("\n")
    valeurs = {"@ENTETE@": entete, "@NODE_IMAGE@": p.get("node_image") or NODE_IMAGE, "@GITLEAKS_IMAGE@": GITLEAKS_IMAGE,
               "@CHECKS_EXTRA@": extra, "@E2E_COMMANDE@": p.get("e2e_commande") or E2E_COMMANDE}
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
    return out


def derives(depot: pathlib.Path) -> list[str]:
    """Écarts entre la CI du jeu et le gabarit ; vide = conforme."""
    out = []
    for chemin, attendu in rendre(depot).items():
        f = depot / chemin
        if not f.is_file():
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
            for chemin, texte in fichiers.items():
                f = depot / chemin
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(texte, encoding="utf-8")
        if "--json" in drapeaux:
            print(json.dumps({"ok": True, "fichiers": sorted(fichiers), "ecrit": "--ecrire" in drapeaux}, ensure_ascii=False))
        else:
            for chemin in sorted(fichiers):
                print(("écrit " if "--ecrire" in drapeaux else "") + chemin)
        return 0
    except Indisponible as e:
        print(f"source indisponible : {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
