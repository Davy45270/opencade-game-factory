"""E257 (EXT-002 01_VISION) : hors périmètre — backend permanent, éditeur graphique, multijoueur temps réel, génération
de graphismes, conversion 3D. Garde : rien de tout cela n'entre sans décision écrite (ce test casse s'il entre)."""
import re
from pathlib import Path
from unittest import TestCase

from tools.cli import COMMANDS
from tools.levels.commands import SUBCOMMANDS

RACINE = Path(__file__).resolve().parents[2]
INTERDITS_CLI = re.compile(r"(?i)^(serve|server|daemon|api|editor|editeur|multiplayer|multijoueur|lobby|"
                           r"convert-3d|to-3d|draw|paint|generate-art|genart)$")
SERVEURS = re.compile(r"(?m)^\s*(?:from|import)\s+(?:http\.server|socketserver|flask|fastapi|aiohttp|websockets?|"
                      r"tornado|uvicorn|starlette|bottle|trimesh|pygltflib|bpy|open3d|diffusers)\b")
DEPS = re.compile(r"(?im)^(flask|fastapi|aiohttp|websockets|tornado|uvicorn|django|trimesh|pygltflib|open3d|"
                  r"diffusers|stable[-_]diffusion)\b")


class HorsPerimetre(TestCase):
    def test_aucune_commande_hors_perimetre(self):
        noms = set(COMMANDS) | set(SUBCOMMANDS)
        self.assertEqual(sorted(n for n in noms if INTERDITS_CLI.match(n)), [])

    def test_aucun_serveur_ni_conversion_3d_ni_generation_graphique_dans_le_code(self):
        fautifs = [p.relative_to(RACINE).as_posix() for p in sorted((RACINE / "tools").rglob("*.py"))
                   if SERVEURS.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(fautifs, [])

    def test_aucune_dependance_hors_perimetre(self):
        for nom in sorted(RACINE.glob("requirements*.txt")):
            self.assertIsNone(DEPS.search(nom.read_text()), nom.name)

    def test_la_garde_voit_un_serveur(self):
        self.assertTrue(SERVEURS.search("import http.server\n"))
        self.assertTrue(INTERDITS_CLI.match("serve"))
        self.assertTrue(DEPS.search("fastapi==1\n"))
