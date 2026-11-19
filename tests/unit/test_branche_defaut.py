"""Une source se lit sur sa branche par défaut, jamais sur la branche extraite (HL-538, 19/11).

Défaut constaté le 19/11 : la copie locale de capsule-panic était extraite sur une branche de
travail non fusionnée ; `scan-repos` lisait HEAD et aurait enregistré, pour une même source,
les sprites de `main` (GitHub, Forgejo) ET ceux de la branche de travail (copie locale).
Auteur : Claude (correctif de l'orchestrateur), tests écrits avant le code.
"""

import json
import unittest

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M

ROUGE = (200, 30, 30, 255)


def _sources(world, mutate):
    document = C.lire_json(world.registre / C.SOURCES)
    mutate(document)
    (world.registre / C.SOURCES).write_text(json.dumps(document), encoding="utf-8")


def _branche(document, branch="main"):
    for source in document["sources"]:
        for copy in source["copies"]:
            copy["defaultBranch"] = branch


def _miroir(world, provider, url):
    """Copie « distante » simulée : miroir nu dans le cache, origine réécrite vers l'URL autorisée."""
    mirror = world.cache / provider / "jeu-a.git"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    world.git(world.depot("jeu-a"), "clone", "--mirror", "--no-local", ".", str(mirror))
    world.git(mirror, "remote", "set-url", "origin", url)
    return mirror


def _miroir_local(world):
    """Avec --no-fetch, le miroir de la copie locale doit exister : clone de TOUTES ses branches,
    HEAD compris (la branche extraite), comme le ferait un premier scan."""
    mirror = world.cache / "local" / "jeu-a.git"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    world.git(world.depot("jeu-a"), "clone", "--mirror", "--no-local", world.depot("jeu-a").as_uri(), str(mirror))


def _avec_copies_distantes(world):
    _miroir(world, "github", "https://github.com/fixture/jeu-a")
    _miroir(world, "forgejo", "https://forgejo.pingfr.duckdns.org/fixture/jeu-a")

    def mutate(document):
        source = next(e for e in document["sources"] if e["name"] == "jeu-a")
        source["copies"].extend([
            {"provider": "github", "url": "https://github.com/fixture/jeu-a", "visibility": "public"},
            {"provider": "forgejo", "url": "https://forgejo.pingfr.duckdns.org/fixture/jeu-a",
             "visibility": "private"}])
        _branche(document)
    _sources(world, mutate)


def _branche_de_travail(world, name="palette-sans-biais"):
    """Branche non fusionnée qui recolore le fouet, laissée EXTRAITE dans la copie locale."""
    depot = world.depot("jeu-a")
    world.git(depot, "checkout", "-q", "-b", name)
    (depot / M.FOUET).write_bytes(M.png(M.uni(16, 16, ROUGE)))
    world.git(depot, "add", "--", M.FOUET)
    world.git(depot, "commit", "-q", "-m", "Recoloration non fusionnée", date="2026-03-02T10:00:00+00:00")
    return world.git(depot, "rev-parse", "HEAD")


class BrancheParDefaut(unittest.TestCase):
    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        self.main = self.world.commits["jeu-a"]

    def test_copie_locale_lue_sur_la_branche_par_defaut_et_non_sur_head(self):
        _sources(self.world, _branche)
        travail = _branche_de_travail(self.world)
        result = self.world.scan("--only", "jeu-a")
        self.assertEqual(result.code, C.OK, str(result))
        _, asset = C.asset_par_chemin(self.world.registre, "jeu-a", M.FOUET)
        commits = {loc["commit"] for loc in asset["files"]["locations"]}
        self.assertEqual(commits, {self.main}, "le fouet doit venir de main, pas de la branche extraite")
        self.assertFalse(any(loc["commit"] == travail for a in C.assets(self.world.registre).values()
                             for loc in a["files"]["locations"]), "aucun emplacement au commit de travail")
        refs = C.lire_json(self.world.registre / "catalog" / "scan-references.json")["references"]
        local = next(r for r in refs if r["name"] == "jeu-a")
        self.assertEqual((local["branch"], local["commit"]), ("main", self.main))

    def test_branche_par_defaut_absente_code_4_sans_repli_sur_head(self):
        _sources(self.world, lambda d: _branche(d, "trunk"))
        result = self.world.scan("--only", "jeu-a")
        self.assertEqual(result.code, C.ERREUR_ES, str(result))
        self.assertIn("trunk", result.stdout + result.stderr)
        self.assertEqual(C.assets(self.world.registre), {}, "aucun repli silencieux sur HEAD")

    def test_source_sans_branche_par_defaut_refusee(self):
        def strip(document):
            for source in document["sources"]:
                for copy in source["copies"]:
                    copy.pop("defaultBranch", None)
        _sources(self.world, strip)
        validate = self.world.ctl(["validate", "--json"])
        self.assertEqual(validate.code, C.ECHEC, str(validate))
        scan = self.world.scan("--only", "jeu-a")
        self.assertNotEqual(scan.code, C.OK, str(scan))
        self.assertEqual(C.assets(self.world.registre), {})
        _sources(self.world, _branche)
        self.assertEqual(self.world.ctl(["validate", "--json"]).code, C.OK)


