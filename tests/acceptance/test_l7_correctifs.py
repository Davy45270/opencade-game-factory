"""L7 — Correctifs de la relecture adverse n° 2 de `34a1455^..4e72ab0` (HL-538).

Source : `.codex-logs/run-rev2-last.md` (constats B1, M1, M2, M3, M4 et mutation M13) et inventaire réel du
19/11 (pestouille-rpg). Oracles écrits AVANT le code par Claude, ROUGES sur `4e72ab0` pour la raison décrite
dans chaque docstring, sauf les témoins (verts : ils interdisent un contournement) et `L7UsageAddCatalogueSale…`
(vert aujourd'hui, rouge sous la mutation M13).

Arbitrage du coordinateur (HL-538, 19/11) :

    « Licence : (b). La licence de la planche ne s'étend à un asset que si l'on prouve qu'il en dérive, et
    c'est la découpe vérifiée qui le prouve. Sans elle, la licence déclarée par le jeu reste un indice :
    l'asset est `derived` ou `unverified`, pas CC-BY. Une seule règle, quelle que soit la voie, déclarative
    comprise. Oracle : une entrée de provenance.json avec `licence: CC-BY-4.0` et une découpe non vérifiée ne
    donne PAS CC-BY. »

Périmètre L7 : B1, M1, M2, M3, M4, oracle M13, (b). Critère de convergence : est bloquant un faux droit ou une
fausse provenance sur un usage honnête.

Constats et contrats :

1. (b) — pestouille-rpg : 142 assets ont reçu CC-BY par `licenseEvidence.method == "provenance-file"`,
   « Licence SPDX déclarée », avec une RMSE de 0,020 à 0,033 (découpe NON vérifiée). Contrat
   `L7LicenceDeclareeSansDecoupeVerifiee` : une licence déclarée dans provenance.json ne s'applique pas sans
   découpe vérifiée (RMSE ≤ 0,02) ; l'asset reste `unknown` et n'est pas `original-sheet-cut`.
2. B1 — `check-lock --public` prend les droits dans le catalogue de travail, pas au `registryCommit`.
   Contrat `L7CheckLockDroitsAuCommitAtteste` : licence et preuve de la révision verrouillée sont résolues au
   commit attesté ; refus (3, comme L5) si ce commit ne les porte pas.
3. M1 — le choix de copie peut reculer : copie en avance indisponible ou filtre fournisseur → la copie en
   retard est importée. Contrat `L7CopieAvanceeIndisponible` : aucun recul ; code 4 (ou 3) et catalogue
   (fiches, planches, ids) octet pour octet inchangé.
4. M2 — la preuve de publication est réinscriptible, et l'adresse du magasin facultative. Contrat
   `L7PreuveDePublicationImmuable` : republier la même révision avec d'autres droits est refusé, détecté par
   `validate --base`, ou conserve la preuve d'origine ; une publication hors `published/sha256/<sha>.<ext>`
   est rejetée par `validate` (1).
5. M3 — `usage add` reconduit un lock dont une ligne ne correspond plus à ses octets. Contrat
   `L7UsageAddRevalideToutLeLock` : refus (1 ou 3), lock inchangé, rien d'écrit.
6. M4 — un raccord dont les cibles couvrent toute la découpe efface la preuve visuelle (RMSE 0,000). Contrat
   `L7RaccordsCouvertureMaximale` : couverture cumulée des cibles au-delà de 50 % de la découpe → pas de région
   vérifiée. DÉCISION À CONFIRMER par le coordinateur : 50 %. Ce seuil laisse passer le raccord L6
   (`test_raccord_rejoue_mesure_sous_le_seuil` : cible 30×10 sur 48×24 ≈ 26 %) et refuse 75 % et 100 %.
7. M13 — supprimer le contrôle `git status` de `usage_head` ne fait rougir aucun test. Contrat
   `L7UsageAddCatalogueSaleHeadCorrect` : HEAD contient bien l'asset demandé, mais UNE AUTRE fiche est modifiée
   sans commit → refus 3, « commite le catalogue », aucun lock.

Boîte noire : CLI `assetctl … --json`, codes de docs/ARCHITECTURE.md (0 succès, 1 contrôle, 2 usage, 3 refus,
4 source indisponible, 5 conflit), `catalog/assets/*.json`, `catalog/sheets/*.json`, `generated/reports/`.
Fixtures synthétiques seulement : aucun dépôt réel, aucun réseau.
"""

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import unittest

import numpy as np
from PIL import Image

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M

SEUIL = 0.02          # spec : seuil de vérification des découpes ; L7 ne le relève pas
COUVERTURE_MAX = 0.5  # M4 : décision à confirmer (voir docstring de module)
NOUVEAU = M.png(M.uni(16, 12, (33, 121, 213, 255)))
PREUVE = ["LICENSE de fixture (oracle L7)"]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bruit(h: int, w: int, graine: int) -> np.ndarray:
    rng = np.random.default_rng(graine)
    a = rng.integers(40, 216, size=(h, w, 4), dtype=np.int32)
    a[..., 3] = 255
    return a


def _geo(s: str) -> tuple[int, int, int, int]:
    w, rest = s.split("x")
    h, x, y = (int(v) for v in rest.split("+"))
    return int(w), h, x, y


def _atlas(cadres: dict[str, np.ndarray], image: str) -> tuple[bytes, dict]:
    """Atlas JSON-hash horizontal, sans rognage ni rotation (repris de L6)."""
    hauteur = max(c.shape[0] for c in cadres.values()) + 4
    largeur = sum(c.shape[1] + 2 for c in cadres.values()) + 2
    img = np.zeros((hauteur, largeur, 4), np.int32)
    frames, x = {}, 2
    for nom, px in cadres.items():
        h, w = px.shape[:2]
        img[2:2 + h, x:x + w] = px
        frames[nom] = {"frame": {"x": x, "y": 2, "w": w, "h": h}, "rotated": False, "trimmed": False,
                       "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h}, "sourceSize": {"w": w, "h": h},
                       "duration": 100}
        x += w + 2
    return M.png(img), {"frames": frames, "meta": {"app": "fixture", "image": image, "format": "RGBA8888",
                                                   "size": {"w": largeur, "h": hauteur}, "scale": "1"}}


