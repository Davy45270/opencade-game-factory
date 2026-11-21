"""Oracles BB-001 lot 2 (HL-525), écrits AVANT le code.

1. Manifestes des autres écosystèmes (§ 3, point 2) : pyproject.toml, Cargo.toml, go.mod, Dockerfile.
2. Découverte open source (§ 4) : `bbctl search --scope opensource --query <q> [--ecosystem npm] [--record] --json`
   interroge le registre OFFICIEL (npm : /-/v1/search puis la fiche de la version exacte) et la base OSV
   (POST /v1/query) — métadonnées seulement, aucun téléchargement d'archive ni exécution de code. Chaque candidat
   porte l'URL canonique du dépôt, la licence EXACTE de la version envisagée, la date de publication et les
   vulnérabilités connues. `--record` inscrit les candidats au catalogue (statut `candidate`). Registre injoignable :
   code 4, aucune donnée inventée, rien d'écrit (T12). Les URL sont réglables (BBCTL_NPM_REGISTRY, BBCTL_OSV_URL) :
   les tests servent un faux registre local et relèvent chaque requête.
"""
from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from ._outil import Usine
from .test_bbctl_discover import Base

RECHERCHE = {"objects": [{"package": {"name": "rot-js", "version": "2.2.0",
                                      "links": {"repository": "https://github.com/ondras/rot.js"}}},
                         {"package": {"name": "sans-licence", "version": "0.1.0", "links": {}}}]}
VERSIONS = {"/rot-js/2.2.0": {"name": "rot-js", "version": "2.2.0", "license": "BSD-3-Clause",
                              "repository": {"type": "git", "url": "git+https://github.com/ondras/rot.js.git"}},
            "/sans-licence/0.1.0": {"name": "sans-licence", "version": "0.1.0"}}
FICHES = {"/rot-js": {"time": {"2.2.0": "2023-05-01T10:00:00.000Z"}},
          "/sans-licence": {"time": {"0.1.0": "2019-01-01T00:00:00.000Z"}}}
OSV = {"rot-js": {"vulns": []}, "sans-licence": {"vulns": [
    {"id": "GHSA-xxxx", "database_specific": {"severity": "CRITICAL"}}]}}


class Faux(BaseHTTPRequestHandler):
    vus: list[str] = []

    def log_message(self, *a) -> None:
        pass

    def repondre(self, corps) -> None:
        if corps is None:
            self.send_response(404); self.end_headers(); return
        b = json.dumps(corps).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(b)

    def do_GET(self) -> None:
        Faux.vus.append("GET " + self.path)
        p = urlparse(self.path).path
        self.repondre(RECHERCHE if p == "/-/v1/search" else VERSIONS.get(p) or FICHES.get(p))

    def do_POST(self) -> None:
        Faux.vus.append("POST " + self.path)
        corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.repondre(OSV.get(corps["package"]["name"]) if self.path == "/v1/query" else None)


class OpenSource(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()
        Faux.vus = []
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Faux)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{self.srv.server_port}"
        os.environ["BBCTL_NPM_REGISTRY"] = url
        os.environ["BBCTL_OSV_URL"] = url

    def tearDown(self) -> None:
        self.srv.shutdown(); self.srv.server_close()
        for k in ("BBCTL_NPM_REGISTRY", "BBCTL_OSV_URL"):
            os.environ.pop(k, None)
        self.u.nettoyer()

    def chercher(self, *extra: str):
        return self.u.bbctl("search", "--scope", "opensource", "--query", "roguelike toolkit", "--ecosystem", "npm",
                            *extra, "--json")

    def test_candidats_verifies_aupres_du_registre_officiel(self) -> None:
        r = self.chercher()
        self.assertEqual(r.rc, 0, r)
        rot = next(c for c in r.json["candidates"] if c["name"] == "rot-js")
        self.assertEqual(rot["repositoryUrl"], "https://github.com/ondras/rot.js")      # URL canonique
        self.assertEqual((rot["version"], rot["licenseSpdx"]), ("2.2.0", "BSD-3-Clause"))  # licence de CETTE version
        self.assertEqual(rot["published"], "2023-05-01T10:00:00.000Z")
        self.assertEqual(rot["vulnerabilities"], {"count": 0, "critical": 0})

    def test_inconnues_jamais_inventees_et_vulnerabilite_critique_relevee(self) -> None:
        r = self.chercher()
        sl = next(c for c in r.json["candidates"] if c["name"] == "sans-licence")
        self.assertEqual((sl["licenseSpdx"], sl["repositoryUrl"]), ("UNKNOWN", None))
        self.assertEqual(sl["vulnerabilities"], {"count": 1, "critical": 1})

    def test_metadonnees_seulement_aucune_archive(self) -> None:
        self.chercher()
        self.assertTrue(Faux.vus)
        self.assertFalse([v for v in Faux.vus if v.endswith(".tgz") or "/-/" in v and "/-/v1/search" not in v], Faux.vus)

    def test_sans_record_rien_n_est_ecrit_avec_record_candidats_inscrits(self) -> None:
        avant = self.u.empreinte(self.u.usine)
        self.chercher()
        self.assertEqual(self.u.empreinte(self.u.usine), avant)
        r = self.chercher("--record")
        self.assertEqual(r.rc, 0, r)
        fiches = [json.loads(p.read_text()) for p in (self.u.usine / "blocks" / "catalog").glob("*.json")]
        rot = next(f for f in fiches if f["name"] == "rot-js")
        self.assertEqual((rot["kind"], rot["quality"]["status"], rot["origin"]["licenseSpdx"]),
                         ("external-library", "candidate", "BSD-3-Clause"))
        self.assertEqual(self.u.bbctl("validate", "--all", "--json").rc, 0)
        n = len(fiches)
        self.chercher("--record")                                                # relance : pas de doublon
        self.assertEqual(len(list((self.u.usine / "blocks" / "catalog").glob("*.json"))), n)

    def test_T12_registre_injoignable_erreur_explicite(self) -> None:
        self.srv.shutdown(); self.srv.server_close()
        os.environ["BBCTL_NPM_REGISTRY"] = "http://127.0.0.1:9"
        avant = self.u.empreinte(self.u.usine)
        r = self.chercher("--record")
        self.assertEqual(r.rc, 4, r)
        self.assertEqual(r.json["status"], "source-unavailable")
        self.assertEqual(self.u.empreinte(self.u.usine), avant)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Faux)                    # pour tearDown (shutdown attend
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()     # une boucle qui tourne)


