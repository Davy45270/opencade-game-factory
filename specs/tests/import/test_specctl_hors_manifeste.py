"""ARCH-001 E006 et E009 : toute spec reçue a sa fiche, enregistrée PAR RÉFÉRENCE (dépôt, chemin, commit, sha256).

Mesure du 22/11 : 251 documents de homelab-docs/specs/*-sources (sur 405) n'avaient l'empreinte d'aucune fiche du
registre, parce que l'import ne lisait que les fichiers listés dans `empreintes-drive.sha256` (ou dans la matrice).
Les pièces ajoutées après l'import Drive (planches, spec v2, relectures) restaient invisibles.
Ici : un fichier du dossier absent du manifeste entre dans la fiche, SANS version (seul un manifeste ou la matrice en
déclare une), avec sa provenance ; `index.md` et le manifeste lui-même, qui ne sont pas des specs, n'y entrent pas ;
la version résolue ne change pas."""
from __future__ import annotations

import unittest

from .._outil import SPEC_B, Docs, sha


class DocumentsHorsManifeste(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()

    def tearDown(self) -> None:
        self.d.nettoyer()

    def test_document_hors_manifeste_a_sa_fiche_par_reference(self) -> None:
        s = self.d.docs / "specs" / "jeu-a-sources"
        (s / "planches").mkdir()
        (s / "planches" / "planche-1.png").write_bytes(b"\x89PNG faux")
        (s / "notes-v2.md").write_text(SPEC_B)
        head = self.d.commit("pièces ajoutées hors manifeste")
        r = self.d.specctl("import", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 0, r)
        fiche = self.d.registre()["SPEC-JEU-A"]
        hors = {p["path"]: (doc["sha256"], p) for doc in fiche.get("unversionedDocuments", []) for p in doc["provenances"]}
        for chemin, contenu in (("specs/jeu-a-sources/planches/planche-1.png", b"\x89PNG faux"),
                                ("specs/jeu-a-sources/notes-v2.md", SPEC_B.encode())):
            self.assertIn(chemin, hors, fiche)
            self.assertEqual(hors[chemin][0], sha(contenu))
            self.assertEqual(hors[chemin][1], {"repo": "homelab-docs", "path": chemin, "commitSha": head})
        tous = {p["path"] for v in fiche["versions"] for doc in v["documents"] for p in doc["provenances"]} | set(hors)
        self.assertNotIn("specs/jeu-a-sources/index.md", tous)
        self.assertNotIn("specs/jeu-a-sources/empreintes-drive.sha256", tous)
        r = self.d.specctl("resolve", "--project", "jeu-a", "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual([s["version"] for s in r.json["specs"]], ["1.0.0"], r)

    def test_temoin_sans_piece_ajoutee_rien_hors_manifeste(self) -> None:
        r = self.d.specctl("import", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 0, r)
        self.assertNotIn("unversionedDocuments", self.d.registre()["SPEC-JEU-A"])


if __name__ == "__main__":
    unittest.main()
