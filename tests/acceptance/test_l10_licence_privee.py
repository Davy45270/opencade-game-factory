"""L10 (HL-538 7-3162 ; décision de David du 2026-11-21) : licence privée de David, publiable à travers TOUS ses jeux.

Règle de David : « autorise pour tous mes jeux sans exceptions !!! ». Règle centrale unique (GAME_GRANT) : un dépôt
de rôle `game` de catalog/sources.json est un jeu de David.
- PASSENT : un jeu dont toutes les copies sont privées ; un jeu PUBLIC de David (Capsule, par exemple), pour ce qu'il emploie.
- BLOQUÉS : un dépôt public tiers (absent de sources.json) ; un dépôt public de David qui n'est pas un jeu
  (bibliothèque) ; `publish --target public` (aucun jeu) ; la planche source, même vers un jeu.
Chaque cas a sa contre-épreuve : le même geste vers une destination qui n'est pas un jeu de David est refusé."""
from __future__ import annotations

import json

from . import _contrat as C
from ._base import MondeScanne
from ._monde import BOUTON_B, FOUET, PLANCHE, NIVEAU, _depot

LICENCE = "LicenseRef-David-Prive-Tous-Droits-Reserves"
PREUVE = {"method": "décision du propriétaire", "ref": "HL-538 7-3162",
          "decision": "Dessins de David : privé, tous droits réservés."}


class L10LicencePrivee(MondeScanne):

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        m = cls.monde
        fichiers = {"package.json": '{"name": "x", "private": true}\n'}
        for nom, date in (("jeu-prive", "2026-02-04T10:00:00+00:00"), ("jeu-capsule", "2026-02-05T10:00:00+00:00"),
                          ("depot-tiers", "2026-02-06T10:00:00+00:00"), ("lib-publique", "2026-02-07T10:00:00+00:00")):
            m.commits[nom] = _depot(m, nom, dict(fichiers), date)
        chemin = m.registre / C.SOURCES
        sources = json.loads(chemin.read_text(encoding="utf-8"))
        prive = C.source_locale("jeu-prive", m.depot("jeu-prive"))
        prive["copies"][0]["visibility"] = "private"
        capsule = C.source_locale("jeu-capsule", m.depot("jeu-capsule"))
        capsule["copies"][0]["visibility"] = "public"
        lib = C.source_locale("lib-publique", m.depot("lib-publique"))
        lib["copies"][0]["visibility"] = "public"
        lib["role"] = "shared-library"
        # depot-tiers n'est PAS déclaré : un dépôt public qui n'est pas à David
        sources["sources"] += [prive, capsule, lib]
        chemin.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        cls.prives = {}
        for depot, fichier in (("jeu-a", FOUET), ("jeu-a", NIVEAU), ("jeu-a", PLANCHE), ("jeu-b", BOUTON_B)):
            asset_id, _ = C.asset_par_chemin(m.registre, depot, fichier)
            fiche = m.registre / "catalog" / "assets" / f"{asset_id}.json"
            a = json.loads(fiche.read_text(encoding="utf-8"))
            a["license"], a["licenseEvidence"] = LICENCE, PREUVE
            fiche.write_text(json.dumps(a, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            cls.prives[fichier] = asset_id
        m.commiter_registre("L10 : licence privée et autorisation par jeu")

    def setUp(self):
        self.exiger_scan_ok()

    def exiger_refus_public(self, r):
        """Refus de la GARDE de publication, pas un refus d'une autre cause (catalogue non commité…)."""
        self.exiger_code(r, C.REFUS)
        self.assertIn("Export public interdit", (r.json or {}).get("message", ""), r)

    def _usage(self, cle: str, jeu: str, chemin: str):
        return self.ctl(C.cmd_usage_add(self.prives[cle], jeu, "Monde", "sprite", self.monde.depot(jeu), chemin))

    def test_schema_accepte_la_licence_privee(self):
        self.exiger_code(self.ctl(["validate", "--json"]), C.OK)

    def test_jeu_prive_passe(self):
        r = self._usage(FOUET, "jeu-prive", "assets/fouet.png")
        self.exiger_code(r, C.OK)
        self.assertTrue((self.monde.depot("jeu-prive") / "assets/fouet.png").is_file())

    def test_jeu_public_de_david_passe_et_check_lock_public(self):
        r = self._usage(NIVEAU, "jeu-capsule", "assets/niveau.png")
        self.exiger_code(r, C.OK)
        lock = self.monde.depot("jeu-capsule") / C.LOCK_JEU
        self.exiger_code(self.ctl(C.cmd_check_lock(lock, "--public")), C.OK)
        # Contre-épreuve : le même lock, copié dans un dépôt public tiers, est refusé en public.
        copie = self.monde.depot("depot-tiers") / "copie.lock.json"
        copie.write_text(lock.read_text(encoding="utf-8"), encoding="utf-8")
        (self.monde.depot("depot-tiers") / "assets").mkdir(exist_ok=True)
        (self.monde.depot("depot-tiers") / "assets/niveau.png").write_bytes(
            (self.monde.depot("jeu-capsule") / "assets/niveau.png").read_bytes())
        self.exiger_refus_public(self.ctl(C.cmd_check_lock(copie, "--public")))

    def test_depot_public_tiers_refuse(self):
        r = self._usage(FOUET, "depot-tiers", "assets/fouet.png")
        self.exiger_refus_public(r)
        self.assertFalse((self.monde.depot("depot-tiers") / "assets/fouet.png").exists(), "un refus n'écrit rien")
        self.assertFalse((self.monde.depot("depot-tiers") / C.LOCK_JEU).exists())

    def test_depot_public_de_david_qui_n_est_pas_un_jeu_refuse(self):
        r = self._usage(FOUET, "lib-publique", "assets/fouet.png")
        self.exiger_refus_public(r)
        self.assertFalse((self.monde.depot("lib-publique") / "assets/fouet.png").exists())

    def test_planche_source_refusee_meme_vers_un_jeu(self):
        r = self._usage(PLANCHE, "jeu-capsule", "assets/planche.png")
        self.exiger_refus_public(r)
        self.assertFalse((self.monde.depot("jeu-capsule") / "assets/planche.png").exists())

    def test_asset_non_employe_publie_directement_refuse(self):
        dest = self.monde.racine / "export-prive"
        r = self.ctl(C.cmd_publish([self.prives[BOUTON_B]], "public", dest))
        self.exiger_refus_public(r)
        self.assertFalse(dest.exists() and any(dest.rglob("*")), "un refus ne doit rien écrire")

    def test_materialize_vers_un_depot_tiers_refuse(self):
        dest = self.monde.depot("depot-tiers") / "assets/bouton.png"
        self.exiger_refus_public(self.ctl(C.cmd_materialize(self.prives[BOUTON_B], dest)))
        self.assertFalse(dest.exists())

    def test_manifeste_licences_interdit_l_export_public(self):
        self.exiger_code(self.ctl(C.cmd_index()), C.OK)
        manifeste = C.lire_json(self.reg / C.MANIFESTE_LICENCES)
        for asset_id in self.prives.values():
            lignes = C.dicts(manifeste, lambda d, i=asset_id: d.get("id") == i)
            self.assertTrue(lignes and all(d.get("publicExport") == "forbidden" for d in lignes), lignes)
