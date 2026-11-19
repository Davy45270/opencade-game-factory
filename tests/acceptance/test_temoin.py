"""Témoin de l'oracle : le dossier se découvre, chaque AT de la spec §11 a son fichier, et chaque
fichier cite l'AT mot pour mot et son identifiant de matrice (E111…E125)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from . import _contrat as C

ICI = Path(__file__).resolve().parent
SPEC_AT = {
    1: "100 % des dépôts **autorisés et accessibles** sont recensés avec commit de référence.",
    2: "100 % des ressources des formats pris en charge sont importées ou signalées en exception.",
    3: "aucun fichier des dépôts sources n'est modifié lors de l'inventaire.",
    4: "un second import identique ne crée aucun nouvel asset.",
    5: "chaque asset possède un ID stable, un univers, un statut, une description et une provenance ou un `unknown` explicite.",
    6: "chaque sprite extrait pointe vers sa planche et sa région vérifiée, ou marque la région inconnue.",
    7: "les usages d'un sprite sont retrouvés par dépôt, jeu, scène et commit lorsque la référence est statiquement déterminable.",
    8: "une ressource à licence inconnue ne peut pas être exportée publiquement.",
    9: "la recherche d'un fouet propre en vue trois quarts retourne les candidats compatibles et leur historique d'usage.",
    10: "une création sans recherche préalable échoue au contrôle de PR.",
    11: "la suppression d'un fichier source utilisé est signalée sans effacer l'historique des releases.",
    12: "l'index de recherche est reconstruit à partir du seul catalogue versionné.",
    13: "l'export d'un atlas PNG/JSON valide la transparence, les dimensions et les références.",
    14: "un agent peut importer et réutiliser un asset dans un autre jeu sans interface graphique.",
    15: "les rapports indiquent les inconnues, échecs, limites de scan et ressources non couvertes.",
}


class Temoin(unittest.TestCase):
    def test_chaque_at_a_son_fichier_avec_l_extrait_et_l_id_de_matrice(self):
        for n, extrait in SPEC_AT.items():
            with self.subTest(at=n):
                fichiers = sorted(ICI.glob(f"test_at{n:02d}_*.py"))
                self.assertEqual(len(fichiers), 1, f"AT-{n:02d} : un fichier attendu")
                texte = fichiers[0].read_text(encoding="utf-8")
                self.assertIn(f"AT-{n:02d}", texte)
                self.assertIn(f"E{110 + n}", texte)
                self.assertIn(extrait, texte, "extrait de la spec, mot pour mot")

    def test_le_dossier_se_decouvre_sans_erreur_d_import(self):
        suite = unittest.defaultTestLoader.discover(str(ICI), pattern="test_*.py",
                                                    top_level_dir=str(C.RACINE_REGISTRE))
        noms, echecs = [], []

        def aplatir(s):
            for t in s:
                if isinstance(t, unittest.TestSuite):
                    aplatir(t)
                else:
                    noms.append(t.id())
                    if type(t).__name__ == "_FailedTest" or "ModuleImportFailure" in t.id():
                        echecs.append(t.id())

        aplatir(suite)
        self.assertEqual(echecs, [], "modules de test qui ne se chargent pas")
        for n in SPEC_AT:
            self.assertTrue(any(re.search(rf"\.test_at{n:02d}_", x) for x in noms), f"AT-{n:02d} non découvert")

    def test_extraits_conformes_a_la_spec(self):
        """Si la spec originale est lisible (poste de David), les extraits sont comparés au texte réel."""
        spec = Path("/home/david/Projets/homelab-docs/specs/asset-registry-sources/"
                    "OpenCade_Asset_Registry_Specifications_v1.0.md.txt")
        if not spec.is_file():
            self.skipTest("spec originale hors de portée (CI)")
        texte = spec.read_text(encoding="utf-8")
        for n, extrait in SPEC_AT.items():
            self.assertIn(f"- AT-{n:02d} : {extrait}", texte)
