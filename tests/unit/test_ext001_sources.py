"""EXT-001 P1/P2 (EXT-08 à EXT-11, autres sources) : OpenGameArt, LPC, itch.io, synchronisation incrémentale, liste
blanche — hors ligne : le web est simulé (robots.txt, pages, flux, API GitHub), aucune requête réelle.

Les règles vérifiées : robots.txt respecté pour le registre ET pour les agents IA qui le pilotent, un seul en-tête
(User-Agent générique), licence jamais présumée, licences mixtes conservées, obligations LPC conservées jusqu'aux
crédits, téléchargement itch.io laissé à un geste humain, revue obligatoire pour une source P2.
"""
import io
import json
import os
import urllib.error
from pathlib import Path
from unittest import TestCase, mock

from tests.unit.test_ext001 import CC0, ExterneFixture, png

BYSA3 = "Attribution-ShareAlike 3.0 Unported\nhttps://creativecommons.org/licenses/by-sa/3.0/\n"
CC_BY3 = "Creative Commons Attribution 3.0 Unported\nhttps://creativecommons.org/licenses/by/3.0/\n"
ROBOTS_OUVERT = "User-agent: *\nDisallow: /search\nDisallow: /game/download/\n"
ROBOTS_ANTI_IA = "User-agent: Claude-User\nUser-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nCrawl-delay: 10\n"
SHA = "a" * 40

OGA_PAGE = """<html><body><h1>Kitchen tools</h1>
<div class="field field-name-author-submitter"><a href="/users/chef">Chef Pixel</a></div>
<div class="field field-name-field-art-tags"><a href="/t/kitchen">kitchen</a><a href="/t/whisk">whisk</a></div>
<div class="field field-name-field-art-licenses"><div class="license-name">CC-BY-SA 3.0</div>
<div class="license-name">CC0</div></div>
<div class="field field-name-field-art-files"><a href="https://opengameart.org/sites/default/files/kitchen.zip">kitchen.zip</a></div>
</body></html>"""

CREDITS = ('filename,notes,authors,licenses,urls\n'
           '"props/tree.png","based on LPC" ,"Alice,Bob (bobart)" ,"OGA-BY 3.0,CC-BY-SA 3.0,GPL 3.0" ,'
           '"https://opengameart.org/content/lpc-tree,https://opengameart.org/content/lpc-base"\n'
           '"props/rock.png","" ,"Carol" ,"CC-BY-SA 3.0" ,"https://opengameart.org/content/rock"\n'
           '"README.md","" ,"x" ,"CC0" ,""\n')


