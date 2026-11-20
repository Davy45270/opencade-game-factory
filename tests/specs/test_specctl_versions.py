"""Oracles du lot (d) : d'où vient la VERSION d'une spec importée (REG-003, préalable au blocage de REG-06).

Mesure du 20/11 : REG-06 rendait `version-missing` pour trois jeux sur quatre, parce que l'importeur ne lisait la
version que dans le NOM DE FICHIER. Or les archives copiées depuis Drive gardent les noms d'origine, sans version. La
version est ailleurs, dans la provenance :
  1. le nom du fichier (inchangé : il l'emporte) ;
  2. sinon, le dossier versionné le plus proche sous `<jeu>-sources/` (ex. `rpg-v1.4/…` → 1.4.0) ;
  3. sinon, le zip d'origine nommé dans un commentaire du manifeste `empreintes-drive.sha256`
     (ex. `# zip d'origine : Qwarkle_Specifications_Implementation_v1.0.zip, …` → 1.0.0).
Un commentaire qui ne nomme pas un `.zip` versionné ne donne AUCUNE version. Plusieurs versions dans une même spec
donnent toujours « arbitrage requis » (rc 5) : on ne choisit jamais à la place de David.
Écrits par Claude AVANT le code ; le cœur est à écrire par Codex."""
from __future__ import annotations

import unittest

from ._outil import SPEC_A, SPEC_B, Docs


class VersionsDesSpecs(unittest.TestCase):
    def setUp(self) -> None:
        self.d = Docs()

    def tearDown(self) -> None:
        self.d.nettoyer()

    def commentaire(self, x: str, ligne: str) -> None:
        m = self.d.docs / "specs" / f"{x}-sources" / "empreintes-drive.sha256"
        lignes = m.read_text().splitlines()
        m.write_text("\n".join([ligne, *lignes[1:]]) + "\n")

    def resoudre(self, projet: str):
        r = self.d.specctl("import", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 0, r)
        return self.d.specctl("resolve", "--project", projet, "--json")

    def versions(self, r) -> list[str]:
        v = r.json
        return sorted({s.get("version") for s in v.get("specs", [v]) if s.get("version")})

    def test_version_du_dossier_versionne(self) -> None:
        self.d.archive("jeu-d", {"rpg-v1.4/ADDENDUM.md.txt": SPEC_B})
        self.d.commit("jeu D")
        r = self.resoudre("jeu-d")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(self.versions(r), ["1.4.0"], r)

    def test_version_du_zip_d_origine_nomme_dans_le_manifeste(self) -> None:
        self.d.archive("jeu-e", {"README.md.txt": SPEC_A, "specifications/01-regles.md.txt": SPEC_B})
        self.commentaire("jeu-e", "# zip d'origine : Jeu_E_Specifications_Implementation_v1.0.zip, Drive id x, sha256 y")
        self.d.commit("jeu E")
        r = self.resoudre("jeu-e")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(self.versions(r), ["1.0.0"], r)

    def test_le_nom_de_fichier_l_emporte_et_deux_versions_exigent_l_arbitrage(self) -> None:
        self.d.archive("jeu-f", {"README.md.txt": SPEC_A, "Jeu_F_v1.1.md.txt": SPEC_B})
        self.commentaire("jeu-f", "# zip d'origine : Jeu_F_v1.0.zip")
        self.d.commit("jeu F")
        r = self.resoudre("jeu-f")
        self.assertEqual(r.rc, 5, r)
        self.assertEqual(r.json.get("status"), "arbitration-required", r)
        self.assertEqual(sorted(r.json.get("versions") or []), ["1.0.0", "1.1.0"], r)

    def test_dossier_versionne_plus_proche_l_emporte_sur_le_zip(self) -> None:
        self.d.archive("jeu-g", {"rpg-v1.3/A.md.txt": SPEC_A, "rpg-v1.3/sous/B.md.txt": SPEC_B})
        self.commentaire("jeu-g", "# zip d'origine : Jeu_G_v1.0.zip")
        self.d.commit("jeu G")
        r = self.resoudre("jeu-g")
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(self.versions(r), ["1.3.0"], r)

    def test_commentaire_sans_zip_versionne_ne_donne_pas_de_version(self) -> None:
        self.d.archive("jeu-h", {"README.md.txt": SPEC_A})
        self.commentaire("jeu-h", "# Drive : dossier v2 du 18/11, identifiants relevés à la main")
        self.d.commit("jeu H")
        r = self.resoudre("jeu-h")
        self.assertEqual(r.rc, 1, r)
        self.assertEqual(r.json.get("status"), "version-missing", r)

    def test_nom_de_dossier_hors_sources_ne_compte_pas(self) -> None:
        """Seuls les dossiers SOUS `<jeu>-sources/` comptent : le nom du projet lui-même n'est pas une version."""
        self.d.archive("jeu-v2", {"README.md.txt": SPEC_A})
        self.d.commit("jeu v2")
        r = self.resoudre("jeu-v2")
        self.assertEqual(r.rc, 1, r)
        self.assertEqual(r.json.get("status"), "version-missing", r)


if __name__ == "__main__":
    unittest.main()


class IdentifiantsStables(unittest.TestCase):
    """20/11 : depuis HL-525 (19/11, Cozy), un élément de planche s'identifie par `E-<table>-<élément>` (identifiant
    stable, minuscules ASCII). Le schéma du registre n'acceptait que `E###` : l'import de TOUT le registre échouait
    (« SPEC-COZY-ROOM-SORT : schéma invalide (requirements/261/id, pattern) »), et REG-06 restait sur un registre périmé."""

    def setUp(self) -> None:
        self.d = Docs()

    def tearDown(self) -> None:
        self.d.nettoyer()

    def matrice(self, ids: list[str]) -> None:
        self.d.archive("jeu-s", {"Jeu_S_v1.0.md.txt": SPEC_A})
        self.d.matrice("jeu-s", "Jeu_S_v1.0.md.txt", [(i, "Le joueur pose une tuile.", "a_faire") for i in ids])
        self.d.commit("jeu S")

    def test_identifiant_stable_importe(self) -> None:
        self.matrice(["E001", "E-p01-objets-carton-ferme"])
        r = self.d.specctl("import", "--from", str(self.d.docs), "--json")
        self.assertEqual(r.rc, 0, r)
        reqs = {x["matrixId"]: x["id"] for x in self.d.registre()["SPEC-JEU-S"]["requirements"]}
        self.assertEqual(reqs.get("E-p01-objets-carton-ferme"), "REQ-JEU-S-E-P01-OBJETS-CARTON-FERME", reqs)
        self.assertEqual(self.d.specctl("validate", "--json").rc, 0)

    def test_identifiant_mal_forme_refuse(self) -> None:
        for mauvais in ("E-", "E-P01-Majuscules", "E-p01--double", "X001"):
            with self.subTest(mauvais=mauvais):
                self.d.nettoyer(); self.d = Docs()
                self.matrice(["E001", mauvais])
                r = self.d.specctl("import", "--from", str(self.d.docs), "--json")
                self.assertNotEqual(r.rc, 0, r)
