"""AT-05 (matrice E115) : « chaque asset possède un ID stable, un univers, un statut, une description et une provenance ou un `unknown` explicite. »"""
from __future__ import annotations

import json
import re

from . import _contrat as C
from ._base import MondeScanne

STATUTS = {"draft", "needs-review", "active", "deprecated", "published"}
TYPES_PROVENANCE = {"original-sheet-cut", "repo-file", "code-generated", "derived", "generated", "unknown"}
FORME_ID = re.compile(r"^asset-[a-z0-9]+(-[a-z0-9]+)*-\d{4}$")


class AT05MetadonneesMinimales(MondeScanne):
    """AT-05 / E115 — « AT-05 : chaque asset possède un ID stable, un univers, un statut, une description
    et une provenance ou un `unknown` explicite. »

    Intention : pour chaque asset importé, `id` (forme du brief L1, égal au nom du fichier, présent au
    registre d'IDs), `originUniverse`, `status`, `description` non vides, `provenance.type` connu
    (`unknown` explicite permis, jamais absent) ; `validate` rend 0 — et rend 1 si l'on retire une
    description (témoin : validate vérifie vraiment)."""

    def test_chaque_asset_porte_les_champs(self):
        self.exiger_scan_ok()
        tous = C.assets(self.reg)
        self.assertTrue(tous)
        ids = set(v for v in C.parcourir(C.lire_json(self.reg / C.FICHIER_IDS)) if isinstance(v, str))
        for fichier, a in tous.items():
            with self.subTest(asset=fichier):
                self.assertEqual(a.get("id"), fichier)
                self.assertRegex(a["id"], FORME_ID)
                self.assertIn(a["id"], ids)
                for champ in ("originUniverse", "description"):
                    self.assertIsInstance(a.get(champ), str)
                    self.assertTrue(a[champ].strip(), f"{champ} vide")
                self.assertIn(a.get("status"), STATUTS)
                prov = a.get("provenance")
                self.assertIsInstance(prov, dict, "provenance absente : `unknown` doit être explicite")
                self.assertIn(prov.get("type"), TYPES_PROVENANCE)
                self.assertIn("license", a, "licence absente : `unknown` doit être explicite")

    def test_validate_rend_0_puis_1_sans_description(self):
        self.exiger_scan_ok()
        self.exiger_code(self.ctl(C.cmd_validate()), C.OK)
        asset_id = sorted(C.assets(self.reg))[0]
        chemin = self.reg / C.DOSSIER_ASSETS / f"{asset_id}.json"
        original = chemin.read_bytes()
        try:
            a = json.loads(original)
            del a["description"]
            chemin.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")
            self.exiger_code(self.ctl(C.cmd_validate()), C.ECHEC)
        finally:
            chemin.write_bytes(original)
        self.exiger_code(self.ctl(C.cmd_validate()), C.OK)
