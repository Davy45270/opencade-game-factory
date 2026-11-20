"""Outils communs des oracles du module specs/ (REG-003) : un homelab-docs JETABLE et l'appel de `specctl`.

Contrat d'appel (fixé par ces oracles, à respecter par l'implémentation) :
  - exécutable `./specctl` à la racine de l'usine (comme `./assetctl`), aussi `python3 -m specs.specctl` ;
  - `USINE_RACINE=<dossier>` : où `specctl` lit et écrit SES données (`specs/registry/…`) ; défaut = la racine du dépôt.
    Les tests pointent toujours un dossier temporaire : aucun test n'écrit dans le dépôt ;
  - `--from <homelab-docs>` : le dépôt git de la doc, LU SEULEMENT ;
  - `--json` : un seul objet JSON sur stdout ; le journal va sur stderr ;
  - codes communs de l'usine (docs/ARCHITECTURE.md) : 0 succès, 1 contrôle en échec, 2 usage, 3 refus de sécurité,
    4 source indisponible, 5 conflit de versions (arbitrage requis). REG-003 § 6 numérote autrement (2 = non-conformité,
    3 = entrée invalide) : la table commune de l'usine l'emporte (HL-525 7-2957 § 6.1).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

RACINE = pathlib.Path(__file__).resolve().parents[2]
SPECCTL = RACINE / "specctl"

SPEC_A = "# Jeu A\n\n## Règles\n\nLe joueur pose une tuile.\nLa partie finit quand la réserve est vide.\n"
SPEC_A_V11 = SPEC_A + "\nAjout v1.1 : mode à deux.\n"
SPEC_B = "# Jeu B\n\nLe joueur saute.\n"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def git(d: pathlib.Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


class Docs:
    """homelab-docs jetable : specs/<x>-sources/ (archives + empreintes-drive.sha256) et specs/<x>-conformite.json."""

    def __init__(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="specctl-"))
        self.docs = self.tmp / "homelab-docs"
        self.usine = self.tmp / "usine"
        self.usine.mkdir()
        self.docs.mkdir()
        git(self.docs, "init", "-q", "-b", "main")
        self.archive("jeu-a", {"Jeu_A_v1.0.md.txt": SPEC_A})
        self.archive("jeu-b", {"Jeu_B_v1.0.md.txt": SPEC_B})
        self.matrice("jeu-a", "Jeu_A_v1.0.md.txt", [("E001", "Le joueur pose une tuile.", "faite"),
                                                     ("E002", "La partie finit quand la réserve est vide.", "a_faire")])
        self.commit("archives")

    def archive(self, x: str, fichiers: dict[str, str]) -> None:
        s = self.docs / "specs" / f"{x}-sources"
        s.mkdir(parents=True, exist_ok=True)
        lignes = ["# Drive : identifiants factices (oracle)"]
        anciennes = (s / "empreintes-drive.sha256").read_text().splitlines()[1:] if (s / "empreintes-drive.sha256").is_file() else []
        for nom, texte in fichiers.items():
            (s / nom).parent.mkdir(parents=True, exist_ok=True)
            (s / nom).write_text(texte)
            anciennes.append(f"{sha(texte.encode())}  {nom}")
        (s / "empreintes-drive.sha256").write_text("\n".join(lignes + anciennes) + "\n")
        (s / "index.md").write_text(f"# Sources {x}\n")

    def matrice(self, x: str, fichier: str, lignes: list[tuple[str, str, str]]) -> None:
        f = f"specs/{x}-sources/{fichier}"
        m = {"schema": "conformite-jeu/1", "jeu": x,
             "sources": [{"fichier": f, "sha256": sha((self.docs / f).read_bytes())}],
             "exigences": [{"id": i, "source": {"fichier": f, "extrait": e}, "statut": st} for i, e, st in lignes]}
        (self.docs / "specs" / f"{x}-conformite.json").write_text(json.dumps(m, ensure_ascii=False, indent=1))

    def commit(self, msg: str) -> str:
        git(self.docs, "add", "specs")
        git(self.docs, "commit", "-q", "-m", msg)
        return git(self.docs, "rev-parse", "HEAD")

    def empreinte_docs(self) -> str:
        """Empreinte de TOUT l'arbre de travail de la doc (preuve de lecture seule)."""
        h = hashlib.sha256()
        for p in sorted(self.docs.rglob("*")):
            if ".git" in p.parts or not p.is_file():
                continue
            h.update(str(p.relative_to(self.docs)).encode() + b"\0" + p.read_bytes())
        return h.hexdigest()

    def empreinte_usine(self) -> str:
        h = hashlib.sha256()
        for p in sorted(self.usine.rglob("*")):
            if p.is_file():
                h.update(str(p.relative_to(self.usine)).encode() + b"\0" + p.read_bytes())
        return h.hexdigest()

    def specctl(self, *args: str, entree: str | None = None, env_tour: dict[str, str] | None = None) -> "Resultat":
        # Isolation : jamais la Control Tower réelle de la machine. Un test qui veut des événements passe env_tour.
        env = {k: v for k, v in os.environ.items() if not k.startswith("TOWER_")}
        env.update(USINE_RACINE=str(self.usine), **(env_tour or {}))
        r = subprocess.run([str(SPECCTL), *args], capture_output=True, text=True, env=env, input=entree, timeout=120,
                           cwd=str(self.tmp))
        return Resultat(r.returncode, r.stdout, r.stderr)

    def registre(self) -> dict[str, dict]:
        d = self.usine / "specs" / "registry"
        return {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("SPEC-*.json"))} if d.is_dir() else {}

    def nettoyer(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class Resultat:
    def __init__(self, rc: int, stdout: str, stderr: str) -> None:
        self.rc, self.stdout, self.stderr = rc, stdout, stderr

    @property
    def json(self) -> dict:
        return json.loads(self.stdout)

    def __repr__(self) -> str:
        return f"rc={self.rc} stdout={self.stdout[:300]!r} stderr={self.stderr[-300:]!r}"
