"""AT-15 (matrice E125) : « les rapports indiquent les inconnues, échecs, limites de scan et ressources non couvertes. »"""
from __future__ import annotations

from . import _contrat as C
from ._base import MondeScanne
from ._monde import EXCLU, FOUET, NIVEAU, TRONQUE


class AT15Rapports(MondeScanne):
    """AT-15 / E125 — « AT-15 : les rapports indiquent les inconnues, échecs, limites de scan et ressources
    non couvertes. »

    Intention : chaque rapport existe en JSON **et** en Markdown (lisible par agents et humains), et dit
    quelque chose de vrai sur la fixture — pas seulement un titre :
      - inconnues : `licenses-unknown` cite le fouet (aucune preuve de licence) ;
      - échecs : `exceptions` cite le PNG tronqué ; `migration` cite le dépôt autorisé inaccessible ;
      - limites de scan : `scan-limits` cite l'exclusion `node_modules/` et le fichier qu'elle cache ;
      - non couverts : `coverage` cite l'exclusion et l'exception, `orphans` cite l'asset jamais utilisé
        (`niveau-1.png`, référencé seulement par un gabarit `${}`)."""

    FANTOME = True

    def setUp(self):
        self.assertIn(self.scan.code, (C.OK, C.ECHEC, C.ERREUR_ES), str(self.scan))

    def _lire(self, nom: str) -> tuple[object, str]:
        j, m = C.rapport(self.reg, nom), C.rapport(self.reg, nom, "md")
        self.assertTrue(j.is_file(), f"{j.name} absent")
        self.assertTrue(m.is_file(), f"{m.name} absent")
        return C.lire_json(j), m.read_text(encoding="utf-8")

    def test_chaque_rapport_en_json_et_markdown(self):
        for nom in C.RAPPORTS:
            with self.subTest(rapport=nom):
                _, md = self._lire(nom)
                self.assertTrue(md.strip())

    def test_inconnues(self):
        fouet_id, _ = self.asset("jeu-a", FOUET)
        j, md = self._lire("licenses-unknown")
        self.assertTrue(C.contient_valeur(j, fouet_id), "licences inconnues : le fouet manque (JSON)")
        self.assertIn(fouet_id, md, "licences inconnues : le fouet manque (Markdown)")

    def test_echecs(self):
        j, md = self._lire("exceptions")
        self.assertTrue(C.contient_valeur(j, TRONQUE))
        self.assertIn(TRONQUE, md)
        j, md = self._lire("migration")
        self.assertTrue(C.contient_texte(j, "fantome"), "dépôt autorisé inaccessible absent du rapport")
        self.assertIn("fantome", md)

    def test_limites_de_scan(self):
        j, md = self._lire("scan-limits")
        for rapport in (j, md):
            self.assertTrue(C.contient_texte(rapport, "node_modules"), "l'exclusion node_modules/ doit être dite")
        self.assertTrue(C.contient_valeur(j, EXCLU) or any(isinstance(v, int) and not isinstance(v, bool) and v >= 1
                                                          for d in C.dicts(j, lambda d: C.contient_texte(d, "node_modules"))
                                                          for v in C.parcourir(d)),
                        "la limite doit compter (ou citer) le fichier de format pris en charge qu'elle cache")

    def test_non_couverts(self):
        j, md = self._lire("coverage")
        self.assertTrue(C.contient_texte(j, "node_modules"), "couverture : exclus avec leur raison")
        self.assertTrue(C.contient_texte(md, "node_modules"))
        niveau_id, _ = self.asset("jeu-a", NIVEAU)
        j, md = self._lire("orphans")
        self.assertTrue(C.contient_valeur(j, niveau_id), "orphelins : asset jamais utilisé absent")
        self.assertIn(niveau_id, md)
        fouet_id, _ = self.asset("jeu-a", FOUET)
        self.assertFalse(C.contient_valeur(j, fouet_id), "le fouet est utilisé : pas orphelin")
