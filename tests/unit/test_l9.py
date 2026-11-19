"""Régressions L9 sur miroirs de dépôts synthétiques."""

import json
import subprocess
import unittest
from unittest.mock import patch

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M
from tests.acceptance.test_l6_correctifs import _ajouter_jeu
from tools.core.catalog import write_json
from tools.extract import magick


class GeneratedResources(unittest.TestCase):
    repo = "jeu-genere"
    path = "public/icon.svg"
    generator = "src/draw.js"
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"/>'

    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        self.reg = self.world.registre

    def prepare(self, **extra):
        _ajouter_jeu(self, self.repo, {
            self.path: self.svg,
            self.generator: "// public/icon.svg",
            "LICENSE": "SPDX-License-Identifier: MIT\n",
            **extra,
        })

    def declare(self, fragment):
        file = self.reg / C.SOURCES
        document = C.lire_json(file)
        source = next(item for item in document["sources"] if item["name"] == self.repo)
        if fragment is None:
            source.pop("generatedResources")
        else:
            source["generatedResources"] = [
                {"path": "public/*.svg", "generator": self.generator, "mentions": [fragment]}
            ]
        write_json(file, document)
        self.world.commiter_registre("Modifie la déclaration de génération de la fixture")

    def scan(self):
        result = self.world.scan()
        self.assertEqual(result.code, C.OK, str(result))

    def test_sync_relit_ajout_remplacement_et_retrait_a_commit_source_constant(self):
        self.prepare()
        self.scan()
        asset_id, _ = C.asset_par_chemin(self.reg, self.repo, self.path)
        self.world.commiter_registre("Inventaire initial de la fixture")
        for step, fragment, expected in (
            ("ajout", self.path, "MIT"),
            ("remplacement", "absent", "unknown"),
            ("correction", self.path, "MIT"),
            ("retrait", None, "unknown"),
        ):
            with self.subTest(step=step):
                self.declare(fragment)
                branch = f"sync/l9-{step}"
                result = self.world.ctl(C.cmd_sync(branch, "--only", self.repo))
                self.assertEqual(result.code, C.OK, str(result))
                self.assertEqual(json.loads(result.stdout)["scannedCopies"], 1)
                asset = json.loads(self.world.git(self.reg, "show", f"{branch}:catalog/assets/{asset_id}.json"))
                self.assertEqual(asset["license"], expected)
                self.assertEqual(asset["version"], 1)
                self.assertEqual("generator" in asset["provenance"], expected == "MIT")
                self.world.git(self.reg, "merge", "--ff-only", branch)
                again = self.world.ctl(C.cmd_sync(branch, "--only", self.repo))
                self.assertEqual(again.code, C.OK, str(again))
                self.assertEqual(json.loads(again.stdout)["scannedCopies"], 0)

    def test_sortie_declaree_et_copie_de_meme_contenu_gardent_des_droits_distincts(self):
        other = "public-copy/icon.svg"
        self.prepare(**{other: self.svg})
        self.scan()
        self.world.commiter_registre("Inventaire avant déclaration")
        self.declare(self.path)
        self.scan()
        active = {
            location["path"]: asset
            for asset in C.assets(self.reg).values()
            for location in asset["files"]["locations"]
            if location.get("repo") == self.repo and location.get("status") == "active"
        }
        self.assertEqual(active[self.path]["license"], "MIT")
        self.assertEqual(active[other]["license"], "unknown")
        self.assertNotEqual(active[self.path]["id"], active[other]["id"])

    def test_licences_du_depot_en_conflit(self):
        self.prepare(**{"package.json": '{"license":"Apache-2.0"}'})
        self.declare(self.path)
        self.scan()
        _, asset = C.asset_par_chemin(self.reg, self.repo, self.path)
        self.assertEqual(asset["license"], "unknown")
        self.assertNotIn("generator", asset["provenance"])

    def test_licence_du_manifeste_seul_cite_sa_source(self):
        self.prepare(**{"LICENSE": "Aucun identifiant déclaré ici.\n", "package.json": '{"license":"MIT"}'})
        self.declare(self.path)
        self.scan()
        _, asset = C.asset_par_chemin(self.reg, self.repo, self.path)
        self.assertEqual(asset["license"], "MIT")
        self.assertEqual(asset["licenseEvidence"]["ref"], f"package.json@{self.world.commits[self.repo]}")

    def test_gardes_publiques_et_droits_au_commit_du_lock(self):
        self.prepare()
        self.declare(self.path)
        self.scan()
        asset_id, _ = C.asset_par_chemin(self.reg, self.repo, self.path)
        self.world.commiter_registre("Preuve de génération au catalogue")
        result = self.world.ctl(C.cmd_publish([asset_id], "public", self.world.racine / "export"))
        self.assertEqual(result.code, C.OK, str(result))
        self.world.commiter_registre("Publication de la sortie générée")
        game = self.world.depot("jeu-b")
        result = self.world.ctl(C.cmd_usage_add(asset_id, "jeu-b", "Menu", "sprite", game, "art/icon.svg"))
        self.assertEqual(result.code, C.OK, str(result))
        result = self.world.ctl(C.cmd_check_lock(game / C.LOCK_JEU, "--public"))
        self.assertEqual(result.code, C.OK, str(result))


class MagickVersion(unittest.TestCase):
    def test_version_installee_conserve_le_suffixe_de_compilation(self):
        executable = "/fixture/bin/magick"
        result = subprocess.CompletedProcess(
            [executable, "-version"], 0, stdout=b"Version: ImageMagick 7.1.2-35 Q16-HDRI\n"
        )
        with patch.object(magick, "which", return_value=executable), patch.object(
            magick.subprocess, "run", return_value=result
        ):
            self.assertEqual(magick.installed(), (executable, "7.1.2-35"))
        self.assertFalse(magick.VERSION.fullmatch("fixture"))
