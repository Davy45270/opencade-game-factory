"""ARCH-001 AT-04 : toute spec et tout composant implémenté possèdent un enregistrement registry vérifiable.

Specs : après `specctl import`, chaque document des dossiers de sources (hors navigation) a son empreinte dans une
fiche du registre, avec sa provenance ; un document ajouté et non importé est vu manquant.
Composants : `bbctl discover` rend `unregistered`, les briques observées dans les dépôts autorisés qui n'ont pas
encore de fiche ; vide après l'enregistrement, et une brique ajoutée dans un jeu y réapparaît (témoin).
"""
from __future__ import annotations

import json
import unittest

from specs.tests._outil import Docs, sha

from .test_bbctl_discover import PKG_B, Base

NAVIGATION = {"index.md", "empreintes-drive.sha256"}


def specs_sans_fiche(d: Docs) -> list[str]:
    """Documents de specs/*-sources dont l'empreinte et le chemin ne sont dans aucune fiche du registre."""
    cites = set()
    for fiche in d.registre().values():
        docs = [doc for v in fiche.get("versions", []) for doc in v.get("documents", [])]
        docs += fiche.get("unversionedDocuments", [])
        cites |= {(p["path"], doc["sha256"]) for doc in docs for p in doc["provenances"] if p.get("commitSha")}
    manquants = []
    for f in sorted((d.docs / "specs").glob("*-sources/**/*")):
        if f.is_file() and f.name not in NAVIGATION:
            chemin = f.relative_to(d.docs).as_posix()
            if (chemin, sha(f.read_bytes())) not in cites:
                manquants.append(chemin)
    return manquants


class AT04Specs(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()

    def tearDown(self) -> None:
        self.d.nettoyer()

    def test_chaque_spec_recue_a_sa_fiche(self) -> None:
        self.assertEqual(self.d.specctl("import", "--from", str(self.d.docs), "--json").rc, 0)
        self.assertEqual(specs_sans_fiche(self.d), [])

    def test_temoin_spec_ajoutee_sans_import_vue_manquante(self) -> None:
        self.d.specctl("import", "--from", str(self.d.docs), "--json")
        (self.d.docs / "specs" / "jeu-b-sources" / "Jeu_B_v1.1.md.txt").write_text("# Jeu B v1.1\n")
        self.d.commit("nouvelle version, pas encore importée")
        self.assertEqual(specs_sans_fiche(self.d), ["specs/jeu-b-sources/Jeu_B_v1.1.md.txt"])
        self.assertEqual(self.d.specctl("import", "--from", str(self.d.docs), "--json").rc, 0)
        self.assertEqual(specs_sans_fiche(self.d), [])


class AT04Composants(Base):
    def test_chaque_composant_implemente_a_sa_fiche(self) -> None:
        deja = set(self.catalogue())                                        # fiches de la fixture, hors découverte
        avant = self.decouvrir("--dry-run")
        self.assertEqual(len(avant.json["unregistered"]), 6, avant)       # aucune brique découverte n'a de fiche
        r = self.decouvrir()
        self.assertEqual(sorted(r.json["unregistered"]), sorted(set(self.catalogue()) - deja))
        self.assertEqual(self.decouvrir("--dry-run").json["unregistered"], [])
        self.assertEqual(self.u.bbctl("validate", "--all", "--json").rc, 0)

    def test_temoin_brique_ajoutee_dans_un_jeu_vue_non_enregistree(self) -> None:
        self.decouvrir()
        self.depot("jeu-b", {"package.json": json.dumps(PKG_B | {"dependencies": {"phaser": "3.90.0", "howler": "2.2.4"}})})
        r = self.decouvrir("--dry-run")
        self.assertEqual(len(r.json["unregistered"]), 1, r)
        self.assertEqual(self.par_nom("howler"), [])                        # dry-run : rien d'écrit
        self.decouvrir()
        (howler,) = self.par_nom("howler")
        self.assertEqual(r.json["unregistered"], [howler["id"]])
        self.assertEqual(self.decouvrir("--dry-run").json["unregistered"], [])
