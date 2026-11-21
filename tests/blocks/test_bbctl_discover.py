"""Oracles BB-001 lot 1 (HL-525), écrits AVANT le code : découverte des briques dans les dépôts autorisés (§ 3),
consultation (inspect, usages, impact) et inventaire réel.

Contrat fixé ici :
  bbctl discover --repos authorized --sources <sources.json> --clones <dossier> [--dry-run] --json
  - lit chaque dépôt autorisé dans sa copie locale, AU COMMIT HEAD, par git (jamais l'arbre de travail, jamais
    d'écriture dans le dépôt) ; un adaptateur par écosystème : npm (package.json + package-lock.json), Python
    (requirements.txt), modules locaux d'un monorepo (`src/engines/<x>`, `packages/<x>`) avec leurs usages par jeu
    (`src/games/<jeu>` qui importe le module) ;
  - seules les dépendances DIRECTES deviennent des briques (une dépendance transitive n'en est pas une, § 4) ;
  - une même bibliothèque sous deux versions = deux briques distinctes (T02) ; la licence vient du lockfile ou reste
    UNKNOWN (jamais inventée) ;
  - écrit `blocks/catalog/<id>.json`, `blocks/ids.json` (clé → identifiant, ajout seul) et `blocks/discovery.json`
    (commit indexé par dépôt : un dépôt inchangé n'est pas relu) ; relance = octets identiques (T03) ;
  - un dépôt sans copie locale est une EXCEPTION du rapport, pas un échec ; la liste des dépôts illisible = 4 (T12).
  bbctl inspect <BB-…> | usages <BB-…> | impact <BB-…> --to-version <v>  (T10)
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import unittest

from ._outil import Usine

PKG_MONO = {"name": "mono", "dependencies": {"phaser": "^3.80.1"}, "devDependencies": {"vitest": "1.0.0"}}
LOCK_MONO = {"lockfileVersion": 3, "packages": {
    "": {"name": "mono"},
    "node_modules/phaser": {"version": "3.80.1", "license": "MIT"},
    "node_modules/vitest": {"version": "1.0.0", "license": "MIT", "dev": True},
    "node_modules/eventemitter3": {"version": "5.0.1", "license": "MIT"}}}
PKG_B = {"name": "jeu-b", "dependencies": {"phaser": "3.90.0"}}
LOCK_B = {"lockfileVersion": 3, "packages": {"": {"name": "jeu-b"},
                                             "node_modules/phaser": {"version": "3.90.0", "license": "MIT"}}}


def git(d: pathlib.Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()
        self.clones = self.u.tmp / "clones"
        self.depot("mono", {
            "package.json": json.dumps(PKG_MONO), "package-lock.json": json.dumps(LOCK_MONO),
            "src/engines/combat/index.ts": "export function attaque() { return 1 }\n",
            "src/engines/save/index.ts": "export function sauver() {}\n",
            "src/games/alpha/scene.ts": "import { attaque } from '../../engines/combat'\n",
            "src/games/beta/scene.ts": "import { attaque } from '../../engines/combat/index'\nimport { sauver } from \"../../engines/save\"\n",
            "src/games/gamma/scene.ts": "export const rien = 0\n"})
        self.depot("jeu-b", {"package.json": json.dumps(PKG_B), "package-lock.json": json.dumps(LOCK_B),
                             "requirements.txt": "pillow==10.0.0\n"})
        self.sources = self.u.tmp / "sources.json"
        self.sources.write_text(json.dumps({"schemaVersion": 1, "excluded": [], "sources": [
            {"name": "mono"}, {"name": "jeu-b"}, {"name": "absent"}]}))

    def tearDown(self) -> None:
        self.u.nettoyer()

    def depot(self, nom: str, fichiers: dict[str, str]) -> pathlib.Path:
        d = self.clones / nom
        for chemin, texte in fichiers.items():
            (d / chemin).parent.mkdir(parents=True, exist_ok=True)
            (d / chemin).write_text(texte)
        if not (d / ".git").exists():
            git(d, "init", "-q", "-b", "main")
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "c")
        return d

    def decouvrir(self, *extra: str):
        return self.u.bbctl("discover", "--repos", "authorized", "--sources", str(self.sources),
                            "--clones", str(self.clones), *extra, "--json")

    def catalogue(self) -> dict[str, dict]:
        d = self.u.usine / "blocks" / "catalog"
        return {p.stem: json.loads(p.read_text()) for p in d.glob("*.json")}

    def par_nom(self, nom: str) -> list[dict]:
        return [b for b in self.catalogue().values() if b["name"] == nom]


class Decouverte(Base):
    def test_T01_monorepo_modules_et_usages_par_jeu(self) -> None:
        r = self.decouvrir()
        self.assertEqual(r.rc, 0, r)
        (combat,) = self.par_nom("combat")
        (save,) = self.par_nom("save")
        self.assertEqual(combat["kind"], "game-local-module")
        self.assertEqual((combat["origin"]["repo"], combat["origin"]["path"]), ("mono", "src/engines/combat"))
        self.assertEqual(combat["usedBy"], ["mono/alpha", "mono/beta"])
        self.assertEqual(save["usedBy"], ["mono/beta"])

    def test_T02_meme_bibliotheque_deux_versions_deux_instances(self) -> None:
        self.decouvrir()
        phaser = sorted(self.par_nom("phaser"), key=lambda b: b["origin"]["version"])
        self.assertEqual([b["origin"]["version"] for b in phaser], ["3.80.1", "3.90.0"])
        self.assertNotEqual(phaser[0]["id"], phaser[1]["id"])
        self.assertEqual([b["usedBy"] for b in phaser], [["mono"], ["jeu-b"]])
        self.assertEqual({b["origin"]["licenseSpdx"] for b in phaser}, {"MIT"})

    def test_transitive_n_est_pas_une_brique_licence_jamais_inventee(self) -> None:
        self.decouvrir()
        self.assertEqual(self.par_nom("eventemitter3"), [])
        (pillow,) = self.par_nom("pillow")
        self.assertEqual((pillow["origin"]["licenseSpdx"], pillow["origin"]["version"]), ("UNKNOWN", "10.0.0"))
        self.assertEqual(pillow["quality"]["status"], "discovered")
        (vitest,) = self.par_nom("vitest")
        self.assertEqual(vitest["kind"], "test-harness")

    def test_T03_relance_octets_identiques(self) -> None:
        self.decouvrir()
        avant = self.u.empreinte(self.u.usine / "blocks")
        r = self.decouvrir()
        self.assertEqual(r.json["skipped"], ["jeu-b", "mono"])                 # commits inchangés : non relus
        self.assertEqual(self.u.empreinte(self.u.usine / "blocks"), avant)
        self.assertEqual(self.u.bbctl("validate", "--all", "--json").rc, 0)

    def test_indexation_incrementale_par_commit(self) -> None:
        self.decouvrir()
        self.depot("jeu-b", {"package.json": json.dumps(PKG_B | {"dependencies": {"phaser": "3.90.0", "howler": "2.2.4"}})})
        r = self.decouvrir()
        self.assertEqual((r.json["scanned"], r.json["skipped"]), (["jeu-b"], ["mono"]))
        (howler,) = self.par_nom("howler")
        self.assertEqual((howler["origin"]["version"], howler["origin"]["licenseSpdx"]), (None, "UNKNOWN"))

    def test_lecture_seule_et_dry_run(self) -> None:
        avant_depots = self.u.empreinte(self.clones)
        avant = self.u.empreinte(self.u.usine)
        r = self.decouvrir("--dry-run")
        self.assertEqual(r.rc, 0, r)
        self.assertGreaterEqual(r.json["blocks"], 7)
        self.assertEqual(self.u.empreinte(self.u.usine), avant)
        self.decouvrir()
        self.assertEqual(self.u.empreinte(self.clones), avant_depots)

    def test_exceptions_et_source_indisponible(self) -> None:
        r = self.decouvrir()
        self.assertEqual(r.json["exceptions"], [{"repo": "absent", "reason": "copie-locale-absente"}])
        self.sources.unlink()
        avant = self.u.empreinte(self.u.usine)
        r = self.decouvrir()
        self.assertEqual(r.rc, 4, r)
        self.assertEqual(self.u.empreinte(self.u.usine), avant)

    def test_identifiants_stables_et_jamais_recycles(self) -> None:
        self.decouvrir()
        ids = json.loads((self.u.usine / "blocks" / "ids.json").read_text())
        self.assertEqual(len(set(ids.values())), len(ids))
        self.assertIn("npm:phaser@3.80.1", ids)
        self.assertIn("local:mono:src/engines/combat", ids)


class Consultation(Base):
    def setUp(self) -> None:
        super().setUp()
        self.assertEqual(self.decouvrir().rc, 0)
        self.phaser = sorted(self.par_nom("phaser"), key=lambda b: b["origin"]["version"])
        self.combat = self.par_nom("combat")[0]

    def test_inspect(self) -> None:
        r = self.u.bbctl("inspect", self.combat["id"], "--json")
        self.assertEqual((r.rc, r.json["block"]["name"]), (0, "combat"))
        self.assertEqual(self.u.bbctl("inspect", "BB-INCONNU-001", "--json").rc, 1)

    def test_usages(self) -> None:
        r = self.u.bbctl("usages", self.combat["id"], "--json")
        self.assertEqual(r.json["usedBy"], ["mono/alpha", "mono/beta"])
        self.assertEqual(r.json["observedIn"][0]["repo"], "mono")

    def test_T10_changement_de_version_partagee_projets_impactes(self) -> None:
        r = self.u.bbctl("impact", self.phaser[1]["id"], "--to-version", "3.90.0", "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(r.json["impacted"], ["mono"])                           # jeu-b est déjà en 3.90.0
        r = self.u.bbctl("impact", self.combat["id"], "--to-version", "2.0.0", "--json")
        self.assertEqual(r.json["impacted"], ["mono/alpha", "mono/beta"])


if __name__ == "__main__":
    unittest.main()
