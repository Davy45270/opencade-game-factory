"""Oracles ligne par ligne de la matrice game-factory (HL-525), BB-001 § 3, écrits AVANT le code : la découverte lit
aussi workflows, scripts et pnpm-lock.yaml (E175, E176), extrait exports et imports publics des modules (E176, E216)
et qualifie chaque module : interfaces, capacités, dépendances, tests, mainteneurs, couverture, maturité (E177).
Ce qui n'est pas mesurable reste null (§ 7) : jamais une couverture ou un mainteneur inventé.
"""
from __future__ import annotations

import json

from .test_bbctl_discover import Base as Decouverte

PNPM_LOCK = """lockfileVersion: '9.0'

settings:
  autoInstallPeers: true

importers:

  .:
    dependencies:
      rot-js:
        specifier: ^2.2.0
        version: 2.2.1
    devDependencies:
      typescript:
        specifier: ~5.6.0
        version: 5.6.3(@types/node@22.0.0)

packages:

  rot-js@2.2.1:
    resolution: {integrity: sha512-x}
"""


class Base(Decouverte):
    def setUp(self) -> None:
        super().setUp()
        self.depot("mono", {
            ".woodpecker/checks.yml": "steps:\n  - name: test\n",
            "scripts/publier.sh": "#!/bin/sh\necho publier\n",
            "src/engines/combat/package.json": json.dumps({"name": "@mono/combat", "author": "Équipe combat"}),
            "src/engines/combat/index.ts": ("import { clamp } from 'lodash-es'\nimport { sauver } from '../save'\n"
                                            "export function attaque() { return clamp(1, 0, 2) }\n"
                                            "export const DEGATS_MAX = 9\nexport class Arbitre {}\n"
                                            "export type Coup = { force: number }\nconst interne = 1\n"),
            "src/engines/combat/attaque.test.ts": "import { attaque } from './index'\n",
            "src/games/alpha/scene.ts": "import { attaque } from '../../engines/combat'\n",
        })
        self.depot("jeu-p", {"package.json": json.dumps({"name": "jeu-p", "dependencies": {"rot-js": "^2.2.0"},
                                                         "devDependencies": {"typescript": "~5.6.0"}}),
                             "pnpm-lock.yaml": PNPM_LOCK})
        self.sources.write_text(json.dumps({"schemaVersion": 1, "excluded": [], "sources": [
            {"name": "mono"}, {"name": "jeu-b"}, {"name": "jeu-p"}]}))
        r = self.decouvrir()
        self.assertEqual(r.rc, 0, r)


class E175WorkflowsEtScripts(Base):
    def test_workflows_et_scripts_inventories(self) -> None:
        (wf,) = [b for b in self.catalogue().values() if b["kind"] == "workflow"]
        self.assertEqual((wf["origin"]["repo"], wf["origin"]["path"], wf["usedBy"]), ("mono", ".woodpecker/checks.yml", ["mono"]))
        (sc,) = [b for b in self.catalogue().values() if b["origin"].get("path") == "scripts/publier.sh"]
        self.assertEqual((sc["kind"], sc["origin"]["repo"]), ("cli-tool", "mono"))
        self.assertEqual([b for b in self.catalogue().values() if (b["origin"].get("repo") == "jeu-b"
                                                                    and b["kind"] in ("workflow", "cli-tool"))], [])


class E176PnpmLockEtExportsPublics(Base):
    def test_versions_lues_dans_pnpm_lock(self) -> None:
        (rot,) = self.par_nom("rot-js")
        self.assertEqual((rot["origin"]["version"], rot["discovery"]["key"]), ("2.2.1", "npm:rot-js@2.2.1"))
        (ts,) = [b for b in self.par_nom("typescript") if "jeu-p" in b["usedBy"]]
        self.assertEqual(ts["origin"]["version"], "5.6.3")                     # suffixe de pairs retiré

    def test_exports_et_imports_publics_du_module(self) -> None:
        (combat,) = self.par_nom("combat")
        a = combat["analysis"]
        self.assertEqual(a["exports"], ["Arbitre", "Coup", "DEGATS_MAX", "attaque"])   # jamais `interne`
        self.assertEqual(a["imports"], ["local:mono:src/engines/save", "lodash-es"])


class E177QualificationDesModules(Base):
    def test_interfaces_capacites_tests_mainteneurs_couverture_maturite(self) -> None:
        (combat,) = self.par_nom("combat")
        self.assertEqual(combat["capabilities"], ["arbitre", "attaque", "coup", "degats-max"])
        self.assertEqual(combat["interfaces"][0]["exports"], ["Arbitre", "Coup", "DEGATS_MAX", "attaque"])
        a = combat["analysis"]
        self.assertEqual(a["tests"], ["src/engines/combat/attaque.test.ts"])
        self.assertEqual(a["maintainers"], ["Équipe combat"])                 # déclaré par le paquet, pas deviné
        self.assertIsNone(a["coverage"])                                       # non mesurée : null, pas 0
        self.assertEqual(a["maturity"], "tested")
        (save,) = self.par_nom("save")
        self.assertEqual((save["analysis"]["tests"], save["analysis"]["maintainers"], save["analysis"]["maturity"]),
                         ([], None, "untested"))

    def test_capacites_tenues_a_la_main_jamais_ecrasees(self) -> None:
        (combat,) = self.par_nom("combat")
        f = self.u.usine / "blocks" / "catalog" / f"{combat['id']}.json"
        combat["capabilities"] = ["turn-based-combat"]
        f.write_text(json.dumps(combat, ensure_ascii=False, indent=1))
        self.depot("mono", {"src/engines/combat/autre.ts": "export const x = 1\n"})
        self.assertEqual(self.decouvrir().rc, 0)
        (combat,) = self.par_nom("combat")
        self.assertEqual(combat["capabilities"], ["turn-based-combat"])


class E216CapacitesEtUsagesTraces(Base):
    def test_usages_par_import_et_capacites_par_export(self) -> None:
        (combat,) = self.par_nom("combat")
        self.assertEqual(combat["usedBy"], ["mono/alpha", "mono/beta"])
        (save,) = self.par_nom("save")
        self.assertIn("mono/engines/combat", save["usedBy"])                   # usage tracé par l'import du module
        self.assertEqual(save["capabilities"], ["sauver"])