def _ajouter_jeu(test, nom: str, fichiers: dict):
    world = test.world
    world.commits[nom] = M._depot(world, nom, fichiers, "2026-02-04T10:00:00+00:00")
    chemin = world.registre / C.SOURCES
    doc = C.lire_json(chemin)
    doc[C.CLE_SOURCES].append(C.source_locale(nom, world.depot(nom)))
    chemin.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    world.commiter_registre(f"Registre de fixture : source {nom}")


def _scan(test, *extra):
    r = test.world.scan(*extra)
    test.assertEqual(r.code, C.OK, f"fixture : scan-repos en échec\n{r}")
    return r


def _sprite(test, cadre: str) -> tuple[str, dict]:
    trouves = [(i, a) for i, a in C.assets(test.reg).items()
               if isinstance(a.get("family"), dict) and a["family"].get("sprite", {}).get("frameName") == cadre]
    test.assertEqual(len(trouves), 1, f"un sprite {cadre} attendu : {[i for i, _ in trouves]}")
    return trouves[0]


def _regions(test, asset_id: str) -> list[dict]:
    return [r for p in C.planches(test.reg).values() for r in p.get("regions", []) if r.get("assetId") == asset_id]


def _rmse_mesurees(regions: list[dict]) -> list[float]:
    return [r["evidence"]["value"] for r in regions
            if isinstance(r.get("evidence"), dict) and r["evidence"].get("method") == "rmse"]


