"""Histoires synthétiques pour les liens causaux et le choix des copies."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from tools.discovery.repos import Copy, Git
from tools.discovery.scan import _descends_from_all, _divergences, _record_causality


class HistoiresDeCopies(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        self.git = Git(self.root)
        self.git.run("init", "--bare", "--initial-branch=main")
        self.tree = self.git.run("mktree").decode().strip()

    def commit(self, message, *parents):
        ancestry = [argument for parent in parents for argument in ("-p", parent)]
        return self.git.run("-c", "user.name=Registry fixture", "-c",
                            "user.email=registry-fixture@noreply.invalid",
                            "commit-tree", self.tree, *ancestry, "-m", message).decode().strip()

    def mirror(self, name, commit, depth=None):
        self.git.run("update-ref", "refs/heads/main", commit)
        dest = self.root / name
        options = ["--depth", str(depth)] if depth else []
        self.git.run("clone", "--bare", *options, "--", self.root.as_uri(), str(dest))
        return dest

    def test_m5_une_branche_indisponible_ne_transforme_pas_le_losange_en_chaine(self):
        root = self.commit("R")
        left = self.commit("A", root)
        right = self.commit("B", root)
        merge = self.commit("M", left, right)
        complete = self.mirror("complete.git", merge)
        # Three versions remain comparable in the available mirror. B belongs
        # to a copy that did not contribute an imported snapshot this time.
        partial = self.mirror("partial.git", left)
        # A narrow double leaves M available without B, independently of the
        # object layout chosen by Git's packer.
        target = SimpleNamespace(
            assets={"sprite": {"versions": [{"version": n, "commit": oid}
                                            for n, oid in enumerate((root, left, right, merge), 1)]}},
            sources={"sprite": {"jeu"}}, changed=set())
        versions = target.assets["sprite"]["versions"]

        def record(git, mirror):
            _record_causality(target, [SimpleNamespace(repo="jeu", members=[(None, mirror, False, None)])], git)

        record(self.git, complete)
        self.assertEqual([entry["causalOrder"] for entry in versions],
                         ["ambiguous", "incomparable", "incomparable", "ambiguous"])
        self.assertEqual(target.changed, {"sprite"})
        target.changed.clear()

        def run_with_missing_branch(*args, **kwargs):
            if args == ("cat-file", "-e", merge + "^{commit}"):
                return b""
            if args == ("merge-base", "--all", root, merge):
                return root.encode()
            if args == ("merge-base", "--all", left, merge):
                return left.encode()
            return self.git.run(*args, **kwargs)

        record(Mock(run=Mock(side_effect=run_with_missing_branch)), partial)
        for entry in versions:
            self.assertIsNone(entry["causalPrevious"], entry)
            self.assertIsNone(entry["causalNext"], entry)
            self.assertEqual(entry["causalOrder"], "unknown", entry)
        self.assertEqual(target.changed, {"sprite"})

        record(self.git, complete)
        self.assertEqual([entry["causalOrder"] for entry in versions],
                         ["ambiguous", "incomparable", "incomparable", "ambiguous"])

    def test_m15_la_copie_en_avance_sans_continuite_est_signalee(self):
        previous = self.commit("Dernière tête importée")
        eligible_commit = self.commit("Copie éligible", previous)
        ahead_commit = self.commit("Copie avancée", eligible_commit)
        older = self.mirror("older.git", eligible_commit)
        ahead = self.mirror("ahead.git", ahead_commit, depth=2)
        github = Copy("jeu", "game", ("jeu",), "github", "https://github.com/fixture/jeu", "public", "main")
        local = Copy("jeu", "game", ("jeu",), "local", str(older), "private", "main")
        prepared = {github.key: (ahead, {"commit": ahead_commit}), local.key: (older, {"commit": eligible_commit})}
        eligible = {key for key, (mirror, ref) in prepared.items()
                    if _descends_from_all(self.git, mirror, ref["commit"], [previous])}
        self.assertEqual(eligible, {local.key})
        self.assertTrue(_descends_from_all(self.git, ahead, ahead_commit, [eligible_commit]))

        skipped, notices = _divergences([github, local], prepared, self.git, eligible=eligible)

        self.assertEqual(set(prepared) - skipped, {local.key})
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["importedProvider"], "local")
        self.assertEqual(notices[0]["importedCommit"], eligible_commit)
        self.assertEqual(notices[0]["ignored"], [{"provider": "github", "commit": ahead_commit}])