def flux(items):
    lignes = "".join(f"<item><title>{t} [Free]</title><plainTitle>{t}</plainTitle><link>{l}</link>"
                     f"<price>$0.00</price><updateDate>{u}</updateDate></item>" for t, l, u in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{lignes}</channel></rss>'


class FauxWeb:
    """urlopen simulé : URL → (statut, corps, en-têtes). Note chaque requête (URL et en-têtes)."""

    def __init__(self, pages):
        self.pages, self.requetes = dict(pages), []

    def __call__(self, request, timeout=None):
        url = request if isinstance(request, str) else request.full_url
        entetes = {} if isinstance(request, str) else dict(request.header_items())
        self.requetes.append((url, entetes))
        if url not in self.pages:
            if url.endswith("/robots.txt"):
                raise urllib.error.HTTPError(url, 404, "absent", {}, None)
            raise urllib.error.HTTPError(url, 404, "absent", {}, None)
        statut, corps, en_tetes = self.pages[url]
        corps = corps.encode() if isinstance(corps, str) else corps
        if statut == 304 or (en_tetes.get("ETag") and entetes.get("If-none-match") == en_tetes["ETag"]):
            raise urllib.error.HTTPError(url, 304, "inchangé", en_tetes, None)
        reponse = io.BytesIO(corps)
        reponse.status, reponse.headers = statut, en_tetes
        reponse.__enter__ = lambda *a: reponse
        reponse.__exit__ = lambda *a: False
        return _Reponse(corps, statut, en_tetes)


class _Reponse(io.BytesIO):
    def __init__(self, corps, statut, en_tetes):
        super().__init__(corps)
        self.status, self.headers = statut, en_tetes

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def zip_de(fichiers):
    import zipfile
    flux_ = io.BytesIO()
    with zipfile.ZipFile(flux_, "w") as z:
        for nom, data in fichiers.items():
            z.writestr(nom, data)
    return flux_.getvalue()


class SourcesFixture(ExterneFixture):
    def web(self, pages):
        faux = FauxWeb(pages)
        patcher = mock.patch("urllib.request.urlopen", faux)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Pas d'attente réelle entre deux requêtes polies.
        sommeil = mock.patch("time.sleep", lambda s: None)
        sommeil.start()
        self.addCleanup(sommeil.stop)
        return faux

    def index_de(self, fournisseur):
        return json.loads((self.root / "external" / fournisseur / "index.json").read_text())

    def plan_de(self, fournisseur, ident, *extra, code=0):
        chemin = self.root / f"plan-{fournisseur}.json"
        res = self.ext("plan-import", "--provider", fournisseur, "--id", ident, "--out", str(chemin), *extra,
                       code=code)
        return chemin, res


class ClientPoli(SourcesFixture, TestCase):
    def test_robots_refuse_un_agent_ia_meme_sous_un_user_agent_generique(self):
        from tools.external.client import Client, RobotsRefusal
        self.web({"https://anti.example/robots.txt": (200, ROBOTS_ANTI_IA, {}),
                  "https://anti.example/content/x": (200, "page", {})})
        with self.assertRaises(RobotsRefusal) as refus:
            Client().get("https://anti.example/content/x")
        self.assertIn("Claude-User", str(refus.exception))

    def test_un_seul_en_tete_generique_et_jamais_de_jeton(self):
        from tools.external.client import Client, USER_AGENT
        from tools.external.adapters import ProviderUnavailable
        faux = self.web({"https://ok.example/robots.txt": (200, ROBOTS_OUVERT, {}),
                         "https://ok.example/a": (200, "corps", {})})
        statut, corps, _ = Client().get("https://ok.example/a")
        self.assertEqual((statut, corps), (200, b"corps"))
        for _, entetes in faux.requetes:
            self.assertEqual(entetes, {"User-agent": USER_AGENT})
        self.assertNotRegex(USER_AGENT, r"@|gmail|david|sevin")
        with self.assertRaises(ProviderUnavailable):
            Client().get("https://ok.example/a?token=abc")


class OpenGameArt(SourcesFixture, TestCase):
    """EXT-08 : licences mixtes gérées ; import automatique seulement pour licence confirmée et téléchargement permis."""

    def pages(self, robots=ROBOTS_OUVERT, archive=None):
        return {"https://opengameart.org/robots.txt": (200, robots, {}),
                "https://opengameart.org/content/kitchen-tools": (200, OGA_PAGE, {"Last-Modified": "Mon, 01 Jan 2024"}),
                "https://opengameart.org/sites/default/files/kitchen.zip":
                    (200, archive or zip_de({"whisk.png": png((9, 9, 9, 255)), "LICENSE.txt": CC0}), {})}

    def test_page_a_deux_licences_options_conservees_et_ordonnees(self):
        from tools.external.sources import parse_oga_page
        row = parse_oga_page(OGA_PAGE, "https://opengameart.org/content/kitchen-tools")
        self.assertEqual(row["licenseOptions"], ["CC0-1.0", "CC-BY-SA-3.0"])
        self.assertEqual((row["author"], row["title"]), ("Chef Pixel", "Kitchen tools"))
        self.assertEqual(row["metadataConfidence"], "inferred")       # annoncée, pas prouvée

    def test_licence_mixte_verifiee_par_le_texte_de_l_archive(self):
        self.web(self.pages())
        self.ext("refresh", "--provider", "opengameart", "--page", "https://opengameart.org/content/kitchen-tools")
        _, plan = self.plan_de("opengameart", "kitchen-tools")
        self.assertEqual((plan["plan"]["license"]["verification"], plan["plan"]["license"]["spdxId"]),
                         ("verified", "CC0-1.0"))

    def test_seule_l_option_copyleft_prouvee_export_public_bloque(self):
        self.web(self.pages(archive=zip_de({"whisk.png": png((9, 9, 9, 255)), "LICENSE.txt": BYSA3})))
        self.ext("refresh", "--provider", "opengameart", "--page", "https://opengameart.org/content/kitchen-tools")
        _, plan = self.plan_de("opengameart", "kitchen-tools", "--target", "public")
        self.assertEqual(plan["plan"]["license"]["spdxId"], "CC-BY-SA-3.0")
        self.assertEqual(plan["plan"]["decision"]["licenseStatus"], "incompatible")

    def test_robots_anti_ia_collecte_refusee_jamais_aucun_resultat(self):
        self.web(self.pages(robots=ROBOTS_ANTI_IA))
        res = self.ext("refresh", "--provider", "opengameart", "--page",
                       "https://opengameart.org/content/kitchen-tools", code=4)
        self.assertEqual(res["error"], "provider-unavailable")
        self.assertIn("robots.txt", res["message"])
        self.assertFalse((self.root / "external" / "opengameart" / "index.json").exists())


class Lpc(SourcesFixture, TestCase):
    """EXT-09 : attributions et obligations conservées, par fichier, jusqu'aux crédits d'un export public."""

    def pages(self):
        base = f"https://raw.githubusercontent.com/LiberatedPixelCup/Universal-LPC-Spritesheet-Character-Generator/{SHA}"
        return {"https://api.github.com/robots.txt": (404, "", {}),
                "https://api.github.com/repos/LiberatedPixelCup/Universal-LPC-Spritesheet-Character-Generator/commits/HEAD":
                    (200, json.dumps({"sha": SHA}), {}),
                f"{base}/CREDITS.csv": (200, CREDITS, {}),
                f"{base}/spritesheets/props/tree.png": (200, png((1, 120, 1, 255)), {})}

    def test_index_par_fichier_avec_licences_au_choix_et_auteurs(self):
        self.web(self.pages())
        self.ext("refresh", "--provider", "lpc", "--query", "")
        packs = {p["title"]: p for p in self.index_de("lpc")["packs"]}
        self.assertEqual(sorted(packs), ["props/rock.png", "props/tree.png"])     # README.md n'est pas un média
        arbre = packs["props/tree.png"]
        self.assertEqual(arbre["licenseOptions"], ["LicenseRef-OGA-BY-3.0", "CC-BY-SA-3.0", "GPL-3.0-only"])
        self.assertEqual(arbre["credits"]["authors"], ["Alice", "Bob (bobart)"])
        self.assertEqual(arbre["sourceVersion"], SHA)

    def test_import_puis_export_public_credite_chaque_auteur(self):
        self.web(self.pages())
        self.ext("refresh", "--provider", "lpc", "--query", "tree")
        chemin, plan = self.plan_de("lpc", "props-tree.png", "--target", "public")
        self.assertEqual((plan["plan"]["license"]["verification"], plan["plan"]["license"]["spdxId"]),
                         ("verified", "LicenseRef-OGA-BY-3.0"))
        self.ext("import", "--plan", str(chemin))
        (asset_id, fiche), = self.externals().items()
        externe = fiche["provenance"]["external"]
        self.assertEqual(externe["licenseOptions"], ["LicenseRef-OGA-BY-3.0", "CC-BY-SA-3.0", "GPL-3.0-only"])
        self.assertEqual(externe["credits"]["authors"], ["Alice", "Bob (bobart)"])
        destination = self.dehors() / "export"
        code, res = self.cli("publish", asset_id, "--target", "public", "--dest", str(destination))
        self.assertEqual(code, 0, res)
        credits = (destination / "THIRD_PARTY_ASSETS.md").read_text()
        for attendu in ("Alice", "Bob (bobart)", "LicenseRef-OGA-BY-3.0", "https://opengameart.org/content/lpc-tree"):
            self.assertIn(attendu, credits)


class Itchio(SourcesFixture, TestCase):
    """EXT-10 : découverte par le flux public ; licence jamais présumée ; téléchargement = geste humain."""

    def pages(self, items, etag="v1"):
        return {"https://itch.io/robots.txt": (200, ROBOTS_OUVERT, {}),
                "https://itch.io/game-assets/free/tag-cc0.xml": (200, flux(items), {"ETag": etag})}

    def test_etiquette_cc0_de_l_auteur_n_est_pas_une_licence(self):
        self.web(self.pages([("Kitchen Pack", "https://chef.itch.io/kitchen-pack", "2024-01-01")]))
        self.ext("refresh", "--provider", "itchio", "--query", "cc0")
        (pack,) = self.index_de("itchio")["packs"]
        self.assertEqual((pack["licenseSpdx"], pack["metadataConfidence"], pack["downloadUrl"]),
                         (None, "unknown", None))
        self.assertIn("etiquette-auteur-cc0", pack["tags"])
        res = self.ext("plan-import", "--provider", "itchio", "--id", pack["externalId"], code=4)
        self.assertEqual(res["error"], "provider-unavailable")

    def test_robots_d_itch_ferme_le_telechargement_aux_robots(self):
        from tools.external.client import Client, RobotsRefusal
        self.web(self.pages([]))
        with self.assertRaises(RobotsRefusal):
            Client().check("https://itch.io/game/download/123")


class SynchroIncrementale(SourcesFixture, TestCase):
    """EXT-11 : modifications et retraits détectés ; requête conditionnelle (ETag) : un 304 ne relit rien."""

    def test_etag_puis_nouveau_retire_et_modifie(self):
        faux = self.web({"https://itch.io/robots.txt": (200, ROBOTS_OUVERT, {}),
                         "https://itch.io/game-assets/free/tag-cc0.xml":
                             (200, flux([("A", "https://a.itch.io/a", "1"), ("B", "https://b.itch.io/b", "1")]),
                              {"ETag": "v1"})})
        self.ext("refresh", "--provider", "itchio", "--query", "cc0")
        self.ext("refresh", "--provider", "itchio", "--query", "cc0")
        conditionnelles = [e for u, e in faux.requetes if u.endswith("tag-cc0.xml")]
        self.assertEqual(conditionnelles[-1].get("If-none-match"), "v1")
        faux.pages["https://itch.io/game-assets/free/tag-cc0.xml"] = (
            200, flux([("A", "https://a.itch.io/a", "2"), ("C", "https://c.itch.io/c", "1")]), {"ETag": "v2"})
        res = self.ext("sync", "--provider", "itchio", "--incremental", "--query", "cc0")
        self.assertEqual(res["changes"], {"new": ["c-c"], "removed": ["b-b"], "updated": ["a-a"]})


class ListeBlanche(SourcesFixture, TestCase):
    """Autres sources (P2) : liste blanche ajoutée par PR, revue de licence et de sécurité exigée."""

    def liste(self, revue=True):
        entree = {"id": "icones", "kind": "github-repo", "repo": "exemple/icones", "ref": SHA, "license": "CC-BY-3.0",
                  "licenseFile": "license.txt", "paths": r"\.png$", "author": "Exemple"}
        if revue:
            entree["review"] = {"licence": "CC BY 3.0 lue dans license.txt", "securite": "PNG seuls, aucun script",
                                "par": "registre", "date": "2026-11-22", "pr": "forge#0"}
        (self.root / "external").mkdir(exist_ok=True)
        (self.root / "external" / "whitelist.json").write_text(json.dumps({"schemaVersion": "1.0",
                                                                          "sources": [entree]}))

    def pages(self):
        raw = f"https://raw.githubusercontent.com/exemple/icones/{SHA}"
        return {f"https://api.github.com/repos/exemple/icones/git/trees/{SHA}?recursive=1":
                    (200, json.dumps({"tree": [{"path": "a/epee.png", "type": "blob"},
                                               {"path": "run.sh", "type": "blob"}]}), {}),
                f"{raw}/a/epee.png": (200, png((200, 0, 0, 255)), {}), f"{raw}/license.txt": (200, CC_BY3, {})}

    def test_sans_revue_refusee(self):
        self.liste(revue=False)
        self.web(self.pages())
        res = self.ext("refresh", "--provider", "whitelist", "--query", "", code=4)
        self.assertIn("sans revue", res["message"])

    def test_avec_revue_licence_prouvee_au_meme_commit(self):
        self.liste()
        self.web(self.pages())
        self.ext("refresh", "--provider", "whitelist", "--query", "")
        (pack,) = self.index_de("whitelist")["packs"]
        self.assertEqual(pack["title"], "a/epee.png")                      # run.sh n'est pas un média
        _, plan = self.plan_de("whitelist", pack["externalId"])
        self.assertEqual((plan["plan"]["license"]["verification"], plan["plan"]["license"]["evidence"]),
                         ("verified", "license.txt"))