class CopiesDUneMemeSource(unittest.TestCase):
    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        self.main = self.world.commits["jeu-a"]

    def test_trois_copies_au_meme_sha_une_seule_version(self):
        _avec_copies_distantes(self.world)
        _branche_de_travail(self.world)  # extraite localement : ne doit rien changer
        _miroir_local(self.world)
        result = self.world.scan("--no-fetch", "--only", "jeu-a")
        self.assertEqual(result.code, C.OK, str(result))
        _, asset = C.asset_par_chemin(self.world.registre, "jeu-a", M.FOUET)
        self.assertEqual({(loc["provider"], loc["commit"]) for loc in asset["files"]["locations"]},
                         {(p, self.main) for p in ("github", "forgejo", "local")})
        report = C.lire_json(self.world.registre / "generated/reports/migration.json")["repositories"]
        repo = next(r for r in report if r["name"] == "jeu-a")
        self.assertFalse(repo["divergent"], repo)

    def test_copie_en_avance_importee_seule_les_autres_signalees(self):
        # Locale en avance sur GitHub et Forgejo (même histoire) : c'est elle qui porte le travail, elle est
        # importée ; les copies en retard sont signalées « divergentes », jamais une seconde version (19/11).
        _avec_copies_distantes(self.world)
        depot = self.world.depot("jeu-a")
        (depot / M.FOUET).write_bytes(M.png(M.uni(16, 16, ROUGE)))
        self.world.git(depot, "add", "--", M.FOUET)
        self.world.git(depot, "commit", "-q", "-m", "Local en avance", date="2026-03-02T10:00:00+00:00")
        ahead = self.world.git(depot, "rev-parse", "HEAD")
        _miroir_local(self.world)
        result = self.world.scan("--no-fetch", "--only", "jeu-a")
        self.assertEqual(result.code, C.OK, str(result))
        _, asset = C.asset_par_chemin(self.world.registre, "jeu-a", M.FOUET)  # une seule version
        self.assertEqual({loc["commit"] for loc in asset["files"]["locations"] if not loc.get("releaseOnly")}, {ahead})
        report = C.lire_json(self.world.registre / "generated/reports/migration.json")["repositories"]
        repo = next(r for r in report if r["name"] == "jeu-a")
        self.assertTrue(repo["divergent"])
        for provider in ("github", "forgejo"):
            self.assertIn({"provider": provider, "commit": self.main, "imported": False}, repo["divergentCopies"])
        self.assertIn({"provider": "local", "commit": ahead, "imported": True}, repo["divergentCopies"])
        self.assertIn("copies divergentes", json.dumps(result.json, ensure_ascii=False).lower())

    def test_histoires_divergentes_priorite_github(self):
        # GitHub porte un commit que la locale n'a pas, et inversement : aucune copie n'est « en avance ».
        _avec_copies_distantes(self.world)
        depot = self.world.depot("jeu-a")
        self.world.git(depot, "checkout", "-q", "-b", "fourche")
        (depot / M.FOUET).write_bytes(M.png(M.uni(16, 16, (10, 200, 10, 255))))
        self.world.git(depot, "add", "--", M.FOUET)
        self.world.git(depot, "commit", "-q", "-m", "Fourche GitHub", date="2026-03-02T09:00:00+00:00")
        fourche = self.world.git(depot, "rev-parse", "HEAD")
        self.world.git(self.world.cache / "github" / "jeu-a.git", "fetch", "-q", str(depot),
                       "+refs/heads/fourche:refs/heads/main")
        self.world.git(depot, "checkout", "-q", "main")
        (depot / M.FOUET).write_bytes(M.png(M.uni(16, 16, ROUGE)))
        self.world.git(depot, "add", "--", M.FOUET)
        self.world.git(depot, "commit", "-q", "-m", "Local en avance", date="2026-03-02T10:00:00+00:00")
        _miroir_local(self.world)
        result = self.world.scan("--no-fetch", "--only", "jeu-a")
        self.assertEqual(result.code, C.OK, str(result))
        _, asset = C.asset_par_chemin(self.world.registre, "jeu-a", M.FOUET)
        self.assertEqual({loc["commit"] for loc in asset["files"]["locations"] if not loc.get("releaseOnly")}, {fourche})
        notice = result.json["divergentSources"][0]
        self.assertEqual((notice["importedProvider"], notice["reason"]), ("github", "forked"))

if __name__ == "__main__":
    unittest.main()
