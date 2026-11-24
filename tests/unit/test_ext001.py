"""EXT-001 — bibliothèques externes : tests d'acceptation EXT-T01 à EXT-T12, hors ligne, sur fixtures (EXT-07).

Le fournisseur Kenney est simulé par un index JSON et des archives ZIP construites ici (file://) : aucune
requête réseau, aucun affichage.
"""
import contextlib
import copy
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
from unittest import TestCase, mock

from PIL import Image

from tests.unit.test_oracles import ASSET, ASSET_ID, CatalogueFixture

CC0 = "Creative Commons Zero, CC0 1.0 Universal\nhttps://creativecommons.org/publicdomain/zero/1.0/\n"
BYSA = "Attribution-ShareAlike 4.0 International\nhttps://creativecommons.org/licenses/by-sa/4.0/\n"


def png(color, size=(16, 16)):
    stream = io.BytesIO()
    image = Image.new("RGBA", size, color)
    image.putpixel((0, 0), (0, 0, 0, 0))
    image.save(stream, "PNG")
    return stream.getvalue()


class ExterneFixture(CatalogueFixture):
    def setUp(self):
        super().setUp()
        self.packs = self.root / "packs"
        self.packs.mkdir()
        self.index = self.root / "kenney-index.json"
        self.rows = []
        patcher = mock.patch.dict(os.environ, {"ASSETCTL_EXTERNAL_INDEX_KENNEY": str(self.index)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def pack(self, pack_id, files, license_spdx="CC0-1.0", version="1.0", tags=("kitchen",), title=None,
             extra=None):
        archive = self.packs / f"{pack_id}-{version}.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            for name, data in files.items():
                if isinstance(data, zipfile.ZipInfo):
                    zipped.writestr(data, b"x")
                else:
                    zipped.writestr(name, data)
        row = {"externalId": pack_id, "title": title or pack_id.replace("-", " "), "sourceUrl":
               f"https://kenney.nl/assets/{pack_id}", "downloadUrl": archive.as_uri(), "author": "Kenney",
               "licenseSpdx": license_spdx, "licenseEvidenceUrl": f"https://kenney.nl/assets/{pack_id}",
               "tags": list(tags), "sourceVersion": version, **(extra or {})}
        self.rows = [r for r in self.rows if r["externalId"] != pack_id] + [row]
        self.write_index()
        return archive

    def write_index(self, rows=None, path=None):
        (path or self.index).write_text(json.dumps({"provider": "kenney", "packs": self.rows if rows is None else rows}))

    def ext(self, *args, code=0):
        result = self.cli("external", *args)
        self.assertEqual(result[0], code, result[1])
        return result[1]

    def plan(self, pack_id, *extra, code=0):
        path = self.root / f"plan-{pack_id}.json"
        payload = self.ext("plan-import", "--provider", "kenney", "--id", pack_id, "--out", str(path), *extra, code=code)
        return path, payload

    def dehors(self):
        """Dossier hors de tout dépôt Git (une destination dans le dépôt du registre est refusée)."""
        import tempfile
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        return Path(dossier.name)

    def externals(self):
        return {p.stem: json.loads(p.read_text()) for p in (self.root / "catalog" / "assets").glob("*.json")
                if json.loads(p.read_text())["provenance"]["type"] == "external"}

    def empreinte_catalogue(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in (self.root / "catalog").rglob("*")
                if p.is_file()}


class EXT001Acceptation(ExterneFixture, TestCase):
    def test_T01_asset_interne_compatible_aucune_creation_ni_import(self):
        self.pack("kitchen-kit", {"fouet.png": png((200, 0, 0, 255)), "License.txt": CC0}, tags=("fouet",))
        avant = self.empreinte_catalogue()
        decision = self.ext("decide", "--query", "fouet")["decision"]
        self.assertEqual((decision["action"], decision["candidateId"]), ("reuse", ASSET_ID))
        self.assertEqual(decision["consulted"][0], {"source": "internal", "id": ASSET_ID})
        self.assertEqual(self.empreinte_catalogue(), avant)

    def test_T02_cc0_verifie_import_permis_preuve_conservee(self):
        archive = self.pack("kitchen-kit", {"Sprites/whisk.png": png((10, 120, 200, 255)), "License.txt": CC0})
        plan, payload = self.plan("kitchen-kit")
        self.assertEqual(payload["plan"]["decision"]["action"], "import")
        self.assertEqual(payload["plan"]["license"]["verification"], "verified")
        result = self.ext("import", "--plan", str(plan))
        self.assertEqual(result["newAssets"], 1)
        (asset,) = self.externals().values()
        decision = asset["creation"]["importJob"]["decision"]
        self.assertEqual(decision["action"], "import")
        self.assertTrue(decision["rationale"].strip() and decision["consulted"])
        self.assertEqual((asset["license"], asset["status"]), ("CC0-1.0", "active"))
        external = asset["provenance"]["external"]
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(external["archiveSha256"], digest)
        self.assertEqual((self.root / external["archivePath"]).read_bytes(), archive.read_bytes())
        self.assertIn("CC0", (self.root / external["license"]["textPath"]).read_text())
        self.assertEqual(asset["licenseEvidence"]["method"], "external-license-file")
        for field in ("provider", "sourceUrl", "observedAt", "importedAt", "pathInArchive", "restrictions"):
            self.assertIn(field, external)
        self.assertEqual(self.cli("validate")[0], 0, self.cli("validate")[1])

    def test_T03_licence_non_confirmee_publication_refusee(self):
        # L'index annonce CC0 ; l'archive ne contient aucun texte qui le confirme.
        self.pack("mystery-pack", {"coin.png": png((250, 200, 0, 255)), "readme.txt": "Free assets!"})
        plan, payload = self.plan("mystery-pack")
        self.assertEqual(payload["plan"]["license"]["verification"], "unknown")
        self.assertEqual(payload["plan"]["decision"]["action"], "block")
        avant = self.empreinte_catalogue()
        self.assertEqual(self.ext("import", "--plan", str(plan), code=3)["error"], "decision-not-import")
        self.assertEqual(self.empreinte_catalogue(), avant)

    def test_T04_copyleft_vers_un_export_public_bloque_et_documente(self):
        self.pack("lpc-like", {"hero.png": png((0, 200, 0, 255)), "LICENSE.txt": BYSA}, license_spdx="CC-BY-SA-4.0")
        _, public = self.plan("lpc-like", "--target", "public")
        decision = public["plan"]["decision"]
        self.assertEqual((decision["action"], decision["licenseStatus"]), ("block", "incompatible"))
        self.assertIn("copyleft", decision["rationale"])
        plan, prive = self.plan("lpc-like")
        self.assertEqual(prive["plan"]["decision"]["action"], "import")
        self.ext("import", "--plan", str(plan))
        (asset_id, asset), = self.externals().items()
        self.assertEqual(asset["publicExport"], "forbidden")
        destination = self.dehors() / "export"
        code, refus = self.cli("publish", asset_id, "--target", "public", "--dest", str(destination))
        self.assertEqual(code, 3, refus)
        self.assertNotIn("autre dépôt", refus["message"])
        self.assertFalse(destination.exists())
        self.assertEqual(self.cli("publish", asset_id, "--target", "private", "--dest", str(destination))[0], 0)

    def test_T05_meme_import_deux_fois_aucun_doublon(self):
        self.pack("kitchen-kit", {"a.png": png((1, 2, 3, 255)), "b.png": png((4, 5, 6, 255)), "License.txt": CC0})
        plan, _ = self.plan("kitchen-kit")
        self.assertEqual(self.ext("import", "--plan", str(plan))["newAssets"], 2)
        avant = self.empreinte_catalogue()
        binaires = sorted((self.root / "sources" / "external").rglob("*"))
        self.assertEqual(self.ext("import", "--plan", str(plan))["newAssets"], 0)
        self.assertEqual(self.empreinte_catalogue(), avant)
        self.assertEqual(sorted((self.root / "sources" / "external").rglob("*")), binaires)

    def test_T06_archive_traversante_rejetee_et_mise_en_quarantaine(self):
        archive = self.pack("evil-pack", {"../../escape.png": png((9, 9, 9, 255)), "License.txt": CC0})
        avant = self.empreinte_catalogue()
        _, refus = self.plan("evil-pack", code=3)
        self.assertEqual(refus["error"], "unsafe-archive")
        self.assertTrue(any("traversant" in p for p in refus["problems"]))
        quarantaine = self.root / refus["quarantine"]
        self.assertTrue(quarantaine.is_file())
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertTrue((quarantaine.parent / f"{digest}.zip").is_file())
        self.assertEqual(self.empreinte_catalogue(), avant)

    def test_T06_lien_symbolique_et_executable_refuses(self):
        lien = zipfile.ZipInfo("link.png")
        lien.external_attr = (0o120777 << 16)
        self.pack("links", {"link.png": lien, "License.txt": CC0})
        self.assertTrue(any("lien symbolique" in p for p in self.plan("links", code=3)[1]["problems"]))
        self.pack("exe", {"tool.exe": b"MZ\x90\x00", "License.txt": CC0})
        self.assertTrue(any("exécutable" in p for p in self.plan("exe", code=3)[1]["problems"]))
        self.pack("masked", {"fake.png": b"MZ\x90\x00" + bytes(20), "License.txt": CC0})
        self.assertTrue(any("exécutable" in p for p in self.plan("masked", code=3)[1]["problems"]))

    def test_T07_fournisseur_indisponible_aucun_faux_negatif(self):
        self.index.unlink(missing_ok=True)
        resultat = self.ext("search", "--query", "whisk")
        self.assertEqual(resultat["externalSearchStatus"], "unavailable")
        self.assertEqual(resultat["providers"]["kenney"]["status"], "unavailable")
        decision = self.ext("decide", "--query", "zebre introuvable")["decision"]
        self.assertEqual((decision["action"], decision["externalSearchStatus"]), ("block", "unavailable"))
        self.assertIn("aucune absence", decision["rationale"])

    def test_T08_fichier_identique_deux_provenances(self):
        meme = png((77, 66, 55, 255))
        self.pack("pack-a", {"coin.png": meme, "License.txt": CC0})
        self.pack("pack-b", {"gold/coin.png": meme, "License.txt": CC0})
        for pack_id in ("pack-a", "pack-b"):
            self.ext("import", "--plan", str(self.plan(pack_id)[0]))
        externes = self.externals()
        self.assertEqual(len(externes), 2)
        self.assertEqual({a["provenance"]["external"]["externalPackId"] for a in externes.values()}, {"pack-a", "pack-b"})
        self.assertEqual(len({a["files"]["registry"] for a in externes.values()}), 1)
        self.assertEqual(len(list((self.root / "sources" / "external" / "sha256").iterdir())), 1)

    def test_T09_changement_de_licence_alerte_versions_historisees(self):
        self.pack("kitchen-kit", {"pan.png": png((5, 5, 5, 255)), "License.txt": CC0})
        self.pack("old-pack", {"pot.png": png((6, 6, 6, 255)), "License.txt": CC0})
        for pack_id in ("kitchen-kit", "old-pack"):
            self.ext("import", "--plan", str(self.plan(pack_id)[0]))
        nouvel = self.root / "nouvel-index.json"
        rows = [dict(r, licenseSpdx="CC-BY-4.0", sourceVersion="2.0") for r in self.rows if r["externalId"] == "kitchen-kit"]
        self.write_index(rows, nouvel)
        simulation = self.ext("sync", "--provider", "kenney", "--from", str(nouvel), "--incremental", "--dry-run")
        self.assertEqual(len(simulation["alerts"]), 2)
        resultat = self.ext("sync", "--provider", "kenney", "--from", str(nouvel), "--incremental")
        self.assertEqual(resultat["changes"]["removed"], ["old-pack"])
        self.assertEqual(resultat["changes"]["updated"], ["kitchen-kit"])
        par_pack = {a["provenance"]["external"]["externalPackId"]: a for a in self.externals().values()}
        kit = par_pack["kitchen-kit"]
        self.assertEqual(kit["license"], "CC0-1.0")
        self.assertEqual([(h["from"], h["to"]) for h in kit["provenance"]["external"]["licenseHistory"]],
                         [("CC0-1.0", "CC-BY-4.0")])
        self.assertEqual(par_pack["old-pack"]["provenance"]["external"]["sourceStatus"], "removed")
        self.assertEqual(self.ext("sync", "--provider", "kenney", "--from", str(nouvel))["alerts"], [])
        self.assertEqual(self.cli("validate")[0], 0)

    def test_T10_export_public_avec_credits_et_licences(self):
        self.pack("kitchen-kit", {"whisk.png": png((10, 10, 200, 255)), "License.txt": CC0})
        self.ext("import", "--plan", str(self.plan("kitchen-kit")[0]))
        (asset_id, _), = self.externals().items()
        destination = self.dehors() / "export-public"
        code, resultat = self.cli("publish", asset_id, "--target", "public", "--dest", str(destination))
        self.assertEqual(code, 0, resultat)
        credits = (destination / "THIRD_PARTY_ASSETS.md").read_text()
        self.assertIn("kenney / kitchen-kit", credits)
        self.assertIn("CC0-1.0", credits)
        provenance = json.loads((destination / "provenance.json").read_text())
        self.assertEqual(provenance["assets"][0]["provider"], "kenney")
        self.assertEqual(provenance["assets"][0]["licenseEvidence"], "License.txt")

    def test_T11_nouvelle_orientation_variante_liee(self):
        self.pack("kitchen-kit", {"whisk.png": png((10, 10, 200, 255), (16, 24)), "License.txt": CC0})
        self.ext("import", "--plan", str(self.plan("kitchen-kit")[0]))
        (asset_id, _), = self.externals().items()
        recette = self.root / "miroir.json"
        recette.write_text('{"mirror": true}')
        code, enfant = self.cli("derive", asset_id, "--recipe", str(recette))
        self.assertEqual(code, 0, enfant)
        self.assertEqual(enfant["asset"]["provenance"]["derivedFrom"], asset_id)
        parent = json.loads((self.root / "catalog" / "assets" / f"{asset_id}.json").read_text())
        self.assertIn(enfant["id"], parent["variants"])
        self.assertEqual(enfant["asset"]["license"], "CC0-1.0")

    def test_T12_ci_sans_interface_sur_fixtures(self):
        import subprocess
        import sys
        self.pack("kitchen-kit", {"whisk.png": png((1, 1, 1, 255)), "License.txt": CC0}, tags=("whisk",))
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        p = subprocess.run([sys.executable, "-m", "tools.cli", "external", "search", "--query", "whisk", "--format",
                            "json"], cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True,
                           timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        resultat = json.loads(p.stdout)
        self.assertEqual(resultat["externalSearchStatus"], "available")
        self.assertEqual([r["externalId"] for r in resultat["results"]], ["kitchen-kit"])


class EXT001Module(ExterneFixture, TestCase):
    def test_module_desactive_recherche_et_validation_internes_intactes(self):
        with mock.patch.dict(os.environ, {"ASSETCTL_EXTERNAL": "off"}):
            self.assertEqual(self.cli("external", "providers"), (2, {"ok": False, "error": "external-disabled",
                             "message": "Module EXT-001 désactivé (ASSETCTL_EXTERNAL=off)."}))
            code, recherche = self.cli("search", "fouet")
            self.assertEqual((code, [r["id"] for r in recherche["results"]]), (0, [ASSET_ID]))
            self.assertEqual(self.cli("validate")[0], 0)

    def test_moteur_de_decision_justifie_chaque_issue(self):
        self.pack("kitchen-kit", {"a.png": png((1, 1, 1, 255)), "License.txt": CC0}, tags=("whisk",))
        derive = self.ext("decide", "--query", "fouet", "--orientation", "left")["decision"]
        self.assertEqual((derive["action"], derive["candidateId"]), ("derive", ASSET_ID))
        importer = self.ext("decide", "--query", "whisk", "--state", "dirty")["decision"]
        self.assertEqual((importer["action"], importer["candidateId"]), ("import", "kenney:kitchen-kit"))
        self.assertEqual(importer["rejected"][0]["id"], ASSET_ID)
        creer = self.ext("decide", "--query", "zebre")["decision"]
        self.assertEqual(creer["action"], "create")
        for decision in (derive, importer, creer):
            self.assertTrue(decision["rationale"].strip())

    def test_registre_des_fournisseurs_et_adaptateur_simule(self):
        from tools.external.adapters import ProviderAdapter, providers
        self.assertTrue(issubclass(type(providers(self.root)["kenney"]), ProviderAdapter))
        self.pack("kitchen-kit", {"a.png": png((1, 1, 1, 255)), "License.txt": CC0}, tags=("whisk", "clean"))
        self.pack("ui-pack", {"b.png": png((2, 2, 2, 255)), "License.txt": BYSA}, license_spdx="CC-BY-SA-4.0",
                  tags=("button",))
        providers_rows = self.ext("providers")["providers"]
        self.assertEqual([(r["id"], r["status"], r["packs"]) for r in providers_rows],
                         [("kenney", "available", 2), ("opengameart", "not-harvested", None),
                          ("lpc", "not-harvested", None), ("itchio", "not-harvested", None),
                          ("whitelist", "not-harvested", None)])
        self.assertEqual([r["externalId"] for r in self.ext("search", "--query", "clean whisk")["results"]], ["kitchen-kit"])
        filtre = self.ext("search", "--query", "", "--license", "CC-BY-SA-4.0")["results"]
        self.assertEqual([r["externalId"] for r in filtre], ["ui-pack"])
        self.assertEqual(self.ext("inspect", "--provider", "kenney", "--id", "ui-pack")["candidate"]["licenseSpdx"],
                         "CC-BY-SA-4.0")
        self.assertEqual(self.ext("inspect", "--provider", "kenney", "--id", "absent", code=1)["error"], "not-found")

    def test_contrat_d_import_valide_et_securite_non_negociable(self):
        from tools.core.schemas import schemas
        self.pack("kitchen-kit", {"a.png": png((1, 1, 1, 255)), "License.txt": CC0})
        plan = json.loads(self.plan("kitchen-kit")[0].read_text())
        valide = schemas().validator("external-import")
        self.assertTrue(valide.is_valid(plan))
        for mutation in ({"publishOnlyVerified": False}, ):
            faux = copy.deepcopy(plan)
            faux["policy"].update(mutation)
            self.assertFalse(valide.is_valid(faux))
        self.assertEqual(plan["files"][0]["path"], "a.png")
        self.assertRegex(plan["archiveSha256"], "^[0-9a-f]{64}$")

    def test_aucun_jeton_dans_index_plan_ou_fiche(self):
        with mock.patch.dict(os.environ, {"ASSETCTL_FORGEJO_TOKEN": "jeton-fixture-ext", "ASSETCTL_GITHUB_TOKEN": "jeton-fixture-ext"}):
            self.pack("kitchen-kit", {"a.png": png((1, 1, 1, 255)), "License.txt": CC0})
            plan, _ = self.plan("kitchen-kit")
            self.ext("import", "--plan", str(plan))
            for fichier in [plan, *(self.root / "catalog").rglob("*.json")]:
                self.assertNotIn("jeton-fixture-ext", fichier.read_text())
        self.pack("leaky", {"a.png": png((3, 3, 3, 255)), "License.txt": CC0},
                  extra={"downloadUrl": "https://kenney.nl/x.zip?token=abc"})
        self.assertEqual(self.ext("search", "--query", "")["externalSearchStatus"], "unavailable")

    def test_telechargement_borne_https_seulement_et_repris(self):
        from tools.external.download import DownloadError, DownloadManager
        source = self.packs / "gros.bin"
        source.write_bytes(bytes(5000))
        with self.assertRaises(DownloadError):
            DownloadManager(max_bytes=1000).fetch(source.as_uri(), self.root / "x")
        with self.assertRaises(DownloadError):
            DownloadManager().fetch("http://kenney.nl/x.zip", self.root / "y")
        manager = DownloadManager(pause=0)
        essais = []
        original = manager._once

        def instable(url, destination):
            essais.append(url)
            if len(essais) < 3:
                raise OSError("coupure réseau simulée")
            return original(url, destination)

        manager._once = instable
        resultat = manager.fetch(source.as_uri(), self.root / "z")
        self.assertEqual((len(essais), resultat["bytes"]), (3, 5000))
        self.assertEqual(resultat["sha256"], hashlib.sha256(bytes(5000)).hexdigest())


class EXT001CoteACote(ExterneFixture, TestCase):
    """E186 : un asset externe employé par un jeu (usage actif) sans côte à côte avec la planche est refusé par validate
    (arbitrage de David HL-538 7-2949, ADR-0005) ; tant qu'aucun jeu ne l'emploie, rien n'est exigé."""
    USAGE = {"assetVersion": 1, "codeRef": {"line": 1, "path": "src/art.ts"}, "commit": "a" * 40,
             "evidence": ["literal: assets/whisk.png"], "game": "cuisine", "importName": "whisk", "provider": "forgejo",
             "releases": [], "repo": "cuisine", "role": "sprite", "scene": "src/art.ts", "status": "active"}

    def employer(self, *preuves):
        if not self.externals():
            self.pack("kitchen-kit", {"whisk.png": png((10, 10, 200, 255)), "License.txt": CC0})
            self.ext("import", "--plan", str(self.plan("kitchen-kit")[0]))
        (asset_id, asset), = self.externals().items()
        asset["provenance"]["evidence"] = [e for e in asset["provenance"]["evidence"] if "te à c" not in e]
        asset["usages"] = [dict(self.USAGE)]
        asset["provenance"]["evidence"] = [*asset["provenance"]["evidence"], *preuves]
        (self.root / "catalog" / "assets" / f"{asset_id}.json").write_text(json.dumps(asset))
        code, rapport = self.cli("validate")
        return code, {i["code"] for i in rapport.get("issues", [])}

    def test_sans_usage_rien_n_est_exige(self):
        self.pack("kitchen-kit", {"whisk.png": png((10, 10, 200, 255)), "License.txt": CC0})
        self.ext("import", "--plan", str(self.plan("kitchen-kit")[0]))
        self.assertEqual(self.cli("validate")[0], 0)

    def test_employe_sans_cote_a_cote_refuse(self):
        self.assertEqual(self.employer(), (1, {"external-without-side-by-side"}))
        self.assertEqual(self.employer("côte à côte : sans ticket"), (1, {"external-without-side-by-side"}))

    def test_employe_avec_cote_a_cote_au_ticket_accepte(self):
        self.assertEqual(self.employer("côte à côte : HL-541 cote-a-cote-whisk.png"), (0, set()))


class EXT001Documentation(TestCase):
    def test_regles_agents_ext001(self):
        texte = (Path(__file__).resolve().parents[2] / "docs" / "AGENTS.md").read_text(encoding="utf-8")
        for attendu in ("**OBLIGATOIRE :** Search internal → Search external → Reuse → Import → Derive → Create.",
                        "Ne jamais présumer la licence d'un pack", "désactivable (`ASSETCTL_EXTERNAL=off`)",
                        "entièrement headless", "côte à côte avec la planche", "rapport de tâche et dans la PR"):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, " ".join(texte.split()))