def _modifier_fiche(registre, asset_id, **champs):
    chemin = registre / C.DOSSIER_ASSETS / f"{asset_id}.json"
    fiche = C.lire_json(chemin)
    fiche.update(champs)
    chemin.write_text(json.dumps(fiche, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return fiche


def _ecrire_lock(dossier, registry_commit, lignes, jeu="jeu-lock"):
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / C.LOCK_JEU
    chemin.write_text(json.dumps({"schemaVersion": "1.0", "game": jeu, "registryCommit": registry_commit,
                                  "assets": lignes}, indent=2) + "\n", encoding="utf-8")
    return chemin


def _ligne(asset_id, version, sha, path="assets/fouet.png"):
    return {"assetId": asset_id, "assetVersion": str(version), "sha256": sha, "scene": "Cuisine",
            "role": "sprite", "path": path}


def _empreinte_catalogue(registre) -> str:
    """Fiches, planches et table d'IDs : ce qui porte droits et provenance. Les journaux d'import et les
    références de scan peuvent légitimement tracer l'échec ; ils ne sont pas comparés."""
    h = hashlib.sha256()
    for f in sorted([*(registre / C.DOSSIER_ASSETS).glob("*.json"), *(registre / C.DOSSIER_PLANCHES).glob("*.json"),
                     registre / C.FICHIER_IDS]):
        if f.is_file():
            h.update(f.relative_to(registre).as_posix().encode() + b"\0" + f.read_bytes() + b"\n")
    return h.hexdigest()


class _Monde(unittest.TestCase):
    """Un monde neuf par test : chaque scénario part de zéro."""

    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        self.reg = self.world.registre
        self.jeu = self.world.depot("jeu-a")
        self.orig = (self.jeu / M.FOUET).read_bytes()


# ------------------------------------------------------------------------------------------------
# 1. (b) Licence déclarée sans découpe vérifiée
# ------------------------------------------------------------------------------------------------

BOITE_L = [40, 30, 120, 300]  # w, h, x, y sur la planche 512×512


def _fichiers_jeu_l() -> dict:
    """Planche + atlas + provenance.json : deux entrées `origine: "planche"`, `licence: "CC-BY-4.0"`,
    `planche_sha256` exact. Le cadre `sprite-l-conforme` est la boîte telle quelle (RMSE 0) ; le cadre
    `sprite-l-ecart` est la boîte décalée de +8/255 sur chaque canal (RMSE ≈ 0,031, comme pestouille)."""
    w, h, x, y = BOITE_L
    cadre = _bruit(h, w, 23)
    planche = np.zeros((512, 512, 4), np.int32)
    planche[y:y + h, x:x + w] = cadre
    planche_png = M.png(planche)
    ecart = cadre.copy()
    ecart[..., :3] += 8
    atlas_png, atlas_json = _atlas({"sprite-l-conforme": cadre, "sprite-l-ecart": ecart}, "l.png")
    entree = {"origine": "planche", "planche": "Planche_L.png", "planche_sha256": _sha(planche_png),
              "boite": BOITE_L, "marge": 0, "ancre": "centre", "transformations": ["crop", "atlas json-hash"],
              "licence": "CC-BY-4.0"}
    provenance = {"schemaVersion": 1, "outils": {"magick": "fixture"},
                  "assets": [dict(entree, id=n) for n in ("sprite-l-conforme", "sprite-l-ecart")]}
    return {
        "package.json": json.dumps({"name": "jeu-l", "private": True}) + "\n",
        "assets/source/Planche_L.png": planche_png,
        "assets/provenance.json": json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        "public/assets/atlas/l.png": atlas_png,
        "public/assets/atlas/l.json": json.dumps(atlas_json, indent=2) + "\n",
    }


class L7LicenceDeclareeSansDecoupeVerifiee(_Monde):
    """Arbitrage (b) : « une entrée de provenance.json avec `licence: CC-BY-4.0` et une découpe non vérifiée ne
    donne PAS CC-BY. »

    ROUGE sur 4e72ab0 : `sheets._apply_declaration` assigne la licence SPDX déclarée (`provenance-file`,
    « Licence SPDX déclarée ») AVANT et INDÉPENDAMMENT de la mesure ; le sprite à RMSE ≈ 0,031 sort CC-BY-4.0.
    Témoin (vert) : même entrée, cadre conforme → CC-BY-4.0 et `original-sheet-cut`."""

    def setUp(self):
        super().setUp()
        _ajouter_jeu(self, "jeu-l", _fichiers_jeu_l())
        _scan(self)

    def test_decoupe_non_verifiee_pas_de_cc_by(self):
        asset_id, fiche = _sprite(self, "sprite-l-ecart")
        mesures = _rmse_mesurees(_regions(self, asset_id))
        self.assertTrue(mesures and min(mesures) > SEUIL,
                        f"fixture : la découpe est mesurée et au-dessus de {SEUIL} : {mesures}")
        self.assertNotEqual(fiche.get("license"), "CC-BY-4.0",
                            "licence déclarée + découpe NON vérifiée : pas de CC-BY (arbitrage b) ; "
                            f"licenseEvidence = {fiche.get('licenseEvidence')}")
        self.assertEqual(fiche.get("license"), "unknown",
                         "sans découpe vérifiée, la licence déclarée reste un indice : `unknown`")
        self.assertNotEqual(fiche["provenance"].get("type"), "original-sheet-cut",
                            f"découpe non vérifiée : provenance non prouvée : {fiche['provenance']}")

    def test_temoin_decoupe_verifiee_cc_by(self):
        asset_id, fiche = _sprite(self, "sprite-l-conforme")
        mesures = _rmse_mesurees(_regions(self, asset_id))
        self.assertTrue(mesures and min(mesures) <= SEUIL, f"fixture : découpe vérifiée : {mesures}")
        self.assertEqual(fiche.get("license"), "CC-BY-4.0", "découpe vérifiée : la licence de la planche s'étend")
        self.assertEqual(fiche["provenance"].get("type"), "original-sheet-cut")


# ------------------------------------------------------------------------------------------------
# 2. B1 — check-lock --public : droits au commit attesté
# ------------------------------------------------------------------------------------------------

class L7CheckLockDroitsAuCommitAtteste(_Monde):
    """Constat B1 : « L'objet soumis à la garde provient de `delivery.assets`, donc du catalogue de travail.
    Une sonde a renvoyé 0 pour un commit simulé où v1 est `unknown`, avec les mêmes octets dans le jeu et une
    preuve MIT fournie uniquement par la fiche de travail. Le problème vaut aussi pour une preuve ajoutée dans
    un commit ultérieur sans changement de numéro ni de SHA. » (delivery.py:373–398)

    Contrat : `check-lock --public` résout licence et preuve de la révision verrouillée AU `registryCommit`.
    Si ce commit ne les porte pas : refus, code 3 (même code que L5 pour un refus de droits).
    ROUGE sur 4e72ab0 : la garde lit la fiche de travail (MIT + preuve) et rend 0.
    Témoin (vert) : commit où la v1 est déjà MIT + preuve → 0."""

    def _lock(self, commit, asset_id, sha):
        dossier = self.world.racine / "jeu-lock"
        (dossier / "assets").mkdir(parents=True, exist_ok=True)
        (dossier / "assets" / "fouet.png").write_bytes(self.orig)
        return _ecrire_lock(dossier, commit, [_ligne(asset_id, 1, sha)])

    def _v1_unknown(self):
        _scan(self)
        asset_id, v1 = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        self.assertEqual(v1.get("license"), "unknown", "fixture : v1 sans licence au commit attesté")
        return asset_id, v1, self.world.commiter_registre("Catalogue : fouet v1 unknown")

    def test_preuve_dans_le_catalogue_de_travail_seulement(self):
        asset_id, v1, commit = self._v1_unknown()
        _modifier_fiche(self.reg, asset_id, license="MIT", licenseEvidence=PREUVE)  # NON commité
        lock = self._lock(commit, asset_id, v1["sha256"])
        r = self.world.ctl(C.cmd_check_lock(lock, "--public"))
        self.assertEqual(r.code, C.REFUS, "au registryCommit, la v1 est `unknown` : --public doit refuser (3), "
                                          f"la preuve MIT n'existe que dans le catalogue de travail\n{r}")

    def test_preuve_ajoutee_dans_un_commit_ulterieur(self):
        asset_id, v1, commit = self._v1_unknown()
        _modifier_fiche(self.reg, asset_id, license="MIT", licenseEvidence=PREUVE)
        plus_tard = self.world.commiter_registre("Catalogue : MIT sur la v1, même numéro, même SHA")
        self.assertNotEqual(plus_tard, commit)
        lock = self._lock(commit, asset_id, v1["sha256"])
        r = self.world.ctl(C.cmd_check_lock(lock, "--public"))
        self.assertEqual(r.code, C.REFUS, "le lock atteste le commit où la v1 est `unknown` : --public doit "
                                          f"refuser (3), même si un commit ULTÉRIEUR porte MIT\n{r}")

    def test_temoin_droits_presents_au_commit_atteste(self):
        _scan(self)
        asset_id, v1 = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        _modifier_fiche(self.reg, asset_id, license="MIT", licenseEvidence=PREUVE)
        commit = self.world.commiter_registre("Catalogue : fouet v1 MIT prouvé")
        lock = self._lock(commit, asset_id, v1["sha256"])
        r = self.world.ctl(C.cmd_check_lock(lock, "--public"))
        self.assertEqual(r.code, C.OK, f"témoin : MIT + preuve au commit attesté, --public accepte\n{r}")


# ------------------------------------------------------------------------------------------------
# 3. M1 — la copie en avance devient indisponible : pas de recul
# ------------------------------------------------------------------------------------------------

GITHUB = "https://github.com/fixture/jeu-a"
FORGEJO = "https://forgejo.pingfr.duckdns.org/fixture/jeu-a"


def _miroir(world, provider, url):
    """Copie « distante » simulée (reprise de tests/unit/test_branche_defaut.py) : miroir nu au commit COURANT
    du dépôt de fixture."""
    mirror = world.cache / provider / "jeu-a.git"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    world.git(world.depot("jeu-a"), "clone", "--mirror", "--no-local", ".", str(mirror))
    if url:
        world.git(mirror, "remote", "set-url", "origin", url)
    return mirror


class L7CopieAvanceeIndisponible(_Monde):
    """Constat M1 : « Avec GitHub en `A` et Forgejo en `B`, où `A` est ancêtre de `B`, Forgejo gagne. Si son
    miroir devient indisponible, `_divergences` reçoit seulement GitHub et ne produit aucun signalement de
    divergence. Un scan complet peut alors importer `A`, promouvoir son contenu à un nouveau numéro et
    sauvegarder avant de retourner 4. […] Un filtre fournisseur, lui, peut sélectionner la copie en retard et
    retourner 0. » (scan.py:104–173, :246–296)

    Montage : GitHub et locale en A (premier commit), Forgejo en B (fouet remplacé, B descend de A). Premier
    scan `--no-fetch` : B importé (la plus avancée). Contrat : ensuite, ni la perte du miroir Forgejo ni
    `--provider github` ne font importer A ; code 4 (ou 3) et fiches, planches, ids octet pour octet inchangés.
    ROUGE sur 4e72ab0 : A est importé (nouvelle version courante au contenu d'origine), code 4 / code 0."""

    def setUp(self):
        super().setUp()
        _miroir(self.world, "github", GITHUB)
        _miroir(self.world, "local", None)
        self.world.git(self.world.cache / "local" / "jeu-a.git", "remote", "set-url", "origin",
                       self.jeu.as_uri())
        self.a = self.world.commits["jeu-a"]
        self.b = M.ajouter_commit(self.world, "jeu-a", {M.FOUET: NOUVEAU}, (), "2026-03-06T10:00:00+00:00",
                                  "B : fouet remplacé")
        _miroir(self.world, "forgejo", FORGEJO)

        def mutate(document):
            source = next(e for e in document["sources"] if e["name"] == "jeu-a")
            source["copies"].extend([
                {"provider": "github", "url": GITHUB, "visibility": "public"},
                {"provider": "forgejo", "url": FORGEJO, "visibility": "private"}])
            for entry in document["sources"]:
                for copy in entry["copies"]:
                    copy["defaultBranch"] = "main"
        doc = C.lire_json(self.reg / C.SOURCES)
        mutate(doc)
        (self.reg / C.SOURCES).write_text(json.dumps(doc), encoding="utf-8")
        _scan(self, "--no-fetch", "--only", "jeu-a")
        _, fiche = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        self.assertEqual(fiche["sha256"], _sha(NOUVEAU), "fixture : la copie en avance (B, Forgejo) est importée")
        self.world.commiter_registre("Catalogue : B importé")
        self.avant = _empreinte_catalogue(self.reg)

    def _pas_de_recul(self, r):
        _, fiche = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        self.assertEqual(fiche["sha256"], _sha(NOUVEAU),
                         f"la copie en retard (A) ne doit pas redevenir courante : {fiche.get('versions')}\n{r}")
        self.assertEqual(_empreinte_catalogue(self.reg), self.avant,
                         f"aucune mutation des fiches, planches ou ids quand l'autorité manque\n{r}")
        self.assertIn(r.code, (C.ERREUR_ES, C.REFUS), f"autorité indisponible : code 4 (ou refus 3)\n{r}")

    def test_miroir_de_la_copie_en_avance_indisponible(self):
        shutil.rmtree(self.world.cache / "forgejo" / "jeu-a.git")
        r = self.world.scan("--no-fetch", "--only", "jeu-a")
        self._pas_de_recul(r)

    def test_filtre_fournisseur_sur_la_copie_en_retard(self):
        r = self.world.scan("--no-fetch", "--only", "jeu-a", "--provider", "github")
        self._pas_de_recul(r)


# ------------------------------------------------------------------------------------------------
# 4. M2 — la preuve de publication est immuable, l'adresse du magasin obligatoire
# ------------------------------------------------------------------------------------------------

class L7PreuveDePublicationImmuable(_Monde):
    """Constat M2 : « Pour une révision qui était courante dans la base, republier au même chemin remplace
    toute la preuve, y compris licence et provenance. […] À la première inscription d'une publication, une
    fiche peut aussi désigner un fichier ailleurs dans le registre, car le validateur n'impose l'adresse SHA
    que si le chemin commence déjà par `published`. » (validate/__init__.py:160–179, :245–268)

    Contrat A : après `publish` de la v1 sous MIT (commit de base), changer les droits et republier la même
    révision au même chemin du magasin est (i) refusé par `publish`, ou (ii) détecté par `validate --base`
    (code 1, problème qui cite la fiche), ou (iii) sans perte : la preuve MIT d'origine reste dans
    `versions[0]`. ROUGE sur 4e72ab0 : publish rend 0, `versions[0].publication` est remplacée par CC0 et
    `validate --base` rend 0.

    Contrat B : une publication dont `registry` n'est pas `published/sha256/<sha>.<ext>` est rejetée par
    `validate` (code 1, problème qui cite la fiche). ROUGE sur 4e72ab0 : l'adresse n'est contrôlée que si le
    chemin commence par `published`."""

    def test_republier_avec_d_autres_droits(self):
        _scan(self)
        asset_id, _ = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        _modifier_fiche(self.reg, asset_id, license="MIT", licenseEvidence=PREUVE)
        self.world.commiter_registre("Catalogue : fouet MIT")
        r = self.world.ctl(C.cmd_publish([asset_id], "public", self.world.racine / "export-1"))
        self.assertEqual(r.code, C.OK, f"fixture : première publication\n{r}")
        base = self.world.commiter_registre("Registre après publication MIT")
        fiche = C.assets(self.reg)[asset_id]
        self.assertEqual(fiche["versions"][0]["publication"].get("license"), "MIT", "fixture : preuve MIT")
        chemin_publie = fiche["versions"][0]["publication"]["registry"]
        _modifier_fiche(self.reg, asset_id, license="CC0-1.0", licenseEvidence=["autre preuve (oracle L7)"])
        second = self.world.ctl(C.cmd_publish([asset_id], "public", self.world.racine / "export-2"))
        if second.code != C.OK:
            return  # (i) refusé
        fiche = C.assets(self.reg)[asset_id]
        self.assertEqual(fiche["versions"][0]["publication"].get("registry"), chemin_publie,
                         "fixture : même révision, même chemin du magasin")
        if C.contient_valeur(fiche["versions"][0], "MIT") and C.contient_texte(fiche["versions"][0], PREUVE[0]):
            return  # (iii) la preuve d'origine est conservée
        v = self.world.ctl(C.cmd_validate("--base", base))
        self.assertEqual(v.code, C.ECHEC, "republier la v1 a remplacé la preuve MIT par CC0 : publish doit "
                                          "refuser, conserver la preuve, ou `validate --base` doit le détecter "
                                          f"(code 1)\n{second}\n{v}")
        self.assertIn(f"catalog/assets/{asset_id}.json", v.stdout, f"le problème cite la fiche\n{v}")

    def test_publication_hors_du_magasin_rejetee(self):
        _scan(self)
        asset_id, fiche = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        ailleurs = "sources/fouet-copie.png"
        (self.reg / ailleurs).parent.mkdir(parents=True, exist_ok=True)
        (self.reg / ailleurs).write_bytes(self.orig)  # octets exacts : seule l'adresse est fautive
        versions = fiche.get("versions") or [{"version": 1, "sha256": fiche["sha256"], "previousVersion": None,
                                              "nextVersion": None}]
        versions[0]["publication"] = {"status": "published", "license": "MIT", "licenseEvidence": PREUVE,
                                      "provenance": fiche["provenance"], "registry": ailleurs}
        champs = {"status": "published", "license": "MIT", "licenseEvidence": PREUVE, "versions": versions,
                  "version": fiche.get("version", 1)}
        temoin = self.world.ctl(C.cmd_validate())
        self.assertEqual(temoin.code, C.OK, f"fixture : catalogue valide avant l'inscription\n{temoin}")
        _modifier_fiche(self.reg, asset_id, **champs)
        v = self.world.ctl(C.cmd_validate())
        self.assertEqual(v.code, C.ECHEC, f"publication inscrite hors de published/sha256/<sha> : code 1\n{v}")
        self.assertIn(f"catalog/assets/{asset_id}.json", v.stdout, f"le problème cite la fiche\n{v}")


# ------------------------------------------------------------------------------------------------
# 5. M3 — usage add revalide tout le lock
# ------------------------------------------------------------------------------------------------

DEST_A = "public/assets/reutilise/fouet.png"
DEST_B = "public/assets/reutilise/niveau.png"


class L7UsageAddRevalideToutLeLock(_Monde):
    """Constat M3 : « Pour les lignes conservées, seul le couple numéro–SHA dans HEAD est contrôlé. Si une
    ancienne ligne pointe vers un fichier supprimé ou modifié, l'ajout d'un second asset réussit et estampille
    le lock entier avec HEAD. » (delivery.py:405–426, :441–479)

    Contrat : `usage add` valide TOUTES les lignes du lock résultant (couple dans HEAD et octets du fichier)
    avant toute écriture ; une ligne dont le fichier est modifié ou supprimé → refus, code 1 (comme
    `check-lock`) ou 3, lock octet pour octet inchangé, fichier du second asset non écrit.
    ROUGE sur 4e72ab0 : code 0, lock réestampillé, second fichier écrit. Témoin (vert) : lock sain → 0."""

    def setUp(self):
        super().setUp()
        _scan(self)
        self.head = self.world.commiter_registre("Catalogue importé")
        self.jeu_b = self.world.depot("jeu-b")
        self.id_a, _ = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        self.id_b, _ = C.asset_par_chemin(self.reg, "jeu-a", M.NIVEAU)
        r = self._usage_add(self.id_a, DEST_A)
        self.assertEqual(r.code, C.OK, f"fixture : première ligne du lock\n{r}")
        self.lock = self.jeu_b / C.LOCK_JEU

    def _usage_add(self, asset_id, dest):
        return self.world.ctl(C.cmd_usage_add(asset_id, "jeu-b", "Menu", "sprite", self.jeu_b, dest,
                                              C.OPTION_CIBLE_PRIVEE))

    def _refus(self):
        avant = self.lock.read_bytes()
        r = self._usage_add(self.id_b, DEST_B)
        self.assertIn(r.code, (C.ECHEC, C.REFUS), f"une ligne existante ne correspond plus à ses octets : "
                                                  f"refus (1 ou 3) attendu\n{r}")
        self.assertEqual(self.lock.read_bytes(), avant, "un refus ne réestampille pas le lock")
        self.assertFalse((self.jeu_b / DEST_B).exists(), "un refus n'écrit pas le fichier du second asset")

    def test_ligne_existante_au_fichier_modifie(self):
        (self.jeu_b / DEST_A).write_bytes(NOUVEAU)
        self._refus()

    def test_ligne_existante_au_fichier_supprime(self):
        (self.jeu_b / DEST_A).unlink()
        self._refus()

    def test_temoin_lock_sain(self):
        r = self._usage_add(self.id_b, DEST_B)
        self.assertEqual(r.code, C.OK, f"témoin : lock sain, usage add accepté\n{r}")
        self.assertEqual({l["assetId"] for l in C.lire_json(self.lock)["assets"]}, {self.id_a, self.id_b})


# ------------------------------------------------------------------------------------------------
# 6. M4 — couverture maximale des raccords
# ------------------------------------------------------------------------------------------------

BOITE_R = [48, 24, 380, 40]  # w, h, x, y sur la planche 512×512 (comme L6)
RACCORDS_COUVRANTS = {
    # nom du cadre : (bande source, zone cible), coordonnées DANS la découpe 48×24
    # 100 % en deux cibles de 50 % chacune : c'est la couverture CUMULÉE qui compte. (Une seule cible pleine
    # rendrait la première ligne uniforme, et le rognage sur la couleur du coin la ferait tomber : la mesure
    # échouerait alors pour une raison étrangère à M4.)
    "sprite-couvre-tout": [("1x24+0+0", "24x24+0+0"), ("1x24+47+0", "24x24+24+0")],
    "sprite-couvre-75": [("1x24+0+0", "36x24+0+0")],   # 75 % : au-delà de COUVERTURE_MAX (décision à confirmer)
}


def _rejouer(decoupe: np.ndarray, paires) -> np.ndarray:
    """Étirement horizontal de bandes d'une colonne, prises dans la découpe D'ORIGINE : chaque ligne de cible
    devient constante, résultat indépendant du filtre de rééchantillonnage."""
    sortie = decoupe.copy()
    for bande, cible in paires:
        bw, bh, bx, by = _geo(bande)
        cw, ch, cx, cy = _geo(cible)
        assert bw == 1 and bh == ch
        sortie[cy:cy + ch, cx:cx + cw] = np.repeat(decoupe[by:by + bh, bx:bx + 1], cw, axis=1)
    return sortie


def _fichiers_jeu_m4() -> dict:
    w, h, x, y = BOITE_R
    decoupe = _bruit(h, w, 31)
    planche = np.zeros((512, 512, 4), np.int32)
    planche[y:y + h, x:x + w] = decoupe
    planche_png = M.png(planche)
    cadres = {nom: _rejouer(decoupe, paires) for nom, paires in RACCORDS_COUVRANTS.items()}
    atlas_png, atlas_json = _atlas(cadres, "m4.png")
    entree = {"origine": "dérivé", "planche": "Planche_M4.png", "planche_sha256": _sha(planche_png),
              "boite": BOITE_R, "transformation": "découpe + nettoyage raster",
              "source_retouche": "assets/source/m4.retouches.json",
              "etapes": ["crop", "retouche raster ImageMagick", "atlas json-hash"]}
    provenance = {"schemaVersion": 1, "outils": {"magick": "fixture"},
                  "assets": [dict(entree, id=nom) for nom in RACCORDS_COUVRANTS]}
    retouches = [{"id": nom.removeprefix("sprite-"), "boite": f"{w}x{h}+{x}+{y}", "raccords": [list(p) for p in paires],
                  "transformation": "découpe + nettoyage raster"} for nom, paires in RACCORDS_COUVRANTS.items()]
    return {
        "package.json": json.dumps({"name": "jeu-m4", "private": True}) + "\n",
        "assets/source/Planche_M4.png": planche_png,
        "assets/source/m4.retouches.json": json.dumps(retouches, ensure_ascii=False, indent=2) + "\n",
        "assets/provenance.json": json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        "public/assets/atlas/m4.png": atlas_png,
        "public/assets/atlas/m4.json": json.dumps(atlas_json, indent=2) + "\n",
    }


class L7RaccordsCouvertureMaximale(_Monde):
    """Constat M4 : « La géométrie exige seulement que chaque bande et chaque cible tiennent dans la découpe.
    La sonde étire un pixel bleu sur une découpe rouge de 16 × 16 et mesure un cadre bleu. Le RMSE passe de
    0,815 à 0,000. […] la région devient `verified`. » (regions.py:107–142, sheets.py:293–315)

    Contrat : quand la couverture cumulée des cibles dépasse COUVERTURE_MAX (50 %, DÉCISION À CONFIRMER) de la
    découpe, la région n'est pas vérifiée : aucune RMSE ≤ 0,02 et aucun statut `verified` (refus de mesure ou
    limite nommée dans scan-limits, au choix de l'implémentation). Compatibilité : le raccord de L6 (≈ 26 %)
    reste sous ce seuil. ROUGE sur 4e72ab0 : RMSE 0 et région `verified` pour 100 % comme pour 75 %."""

    def setUp(self):
        super().setUp()
        _ajouter_jeu(self, "jeu-m4", _fichiers_jeu_m4())
        _scan(self)

    def _non_verifiee(self, cadre):
        asset_id, fiche = _sprite(self, cadre)
        regions = _regions(self, asset_id)
        mesures = _rmse_mesurees(regions)
        self.assertFalse([m for m in mesures if m <= SEUIL],
                         f"{cadre} : des cibles couvrant plus de {COUVERTURE_MAX:.0%} de la découpe effacent la "
                         f"preuve visuelle ; pas de mesure sous {SEUIL} : {mesures}")
        self.assertFalse([r for r in regions if r.get("status") == "verified"],
                         f"{cadre} : région vérifiée malgré une couverture excessive : {regions}")
        self.assertFalse((fiche.get("sourceRegion") or {}).get("verified"), f"{cadre} : {fiche.get('sourceRegion')}")

    def test_cibles_couvrant_toute_la_decoupe(self):
        self._non_verifiee("sprite-couvre-tout")

    def test_cibles_couvrant_75_pourcent(self):
        self._non_verifiee("sprite-couvre-75")


# ------------------------------------------------------------------------------------------------
# 7. Oracle M13 — usage add sur catalogue sale, HEAD correct
# ------------------------------------------------------------------------------------------------

class L7UsageAddCatalogueSaleHeadCorrect(_Monde):
    """Mutation M13 : supprimer `if dirty: raise CatalogueScopeError(COMMIT_CATALOGUE)` dans `usage_head`
    (delivery.py) ne fait rougir aucun test : les cas L6 s'arrêtent aussi sur `args.id not in HEAD`.

    Contrat (arbitrage AT-14 du 19/11) : catalogue commité qui CONTIENT l'asset A au bon couple, mais UNE AUTRE
    fiche modifiée sans commit → `usage add` de A refusé, code 3, message « commite le catalogue », aucun
    lock. VERT sur 4e72ab0 ; ROUGE sous la mutation M13."""

    def test_autre_fiche_modifiee_sans_commit(self):
        _scan(self)
        self.world.commiter_registre("Catalogue importé")
        id_a, _ = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        id_autre, _ = C.asset_par_chemin(self.reg, "jeu-a", M.NIVEAU)
        _modifier_fiche(self.reg, id_autre, name="Niveau renommé sans commit")
        jeu_b = self.world.depot("jeu-b")
        r = self.world.ctl(C.cmd_usage_add(id_a, "jeu-b", "Menu", "sprite", jeu_b, DEST_A, C.OPTION_CIBLE_PRIVEE))
        self.assertEqual(r.code, C.REFUS, f"catalogue non commité (autre fiche) : refus 3 attendu\n{r}")
        self.assertIn("commite le catalogue", (r.stdout + r.stderr).casefold(), str(r))
        self.assertFalse((jeu_b / C.LOCK_JEU).exists(), "un refus n'écrit aucun lock")


# ------------------------------------------------------------------------------------------------
# 8. Méthode de normalisation déclarée par la recette (outils.magick)
# ------------------------------------------------------------------------------------------------

BOITE_K = [50, 36, 200, 150]   # w, h, x, y : 50×36 → 32×32 impose un redimensionnement (32×23, centré)
MARGE_K = 2
TAILLE_K = (32, 32)


def _version_magick() -> tuple[int, int, int] | None:
    exe = shutil.which("magick")
    if not exe:
        return None
    sortie = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=60).stdout
    trouve = re.search(r"ImageMagick (\d+)\.(\d+)\.(\d+)", sortie)
    return tuple(int(v) for v in trouve.groups()) if trouve else None


def _exiger_magick(test) -> tuple[int, int, int]:
    """Un oracle qui saute en silence ne prouve rien : en CI (variable `CI` présente), magick absent = ÉCHEC ;
    le saut n'est permis qu'en local."""
    version = _version_magick()
    if version is None:
        if "CI" in os.environ:
            test.fail("ImageMagick (`magick`) absent en CI : l'oracle L7MethodeDeclareeParLaRecette ne peut pas "
                      "prouver le contrat ; installer ImageMagick 7 sur l'exécuteur.")
        test.skipTest("ImageMagick absent (saut toléré hors CI seulement)")
    return version


def _planche_k() -> np.ndarray:
    w, h, x, y = BOITE_K
    a = np.zeros((512, 512, 4), np.int32)
    a[y:y + h, x:x + w] = _bruit(h, w, 41)
    return a


def _normaliser_magick(racine, planche_png: bytes) -> np.ndarray:
    """La chaîne EXACTE de `normaliser()` (pestouille-rpg 3f83fff, tools/assets/decouper.py), ancre centre."""
    w, h, x, y = BOITE_K
    m = MARGE_K
    W, H = TAILLE_K
    entree, sortie = racine / "planche-k.png", racine / "cadre-k.png"
    entree.write_bytes(planche_png)
    subprocess.run(["magick", str(entree), "-crop", f"{w + 2 * m}x{h + 2 * m}+{x - m}+{y - m}", "+repage",
                    "-channel", "A", "-fx", "u<0.04?0:u", "+channel", "-trim", "+repage", "-resize", f"{W}x{H}",
                    "-background", "none", "-gravity", "center", "-extent", f"{W}x{H}", f"PNG32:{sortie}"],
                   check=True, capture_output=True, timeout=120)
    with Image.open(sortie) as im:
        return np.asarray(im.convert("RGBA")).astype(np.int32)


def _aplatir(img: Image.Image) -> np.ndarray:
    fond = Image.new("RGBA", img.size, (127, 127, 127, 255))
    fond.alpha_composite(img.convert("RGBA"))
    return np.asarray(fond.convert("RGB"), dtype=np.float64) / 255


def _rmse_pillow(planche: np.ndarray, cadre: np.ndarray) -> float:
    """Normalisation Pillow LANCZOS (crop + marge, alpha < 4 % = 0, rognage, réduction, centrage) écrite ICI,
    indépendamment du registre : prouve que la fixture discrimine les deux méthodes."""
    w, h, x, y = BOITE_K
    m = MARGE_K
    W, H = TAILLE_K
    src = Image.fromarray(planche.astype(np.uint8), "RGBA").crop((x - m, y - m, x + w + m, y + h + m))
    alpha = src.getchannel("A").point([0 if i < 0.04 * 255 else i for i in range(256)])
    src.putalpha(alpha)
    src = src.crop(src.getbbox())
    f = min(W / src.width, H / src.height)
    reduit = src.resize((max(1, round(src.width * f)), max(1, round(src.height * f))), Image.Resampling.LANCZOS)
    calque = Image.new("RGBA", (W, H))
    calque.paste(reduit, ((W - reduit.width) // 2, (H - reduit.height) // 2))
    attendu = _aplatir(calque)
    obtenu = _aplatir(Image.fromarray(cadre.astype(np.uint8), "RGBA"))
    return float(np.sqrt(np.mean((attendu - obtenu) ** 2)))


def _fichiers_jeu_k(nom: str, planche_png: bytes, cadre: np.ndarray, outils: dict) -> dict:
    atlas_png, atlas_json = _atlas({"sprite-k": cadre}, "k.png")
    provenance = {"schemaVersion": 1, "outils": outils, "assets": [
        {"id": "sprite-k", "origine": "planche", "planche": "Planche_K.png", "planche_sha256": _sha(planche_png),
         "boite": BOITE_K, "marge": MARGE_K, "ancre": "centre", "taille": list(TAILLE_K),
         "transformations": ["crop", "alpha<4%=0", "trim", "resize", "extent+ancre", "atlas json-hash"]}]}
    return {
        "package.json": json.dumps({"name": nom, "private": True}) + "\n",
        "assets/source/Planche_K.png": planche_png,
        "assets/provenance.json": json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        "public/assets/atlas/k.png": atlas_png,
        "public/assets/atlas/k.json": json.dumps(atlas_json, indent=2) + "\n",
    }


class L7MethodeDeclareeParLaRecette(_Monde):
    """Mesure réelle (pestouille, 142 régions, 19/11) : le registre (Pillow LANCZOS) donne une RMSE médiane de
    0,0236 ; la commande magick de la recette du jeu donne 0,0000 (max 0,011).

    Contrat (ajout validé par le coordinateur, HL-538, 19/11) : quand provenance.json déclare
    `outils: {"magick": "<majeure>.<mineure>.<correctif>"}`, la découpe est normalisée par ImageMagick avec la
    chaîne de la recette (`-crop … +repage -channel A -fx "u<0.04?0:u" +channel -trim +repage -resize WxH
    -background none -gravity center|south -extent WxH`) ; l'evidence de la région porte `tool: "magick"` et
    `toolVersion` (version RÉELLEMENT utilisée, même majeure). Majeure déclarée ≠ majeure disponible : aucune
    mesure, limite nommée dans scan-limits (entrée du cadre qui cite magick). Sans `outils.magick` : Pillow,
    inchangé. Interprétation retenue : seule une valeur de forme `N.N.N` déclare une version ; les fixtures
    existantes portent `"magick": "fixture"`, qui ne doit RIEN changer (sinon AT-06 et L6 cassent).

    ROUGE sur 4e72ab0 : `outils` est ignoré ; Pillow mesure > 0,02 et l'evidence ne nomme aucun outil ; en cas
    de majeure différente, une RMSE est quand même rendue. Témoin (vert) : sans `outils.magick`, RMSE Pillow."""

    def setUp(self):
        super().setUp()
        self.version = _exiger_magick(self)
        planche = _planche_k()
        self.planche_png = M.png(planche)
        self.cadre = _normaliser_magick(self.world.racine, self.planche_png)
        self.rmse_pillow = _rmse_pillow(planche, self.cadre)
        self.assertGreater(self.rmse_pillow, SEUIL, "fixture : Pillow LANCZOS doit dépasser le seuil sur ce cadre")

    def _jeu(self, nom, outils):
        _ajouter_jeu(self, nom, _fichiers_jeu_k(nom, self.planche_png, self.cadre, outils))
        _scan(self)
        asset_id, _ = _sprite(self, "sprite-k")
        return asset_id, _regions(self, asset_id)

    def test_magick_declare_mesure_avec_la_recette(self):
        declaree = ".".join(map(str, self.version))
        asset_id, regions = self._jeu("jeu-k7", {"magick": declaree})
        mesures = _rmse_mesurees(regions)
        self.assertTrue(mesures and min(mesures) <= SEUIL,
                        f"normalisation par la recette déclarée (magick {declaree}) : RMSE ≤ {SEUIL} attendue, "
                        f"Pillow donne {self.rmse_pillow:.4f} : {mesures}")
        preuves = [r["evidence"] for r in regions if isinstance(r.get("evidence"), dict)]
        self.assertTrue(any(p.get("tool") == "magick" and str(p.get("toolVersion", "")).startswith(f"{self.version[0]}.")
                            for p in preuves), f"l'evidence porte l'outil et sa version réelle : {preuves}")

    def test_majeure_differente_pas_de_mesure_et_limite(self):
        declaree = f"{self.version[0] - 1}.9.0"
        asset_id, regions = self._jeu("jeu-k6", {"magick": declaree})
        self.assertFalse(_rmse_mesurees(regions), f"magick {declaree} déclaré, {self.version[0]}.x disponible : "
                                                  f"aucune RMSE : {regions}")
        limites = C.lire_json(self.reg / "generated" / "reports" / "scan-limits.json")
        entrees = [d for d in C.dicts(limites, lambda d: d.get("frame") == "sprite-k")
                   if "magick" in json.dumps(d).casefold()]
        self.assertTrue(entrees, f"limite nommée (cadre sprite-k, outil magick) dans scan-limits : "
                                 f"{C.dicts(limites, lambda d: d.get('frame') == 'sprite-k')}")

    def test_temoin_sans_outil_declare_pillow_inchange(self):
        asset_id, regions = self._jeu("jeu-k0", {})
        mesures = _rmse_mesurees(regions)
        self.assertEqual(len(mesures), 1, f"témoin : une mesure Pillow : {regions}")
        self.assertAlmostEqual(mesures[0], self.rmse_pillow, places=6,
                               msg="sans outils.magick, la normalisation Pillow reste celle d'aujourd'hui")
        self.assertFalse(any(isinstance(r.get("evidence"), dict) and r["evidence"].get("tool") == "magick"
                             for r in regions), "témoin : aucun outil magick revendiqué")


# ------------------------------------------------------------------------------------------------
# 9. Effacements : le registre masque les zones que la recette retouche
# ------------------------------------------------------------------------------------------------

BOITE_E = [48, 32, 100, 100]  # w, h, x, y ; ni marge ni taille : aucun redimensionnement


def _fichiers_jeu_e() -> dict:
    """Table `*.decoupe.json` : trois éléments déclarant des `effacements` (clonage, plume 2), coordonnées de
    PLANCHE comme dans la recette `effacer()` (pestouille-rpg 3f83fff). Le cadre est la découpe de la planche
    où la zone a été remplacée par clonage d'une zone voisine (collage franc : écart limité à la zone)."""
    w, h, x, y = BOITE_E
    planche = np.zeros((512, 512, 4), np.int32)
    planche[y - 40:y + h + 40, x - 40:x + w + 40] = _bruit(h + 80, w + 80, 53)
    planche_png = M.png(planche)

    def cloner(zone, source):
        zw, zh, zx, zy = zone
        sx, sy = source
        retouchee = planche.copy()
        retouchee[zy:zy + zh, zx:zx + zw] = planche[sy:sy + zh, sx:sx + zw]
        return retouchee[y:y + h, x:x + w]

    petite, source = [12, 10, 110, 110], [60, 60]      # ≈ 17 % de la découpe avec la plume : sous masque_max
    grande = [30, 24, 105, 104]                          # ≈ 60 % : au-delà de masque_max (0,25)
    dans_zone = cloner(petite, source)
    hors_zone = dans_zone.copy()
    hors_zone[20:30, 34:44] = (255, 255, 0, 255)         # écart HORS de toute zone déclarée
    cadres = {"sprite-e-dans-zone": dans_zone, "sprite-e-hors-zone": hors_zone,
              "sprite-e-trop-large": cloner(grande, source)}
    atlas_png, atlas_json = _atlas(cadres, "e.png")

    def effacement(zone):
        return [{"zone": zone, "source": source, "methode": "clonage", "plume": 2}]
    decoupe = {"planche": "Planche_E.png", "marge": 0, "elements": [
        {"id": "e-dans-zone", "boite": BOITE_E, "ancre": "centre", "effacements": effacement(petite)},
        {"id": "e-hors-zone", "boite": BOITE_E, "ancre": "centre", "effacements": effacement(petite)},
        {"id": "e-trop-large", "boite": BOITE_E, "ancre": "centre", "effacements": effacement(grande)}]}
    return {
        "package.json": json.dumps({"name": "jeu-e", "private": True}) + "\n",
        "assets/source/Planche_E.png": planche_png,
        "assets/source/Planche_E.elements.decoupe.json": json.dumps(decoupe, ensure_ascii=False, indent=2) + "\n",
        "public/assets/atlas/e.png": atlas_png,
        "public/assets/atlas/e.json": json.dumps(atlas_json, indent=2) + "\n",
    }


class L7EffacementsMemeMasqueQueLaRecette(_Monde):
    """Aucun test ne couvrait les `effacements` de decoupe.json (grep sur tests/, 19/11). La recette du jeu
    (`effacer()`) retouche la planche par clonage dans les zones déclarées ; le registre masque ces zones
    (`_masked_edits` : plume, `masque_max`).

    Contrat : un cadre qui ne diffère de la planche QUE dans les zones déclarées (plume comprise) se vérifie
    sous 0,02 ; un cadre qui diffère AUSSI hors des zones reste au-dessus ; des zones couvrant plus que
    `masque_max` (0,25 par défaut) ne donnent pas de mesure. Tests de GARDE : attendus verts sur 4e72ab0."""

    def setUp(self):
        super().setUp()
        _ajouter_jeu(self, "jeu-e", _fichiers_jeu_e())
        _scan(self)

    def _mesures(self, cadre):
        asset_id, _ = _sprite(self, cadre)
        return _rmse_mesurees(_regions(self, asset_id))

    def test_ecart_dans_les_zones_seulement_verifie(self):
        mesures = self._mesures("sprite-e-dans-zone")
        self.assertTrue(mesures and min(mesures) <= SEUIL, f"zones déclarées masquées : vérifié : {mesures}")

    def test_ecart_hors_des_zones_au_dessus(self):
        mesures = self._mesures("sprite-e-hors-zone")
        self.assertTrue(mesures, "fixture : la région est mesurée")
        self.assertFalse([m for m in mesures if m <= SEUIL], f"écart hors zone : au-dessus du seuil : {mesures}")

    def test_zones_au_dela_de_masque_max_pas_de_mesure(self):
        self.assertFalse(self._mesures("sprite-e-trop-large"),
                         "zones couvrant plus que masque_max : aucune mesure")


if __name__ == "__main__":
    unittest.main()
