"""Oracles v1.0 E026/E106/E072 et EXT-002 E258 (« on utilise GitHub », David 22/11) : les workflows GitHub Actions
`.github/workflows/{scan,validate,build-index,release}.yml` (spec v1.0 § 3) et `{discover,validate,release}.yml`
(EXT-002 § 2) existent, tournent les MÊMES commandes que Woodpecker (qui reste en plus), et ne portent aucun secret.
Écrits AVANT les fichiers. Le vert réel se mesure sur GitHub (API des exécutions), pas ici."""
from __future__ import annotations

import pathlib
import re
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[2]
WF = RACINE / ".github" / "workflows"


def lire(nom):
    return (WF / f"{nom}.yml").read_text(encoding="utf-8")


def yaml_ou_saut(test):
    try:
        import yaml
    except ImportError:
        test.skipTest("PyYAML absent")
    return yaml


def declencheurs(d):
    # PyYAML lit la clé `on:` comme le booléen True.
    return d.get("on", d.get(True))


class WorkflowsRegistreGitHub(unittest.TestCase):
    def test_e026_les_quatre_workflows_de_la_spec_existent(self) -> None:
        for nom in ("scan", "validate", "build-index", "release"):
            self.assertTrue((WF / f"{nom}.yml").is_file(), nom)

    def test_e258_discover_validate_release_d_ext002(self) -> None:
        self.assertTrue((WF / "discover.yml").is_file())
        t = lire("discover")
        self.assertIn("scripts/niveaux-decouverte-publique.py", t)
        self.assertIn("level validate", lire("validate"))
        self.assertIn("level publish", lire("release"))

    def test_e106_validate_rejoue_les_controles_de_woodpecker(self) -> None:
        t = lire("validate")
        for c in ("python3 -m pytest -n 4 -q -p no:cacheprovider tests/unit",
                  "python3 -m pytest -n 4 -q -p no:cacheprovider tests/acceptance",
                  "./assetctl validate --json", "./assetctl validate --base", "./assetctl validate-atlas",
                  "./assetctl external audit-licenses --json", "./assetctl duplicates --json", "gitleaks"):
            self.assertIn(c, t, c)
        d = yaml_ou_saut(self).safe_load(t)
        self.assertIn("pull_request", declencheurs(d))

    def test_build_index_echoue_sur_un_index_perime(self) -> None:
        t = lire("build-index")
        self.assertIn("./assetctl index --json", t)
        self.assertIn("git diff --stat --exit-code -- generated/", t)

    def test_e072_scan_periodique_et_crochet_des_jeux(self) -> None:
        d = yaml_ou_saut(self).safe_load(lire("scan"))
        on = declencheurs(d)
        self.assertTrue(on.get("schedule"), "scan périodique (cron) exigé")
        self.assertIn("repository_dispatch", on, "crochet des dépôts de jeux (PR et merge)")
        self.assertIn("scan-repos --verify --dry-run --provider github", lire("scan"))

    def test_release_sur_tag_et_controle_sur_main(self) -> None:
        d = yaml_ou_saut(self).safe_load(lire("release"))
        on = declencheurs(d)
        self.assertIn("tags", on["push"])
        t = lire("release")
        self.assertIn("./assetctl sbom --out generated/sbom.cdx.json", t)
        self.assertIn("scripts/ci-local.sh controle-release", t)

    def test_aucun_secret_et_droits_minimaux(self) -> None:
        for f in sorted(WF.glob("*.yml")):
            t = f.read_text(encoding="utf-8")
            self.assertNotRegex(t, r"secrets\.(?!GITHUB_TOKEN)", f.name)
            d = yaml_ou_saut(self).safe_load(t)
            self.assertEqual(d.get("permissions"), {"contents": "read"}, f"{f.name} : droits par défaut en lecture")

    def test_actions_epinglees_par_sha(self) -> None:
        for f in sorted(WF.glob("*.yml")):
            for ref in re.findall(r"uses:\s*(\S+)", f.read_text(encoding="utf-8")):
                self.assertRegex(ref, r"@[0-9a-f]{40}$", f"{f.name} : {ref}")


if __name__ == "__main__":
    unittest.main()
