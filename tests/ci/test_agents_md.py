"""AGENTS.md de l'usine (écart 10) : les règles communes aux agents y sont, et chaque prompt rangé dans .codex-logs y renvoie."""
from __future__ import annotations

import pathlib
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[2]


class AgentsMd(unittest.TestCase):
    def setUp(self) -> None:
        self.texte = (RACINE / "AGENTS.md").read_text(encoding="utf-8")

    def test_regles_communes_presentes(self) -> None:
        for regle in ("graphify", "token_budget=4000", "pkill", "killall", "<<'EOF'", "git add -A",
                      "Aucun son", "n'approuve jamais sa propre dérogation", "expire", "codex-file.sh"):
            self.assertIn(regle, self.texte, regle)

    def test_les_prompts_codex_renvoient_a_agents_md(self) -> None:
        prompts = sorted((RACINE / ".codex-logs").glob("*prompt*.md")) if (RACINE / ".codex-logs").is_dir() else []
        if not prompts:
            self.skipTest(".codex-logs absent (gitignoré : clone neuf ou CI)")
        sans = [p.name for p in prompts if "AGENTS.md" not in p.read_text(encoding="utf-8")
                and p.stat().st_mtime > (RACINE / "AGENTS.md").stat().st_mtime]
        self.assertEqual(sans, [], "prompts écrits après AGENTS.md sans y renvoyer")


if __name__ == "__main__":
    unittest.main()
