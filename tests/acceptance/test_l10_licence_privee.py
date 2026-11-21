"""L10 (HL-538 7-3162, HL-537 7-3167) : licence privée de David et autorisation explicite de publication par jeu.

Règle de David : « utilisable dans SES jeux, jamais exposé publiquement sans son accord ».
- PASSENT : un jeu dont toutes les copies sont privées (forge privée, dépôt GitHub privé des assets) ;
  un jeu public qui porte l'autorisation explicite (`publicationGrants`) pour cette licence, à travers ce jeu.
- BLOQUÉS : un jeu public sans autorisation ; `publish --target public` (aucun jeu) ; la planche source,
  même vers le jeu autorisé ; un asset privé non employé par le jeu autorisé, publié directement.
Chaque cas a sa contre-épreuve : le même geste sans la condition qui le permet est refusé."""
from __future__ import annotations

import json

from . import _contrat as C
from ._base import MondeScanne
from ._monde import BOUTON_B, FOUET, PLANCHE, NIVEAU, _depot

LICENCE = "LicenseRef-David-Prive-Tous-Droits-Reserves"
PREUVE = {"method": "décision du propriétaire", "ref": "HL-538 7-3162",
          "decision": "Dessins de David : privé, tous droits réservés."}
GRANT = {"license": LICENCE, "ref": "HL-537 7-3167", "decision": "Publication du jeu autorisée par David."}


class L10LicencePrivee(MondeScanne):

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        m = cls.monde
        fichiers = {"package.json": '{"name": "x", "private": true}\n'}
        for nom, date in (("jeu-prive", "2026-02-04T10:00:00+00:00"), ("jeu-public", "2026-02-05T10:00:00+00:00"),
                          ("jeu-autorise", "2026-02-06T10:00:00+00:00")):
            m.commits[nom] = _depot(m, nom, dict(fichiers), date)
        chemin = m.registre / C.SOURCES
        sources = json.loads(chemin.read_text(encoding="utf-8"))
        prive = C.source_locale("jeu-prive", m.depot("jeu-prive"))
        prive["copies"][0]["visibility"] = "private"
        public = C.source_locale("jeu-public", m.depot("jeu-public"))
        public["copies"][0]["visibility"] = "public"
        autorise = C.source_locale("jeu-autorise", m.depot("jeu-autorise"))
        autorise["copies"][0]["visibility"] = "public"
        autorise["publicationGrants"] = [GRANT]
        sources["sources"] += [prive, public, autorise]
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

    def test_jeu_public_sans_autorisation_refuse(self):
        r = self._usage(FOUET, "jeu-public", "assets/fouet.png")
        self.exiger_refus_public(r)
        self.assertFalse((self.monde.depot("jeu-public") / "assets/fouet.png").exists(), "un refus n'écrit rien")
        self.assertFalse((self.monde.depot("jeu-public") / C.LOCK_JEU).exists())

    def test_jeu_autorise_passe_et_check_lock_public(self):
        r = self._usage(NIVEAU, "jeu-autorise", "assets/niveau.png")
        self.exiger_code(r, C.OK)
        lock = self.monde.depot("jeu-autorise") / C.LOCK_JEU
        self.exiger_code(self.ctl(C.cmd_check_lock(lock, "--public")), C.OK)
        # Contre-épreuve : le même lock, copié dans le jeu public sans autorisation, est refusé en public.
        copie = self.monde.depot("jeu-public") / "copie.lock.json"
        copie.write_text(lock.read_text(encoding="utf-8"), encoding="utf-8")
        (self.monde.depot("jeu-public") / "assets").mkdir(exist_ok=True)
        (self.monde.depot("jeu-public") / "assets/niveau.png").write_bytes(
            (self.monde.depot("jeu-autorise") / "assets/niveau.png").read_bytes())
        self.exiger_refus_public(self.ctl(C.cmd_check_lock(copie, "--public")))

    def test_planche_source_refusee_meme_vers_le_jeu_autorise(self):
        r = self._usage(PLANCHE, "jeu-autorise", "assets/planche.png")
        self.exiger_refus_public(r)
        self.assertFalse((self.monde.depot("jeu-autorise") / "assets/planche.png").exists())

    def test_asset_non_employe_publie_directement_refuse(self):
        dest = self.monde.racine / "export-prive"
        r = self.ctl(C.cmd_publish([self.prives[BOUTON_B]], "public", dest))
        self.exiger_refus_public(r)
        self.assertFalse(dest.exists() and any(dest.rglob("*")), "un refus ne doit rien écrire")

    def test_materialize_public_refuse_sans_autorisation(self):
        dest = self.monde.depot("jeu-public") / "assets/bouton.png"
        self.exiger_refus_public(self.ctl(C.cmd_materialize(self.prives[BOUTON_B], dest)))
        self.assertFalse(dest.exists())

    def test_manifeste_licences_interdit_l_export_public(self):
        self.exiger_code(self.ctl(C.cmd_index()), C.OK)
        manifeste = C.lire_json(self.reg / C.MANIFESTE_LICENCES)
        for asset_id in self.prives.values():
            lignes = C.dicts(manifeste, lambda d, i=asset_id: d.get("id") == i)
            self.assertTrue(lignes and all(d.get("publicExport") == "forbidden" for d in lignes), lignes)