class AutresEcosystemes(Base):
    def test_dependance_retiree_fiche_gardee_plus_utilisee(self) -> None:
        self.decouvrir()
        (pillow,) = self.par_nom("pillow")
        self.depot("jeu-b", {"requirements.txt": "\n"})
        self.decouvrir()
        f = self.catalogue()[pillow["id"]]                                      # identifiant jamais recyclé
        self.assertEqual((f["usedBy"], f["observedIn"]), ([], []))
        self.assertEqual(self.u.bbctl("validate", "--all", "--json").rc, 0)

    def test_espace_de_travail_npm_version_du_lockfile_racine(self) -> None:
        lock = {"lockfileVersion": 3, "packages": {"": {"name": "mono"},
                "node_modules/pixi.js": {"version": "8.1.0", "license": "MIT"},
                "packages/moteur": {"name": "@mono/moteur", "version": "0.1.0"},
                "node_modules/@mono/moteur": {"link": True, "resolved": "packages/moteur"}}}
        self.depot("mono", {"package-lock.json": json.dumps(lock),
                            "apps/web/package.json": json.dumps({"dependencies": {"pixi.js": "^8", "@mono/moteur": "*"}}),
                            "packages/moteur/package.json": json.dumps({"name": "@mono/moteur"}),
                            "packages/moteur/src/index.ts": "export const m = 1\n"})
        self.assertEqual(self.decouvrir().rc, 0)
        (pixi,) = self.par_nom("pixi.js")
        self.assertEqual((pixi["origin"]["version"], pixi["origin"]["licenseSpdx"]), ("8.1.0", "MIT"))
        self.assertEqual([b["kind"] for b in self.par_nom("@mono/moteur")], [])   # paquet de l'espace : module local
        self.assertEqual(len(self.par_nom("moteur")), 1)

    def test_pyproject_cargo_gomod_dockerfile(self) -> None:
        self.depot("jeu-b", {
            "pyproject.toml": '[project]\nname = "x"\ndependencies = ["requests==2.31.0", "rich>=13"]\n',
            "outil/Cargo.toml": '[package]\nname = "o"\n\n[dependencies]\nserde = "1.0.190"\n',
            "srv/go.mod": "module ex.com/srv\n\ngo 1.22\n\nrequire (\n\tgithub.com/x/y v1.2.3\n)\n",
            "Dockerfile": "FROM node:20.11-alpine AS build\nRUN true\nFROM nginx:1.25\n"})
        self.assertEqual(self.decouvrir().rc, 0)
        vus = {(b["discovery"]["ecosystem"], b["name"], b["origin"]["version"], b["kind"])
               for b in self.catalogue().values() if "discovery" in b}   # hors fiche posée par la fixture
        for attendu in [("pypi", "requests", "2.31.0", "external-library"), ("pypi", "rich", None, "external-library"),
                        ("cargo", "serde", None, "external-library"), ("go", "github.com/x/y", "v1.2.3", "external-library"),
                        ("docker", "node", "20.11-alpine", "service"), ("docker", "nginx", "1.25", "service")]:
            self.assertIn(attendu, vus)


if __name__ == "__main__":
    unittest.main()
