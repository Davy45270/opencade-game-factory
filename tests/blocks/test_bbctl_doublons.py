"""Oracles BB-04 (BB-001 § 3) : détection de doublons, rapport SANS fusion automatique.

Écrits AVANT le code (Claude, oracle, HL-525 19/11, lot (c)) : ils échouent tant que `bbctl duplicates` n'existe pas.
L'implémentation (Codex) les fait passer SANS les modifier ; un oracle jugé faux se signale dans le rapport.

Contrat d'appel (en plus de tests/blocks/_outil.py) :
  bbctl duplicates --graph <graph.json> [--root <dépôt>=<chemin>]… [--min-similarity <0..1>] --json
  - lit le graphe graphify (et, avec --root, le CONTENU des `source_file` sous ce chemin) ; n'écrit RIEN ;
  - rend {"groups": [{"reason": "same-hash" | "similar-name", "members": [<id de nœud graphify>, …],
                      "repos": [<dépôt>, …], "evidence": {…}}], "graphSha256": <sha256 du graphe>} ;
  - un groupe porte au moins deux DÉPÔTS différents (deux nœuds d'un même dépôt ne sont pas un doublon interprojets) ;
  - « similar-name » : noms normalisés (casse, `_`, `-`, parenthèses ignorées) égaux, ou similarité ≥ --min-similarity
    (défaut 0.85) ; « same-hash » : même sha256 du fichier source (evidence.sha256) ;
  - code 0 même avec des doublons (c'est un RAPPORT) ; graphe absent = 4 (source indisponible), aucun groupe inventé ;
  - le catalogue (USINE_RACINE/blocks) est identique, octet pour octet, avant et après.
"""
from __future__ import annotations

import json
import unittest

from ._outil import Usine, sha


def noeud(repo: str, fichier: str, label: str) -> dict:
    return {"id": f"{repo}::{fichier.replace('/', '_').replace('.', '_')}_{label.strip('()').lower()}", "label": label,
            "norm_label": label.lower(), "repo": repo, "source_file": fichier, "source_location": "L1", "file_type": "code"}


class BB04Doublons(unittest.TestCase):
    def setUp(self) -> None:
        self.u = Usine()
        self.noeuds = [
            noeud("six-de-chaque", "packages/engine/src/rng.ts", "mulberry32()"),
            noeud("capsule-panic", "src/game/rng.ts", "mulberry32()"),          # même nom, autre dépôt → similar-name
            noeud("cozy-room-sort", "src/util/random.ts", "seededRandom()"),
            noeud("pestouille-rpg", "src/core/seeded-random.ts", "seeded_random()"),  # même nom normalisé → similar-name
            noeud("six-de-chaque", "packages/engine/src/score.ts", "score()"),
            noeud("six-de-chaque", "packages/ui/src/score.ts", "score()"),     # même dépôt : PAS un doublon
            noeud("capsule-panic", "src/save/checksum.ts", "crc()"),
            noeud("cozy-room-sort", "src/save/hash.ts", "fnv()"),              # noms différents, contenu identique → same-hash
        ]
        self.u.graphe.write_text(json.dumps({"directed": True, "multigraph": False, "graph": {}, "nodes": self.noeuds,
                                             "links": []}))
        self.racines = {}
        for n in self.noeuds:
            r = self.u.tmp / "depots" / n["repo"]
            self.racines[n["repo"]] = r
            f = r / n["source_file"]
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"// {n['repo']} {n['label']}\n")
        commun = "export function h(s: string): number { let x = 0; for (const c of s) x = (x * 31 + c.charCodeAt(0)) | 0; return x; }\n"
        (self.racines["capsule-panic"] / "src/save/checksum.ts").write_text(commun)
        (self.racines["cozy-room-sort"] / "src/save/hash.ts").write_text(commun)

    def tearDown(self) -> None:
        self.u.nettoyer()

    def doublons(self, *extra: str):
        args = ["duplicates", "--graph", str(self.u.graphe), "--json", *extra]
        return self.u.bbctl(*args)

    def avec_racines(self):
        r = []
        for repo, chemin in sorted(self.racines.items()):
            r += ["--root", f"{repo}={chemin}"]
        return self.doublons(*r)

    def groupes(self, r, raison: str) -> list[set[str]]:
        return [set(g["members"]) for g in r.json["groups"] if g["reason"] == raison]

    def test_meme_nom_dans_deux_depots(self) -> None:
        r = self.doublons()
        self.assertEqual(r.rc, 0, r)
        ids = {n["label"]: n["id"] for n in self.noeuds if n["label"] == "mulberry32()" and n["repo"] == "capsule-panic"}
        attendu = {n["id"] for n in self.noeuds if n["label"] == "mulberry32()"}
        self.assertIn(attendu, self.groupes(r, "similar-name"), r)
        self.assertTrue(ids)

    def test_nom_normalise_casse_et_separateurs(self) -> None:
        r = self.doublons()
        attendu = {n["id"] for n in self.noeuds if n["label"] in ("seededRandom()", "seeded_random()")}
        self.assertIn(attendu, self.groupes(r, "similar-name"), r)

    def test_meme_depot_n_est_pas_un_doublon_interprojets(self) -> None:
        r = self.doublons()
        for g in r.json["groups"]:
            self.assertGreaterEqual(len(set(g["repos"])), 2, g)
            self.assertNotIn({n["id"] for n in self.noeuds if n["label"] == "score()"}, [set(g["members"])])

    def test_meme_contenu_sous_deux_noms(self) -> None:
        r = self.avec_racines()
        self.assertEqual(r.rc, 0, r)
        attendu = {n["id"] for n in self.noeuds if n["label"] in ("crc()", "fnv()")}
        self.assertIn(attendu, self.groupes(r, "same-hash"), r)
        g = next(g for g in r.json["groups"] if g["reason"] == "same-hash" and set(g["members"]) == attendu)
        self.assertRegex(g["evidence"]["sha256"], r"^[0-9a-f]{64}$")

    def test_sans_racine_aucun_hash_invente(self) -> None:
        r = self.doublons()
        self.assertEqual(self.groupes(r, "same-hash"), [], r)

    def test_rapport_sans_fusion_catalogue_intact(self) -> None:
        avant = self.u.empreinte(self.u.usine)
        r = self.avec_racines()
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(self.u.empreinte(self.u.usine), avant)
        self.assertEqual(r.json["graphSha256"], sha(self.u.graphe.read_bytes()))

    def test_depots_lus_seulement(self) -> None:
        avant = self.u.empreinte(self.u.tmp / "depots")
        r = self.avec_racines()
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(self.u.empreinte(self.u.tmp / "depots"), avant)

    def test_graphe_indisponible(self) -> None:
        r = self.u.bbctl("duplicates", "--graph", str(self.u.tmp / "absent.json"), "--json")
        self.assertEqual(r.rc, 4, r)
        self.assertEqual(r.json["status"], "source-unavailable")
        self.assertNotIn("groups", r.json)

    def test_seuil_de_similarite(self) -> None:
        r = self.doublons("--min-similarity", "1.0")
        self.assertEqual(r.rc, 0, r)
        attendu = {n["id"] for n in self.noeuds if n["label"] in ("seededRandom()", "seeded_random()")}
        self.assertIn(attendu, self.groupes(r, "similar-name"), r)     # égaux après normalisation : 1.0
        self.assertEqual(self.u.bbctl("duplicates", "--graph", str(self.u.graphe), "--min-similarity", "1.5",
                                      "--json").rc, 2)


if __name__ == "__main__":
    unittest.main()
