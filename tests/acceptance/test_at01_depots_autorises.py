"""AT-01 (matrice E111) : « 100 % des dépôts **autorisés et accessibles** sont recensés avec commit de référence. »"""
from __future__ import annotations

from . import _contrat as C
from ._base import MondeScanne


class AT01DepotsAutorises(MondeScanne):
    """AT-01 / E111 — « AT-01 : 100 % des dépôts **autorisés et accessibles** sont recensés avec commit
    de référence. »

    Intention : chaque dépôt de la liste d'autorisation figure au rapport de migration avec SON commit
    de référence (celui de la branche par défaut) ; un dépôt hors liste n'est ni lu, ni copié, ni cité,
    et le demander explicitement est un refus de sécurité (code 3)."""

    def test_chaque_depot_autorise_au_rapport_avec_son_commit(self):
        self.exiger_scan_ok()
        migration = C.lire_json(C.rapport(self.reg, "migration"))
        for nom in ("jeu-a", "jeu-b"):
            commit = self.monde.commits[nom]
            porteurs = C.dicts(migration, lambda d, n=nom: n in d.values())
            self.assertTrue(porteurs, f"{nom} absent du rapport de migration")
            self.assertTrue(any(C.contient_valeur(d, commit) for d in porteurs),
                            f"{nom} : commit de référence {commit} absent de son entrée du rapport")

    def test_rapport_markdown_cite_les_commits(self):
        self.exiger_scan_ok()
        md = C.rapport(self.reg, "migration", "md").read_text(encoding="utf-8")
        for nom in ("jeu-a", "jeu-b"):
            self.assertIn(nom, md)
            self.assertIn(self.monde.commits[nom][:12], md, f"commit de {nom} absent du Markdown")

    def test_depot_non_autorise_ni_lu_ni_cite(self):
        self.exiger_scan_ok()
        for dossier in ("catalog", "generated"):
            for f in (self.reg / dossier).rglob("*"):
                if f.is_file() and f.suffix in (".json", ".md"):
                    texte = f.read_text(encoding="utf-8", errors="replace")
                    self.assertNotIn("intrus-secret", texte, f"contenu du dépôt intrus dans {f}")
                    self.assertNotIn(str(self.monde.depot("intrus")), texte, f"chemin de l'intrus dans {f}")
                    self.assertNotIn(self.monde.commits["intrus"], texte, f"commit de l'intrus dans {f}")
        self.assertFalse([p for p in self.monde.cache.rglob("*intrus*")], "un miroir de l'intrus a été créé")

    def test_scan_d_un_depot_exclu_ou_inconnu_refuse_code_3(self):
        for nom in ("intrus", "depot-inconnu"):
            avant = C.empreinte_arbre(self.reg / "catalog")
            r = self.ctl(C.cmd_scan(self.monde.cache, "--only", nom))
            self.exiger_code(r, C.REFUS)
            self.assertEqual(avant, C.empreinte_arbre(self.reg / "catalog"), "un refus ne doit rien écrire")
            self.assertFalse([p for p in self.monde.cache.rglob(f"*{nom}*")], f"miroir créé pour {nom}")


class AT01DepotInaccessible(MondeScanne):
    """AT-01 / E111 — « autorisés **et accessibles** » : un dépôt autorisé mais inaccessible n'empêche pas
    de recenser les autres, et son échec est écrit au rapport (jamais passé sous silence)."""

    FANTOME = True

    def test_inaccessible_signale_et_les_autres_recenses(self):
        self.assertIn(self.scan.code, (C.OK, C.ECHEC, C.ERREUR_ES), str(self.scan))
        migration = C.lire_json(C.rapport(self.reg, "migration"))
        self.assertTrue(C.contient_valeur(migration, "fantome") or C.contient_texte(migration, "fantome"),
                        "le dépôt autorisé inaccessible doit figurer au rapport, avec son échec")
        for nom in ("jeu-a", "jeu-b"):
            self.assertTrue(C.contient_valeur(migration, self.monde.commits[nom]),
                            f"{nom} doit rester recensé malgré l'échec d'un autre dépôt")
