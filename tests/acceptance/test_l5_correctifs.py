"""L5 — Correctifs de la relecture adverse de `d872f32` (HL-538).

Source : `.codex-logs/run-rev1-last.md` (relecture adverse des lots L1 à L4), spec v1.0 § 5 (relations et
lock), § 9 (droits par ressource), § 12 règle 5 « Ne jamais écraser un asset publié ». Chaque contrat est
une DÉCISION de l'orchestrateur (HL-538, 19/11) ; oracles écrits AVANT le code par Claude, ROUGES sur
`34a1455` pour la raison décrite dans chaque docstring, sauf `M4DoublonsHorsGit` (vert aujourd'hui,
rouge sous la mutation M4 de la relecture).

Boîte noire : CLI `assetctl … --json`, codes de retour de docs/ARCHITECTURE.md (0 succès, 1 contrôle,
2 usage, 3 refus, 4 source indisponible, 5 conflit), catalogue `catalog/assets/*.json`. Seul l'oracle
M4 importe `canonical_png` pour fabriquer des octets identiques à ceux d'une dérivation identité.
Fixtures synthétiques seulement : aucun dépôt réel, aucun réseau.
"""

import hashlib
import io
import json
import shutil
import unittest

import numpy as np
from PIL import Image

from tests.acceptance import _contrat as C
from tests.acceptance import _monde as M

NOUVEAU = M.png(M.uni(16, 12, (33, 121, 213, 255)))
AUTRE = M.png(M.uni(16, 12, (240, 160, 20, 255)))
PREUVE = ["LICENSE de fixture (oracle L5)"]
EXPORT_IDENTITE = '{"mirror": false}\n'


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _actif(loc: dict) -> bool:
    return loc.get("status", "active") != "removed" and not loc.get("releaseOnly")


def _assets_actifs(registre, depot: str, chemin: str) -> list[tuple[str, dict]]:
    """Assets portant un emplacement ACTIF (ni retiré, ni release seule) à `depot:chemin`."""
    return [(i, a) for i, a in C.assets(registre).items()
            if any(_actif(loc) and loc.get("path") == chemin and loc.get("repo") == depot
                   for loc in a["files"]["locations"])]


def _un_actif(test, registre, depot, chemin):
    trouves = _assets_actifs(registre, depot, chemin)
    test.assertEqual(len(trouves), 1, f"un seul asset actif attendu pour {depot}:{chemin} : "
                                      f"{[i for i, _ in trouves]}")
    return trouves[0]


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


def _ctl(test, world, args, code=C.OK):
    r = world.ctl(args)
    test.assertEqual(r.code, code, f"code {code} attendu\n{r}")
    return r.json


def _scan(test, *extra):
    r = test.world.scan(*extra)
    test.assertEqual(r.code, C.OK, f"fixture : scan-repos en échec\n{r}")
    return r


class _Monde(unittest.TestCase):
    """Un monde neuf par test : chaque scénario part de zéro."""

    def setUp(self):
        self.world = M.creer_monde()
        self.addCleanup(self.world.nettoyer)
        self.reg = self.world.registre
        self.jeu = self.world.depot("jeu-a")
        self.orig = (self.jeu / M.FOUET).read_bytes()

    def remplacer(self, contenu=NOUVEAU, date="2026-03-06T10:00:00+00:00", chemin=M.FOUET):
        return M.ajouter_commit(self.world, "jeu-a", {chemin: contenu}, (), date, "Nouveau contenu")


# ------------------------------------------------------------------------------------------------
# 1. BLOQUANT — check-lock contrôle la version VERROUILLÉE
# ------------------------------------------------------------------------------------------------

class L5CheckLockVersionVerrouillee(_Monde):
    """Constat bloquant : « Le lock public contrôle les droits d'une autre version. `check-lock` applique
    d'abord la garde à la fiche courante, puis cherche le couple numéro–SHA dans l'historique. […] Dans le
    sens inverse, une ancienne version autorisée est refusée si la courante est `unknown`. Le contrôle ignore
    aussi `registryCommit` et ne vérifie pas les octets du jeu. » (delivery.py:258, licenses.py:73)

    Contrat : la garde publique s'applique à la révision verrouillée (licence + preuve de CETTE version,
    `versions[n-1].publication` pour une version historique) ; `registryCommit` doit exister dans le dépôt
    du registre et y contenir le couple `assetId`/`assetVersion` ; le fichier `path` (relatif au dossier du
    lock) doit avoir le sha256 de la ligne."""

    def _v1_puis_v2(self):
        _scan(self)
        asset_id, v1 = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        apres_v1 = self.world.commiter_registre("Catalogue : fouet v1")
        return asset_id, v1, apres_v1

    def _lock_avec_fichier(self, nom, commit, asset_id, version, sha, octets):
        dossier = self.world.racine / nom
        (dossier / "assets").mkdir(parents=True, exist_ok=True)
        (dossier / "assets" / "fouet.png").write_bytes(octets)
        return _ecrire_lock(dossier, commit, [_ligne(asset_id, version, sha)])

    def test_a_public_refuse_une_version_historique_sans_licence_prouvee(self):
        asset_id, v1, _ = self._v1_puis_v2()
        self.remplacer()
        _scan(self)
        # La version COURANTE (2) reçoit une licence admissible avec preuve ; la 1 n'en a jamais eu.
        courant = _modifier_fiche(self.reg, asset_id, license="MIT", licenseEvidence=PREUVE)
        self.assertEqual((courant["version"], courant["sha256"]), (2, _sha(NOUVEAU)), "fixture : v2 courante")
        self.assertFalse(any("publication" in e for e in courant["versions"][:1]), "fixture : v1 sans preuve")
        commit = self.world.commiter_registre("Catalogue : licence MIT sur la v2 seule")
        lock = self._lock_avec_fichier("jeu-a1", commit, asset_id, 1, v1["sha256"], self.orig)
        r = self.world.ctl(C.cmd_check_lock(lock, "--public"))
        self.assertEqual(r.code, C.REFUS, "la v1 verrouillée n'a ni licence ni preuve : --public doit "
                                          f"refuser (3), même si la v2 courante est MIT prouvée\n{r}")

    def test_b_public_accepte_une_version_historique_prouvee_malgre_courante_unknown(self):
        _scan(self)
        asset_id, v1 = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        _modifier_fiche(self.reg, asset_id, status="published", license="CC0-1.0", licenseEvidence=PREUVE)
        self.world.commiter_registre("Catalogue : v1 publiée sous CC0")
        self.remplacer()
        _scan(self)
        courant = C.assets(self.reg)[asset_id]
        self.assertEqual((courant["version"], courant["license"]), (2, "unknown"), "fixture : v2 unknown")
        self.assertEqual(courant["versions"][0].get("publication", {}).get("license"), "CC0-1.0",
                         "fixture : la preuve de la v1 est archivée dans versions[0].publication")
        commit = self.world.commiter_registre("Catalogue : v2 sans licence")
        lock = self._lock_avec_fichier("jeu-a1", commit, asset_id, 1, v1["sha256"], self.orig)
        r = self.world.ctl(C.cmd_check_lock(lock, "--public"))
        self.assertEqual(r.code, C.OK, "la v1 verrouillée porte CC0 + preuve : --public doit accepter (0), "
                                       f"la v2 courante `unknown` n'est pas celle livrée\n{r}")
        self.assertIn("non-current-version", {w.get("warning") for w in (r.json or {}).get("warnings", [])}, str(r))

    def test_c_registry_commit_absent_ou_sans_le_couple_echoue(self):
        asset_id, _, apres_v1 = self._v1_puis_v2()
        self.remplacer()
        _scan(self)
        apres_v2 = self.world.commiter_registre("Catalogue : fouet v2")
        v2 = _sha(NOUVEAU)
        # Contrôle : le couple v2 dans un commit qui le contient passe.
        lock = self._lock_avec_fichier("jeu-ok", apres_v2, asset_id, 2, v2, NOUVEAU)
        _ctl(self, self.world, C.cmd_check_lock(lock))
        cas = {"registryCommit absent du dépôt du registre": "f" * 40,
               "commit où assetId/assetVersion 2 n'existe pas encore": apres_v1}
        for motif, commit in cas.items():
            with self.subTest(motif):
                lock = self._lock_avec_fichier("jeu-c", commit, asset_id, 2, v2, NOUVEAU)
                r = self.world.ctl(C.cmd_check_lock(lock))
                self.assertEqual(r.code, C.ECHEC, f"{motif} : code 1 attendu\n{r}")

    def test_d_octets_du_fichier_verrouille(self):
        asset_id, v1, commit = self._v1_puis_v2()
        lock = self._lock_avec_fichier("jeu-d", commit, asset_id, 1, v1["sha256"], self.orig)
        _ctl(self, self.world, C.cmd_check_lock(lock))  # fichier conforme : 0
        (lock.parent / "assets" / "fouet.png").write_bytes(NOUVEAU)
        r = self.world.ctl(C.cmd_check_lock(lock))
        self.assertEqual(r.code, C.ECHEC, "le fichier `path` du jeu n'a plus le sha256 verrouillé : "
                                          f"code 1 attendu\n{r}")


# ------------------------------------------------------------------------------------------------
# 2. Une version publiée reste livrable
# ------------------------------------------------------------------------------------------------

class L5VersionPublieeLivrable(_Monde):
    """Constat majeur : « Une version publiée peut rester dans le catalogue sans rester livrable. […] Pour
    un asset publié depuis un miroir, le registre ne conserve pas nécessairement de copie des octets. Les
    commandes de livraison sélectionnent la version courante et n'exploitent pas le chemin archivé. »
    (asset_versions.py:21, importer.py:320, delivery.py:191)

    Contrat : `publish` fait conserver au registre les binaires des versions publiées, adressés par sha256 ;
    `materialize <id> --version <n> --to <dossier>` rend les octets exacts de la version n (sha256 vérifié),
    code 0, même après suppression du cache des miroirs et arrivée d'une version courante plus récente."""

    def test_materialize_version_publiee_apres_purge_des_miroirs(self):
        _scan(self)
        asset_id, v1 = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        _modifier_fiche(self.reg, asset_id, license="MIT", licenseEvidence=PREUVE)
        self.world.commiter_registre("Catalogue : fouet MIT")
        export = self.world.racine / "export-public"
        _ctl(self, self.world, C.cmd_publish([asset_id], "public", export))
        self.world.commiter_registre("Registre après publication")
        self.remplacer()
        _scan(self)
        self.assertEqual(C.assets(self.reg)[asset_id]["version"], 2, "fixture : v2 courante")
        shutil.rmtree(self.world.cache)  # l'ancien objet a disparu du miroir
        dest = self.world.racine / "livraison" / "fouet-v1.png"
        r = self.world.ctl(["materialize", asset_id, "--version", "1", "--to", str(dest), "--private-target",
                            "--json"])
        self.assertEqual(r.code, C.OK, "la v1 publiée doit rester livrable sans miroir (binaire conservé "
                                       f"par sha256 dans le registre)\n{r}")
        self.assertEqual(C.sha256_fichier(dest), v1["sha256"])


# ------------------------------------------------------------------------------------------------
# 3. Un tag tardif à tête constante est pris par sync
# ------------------------------------------------------------------------------------------------

class L5SyncTagsATeteConstante(_Monde):
    """Constat majeur : « Un tag tardif échappe à `sync` lorsque la tête reste stable. Avec fetch,
    l'égalité du couple commit–branche court-circuite la lecture des tags. […] La sonde du premier chemin a
    renvoyé 0, `scannedCopies: 0`. » (scan.py:171)

    Contrat : la carte des tags fait partie de l'état comparé ; ajout, déplacement et retrait d'un tag à
    tête constante sont lus par `sync` (`scannedCopies` ≥ 1) et le catalogue de la branche de sync porte la
    version du tag."""

    BRANCHE = "sync/l5-tags"

    def _base(self):
        _scan(self)
        self.world.commiter_registre("Catalogue initial")

    def _sync(self):
        return _ctl(self, self.world, C.cmd_sync(self.BRANCHE))

    def _fiche_sur_branche(self, asset_id):
        brut = self.world.git(self.reg, "show", f"{self.BRANCHE}:{C.DOSSIER_ASSETS}/{asset_id}.json")
        return json.loads(brut)

    def _refs_sur_branche(self):
        brut = self.world.git(self.reg, "show", f"{self.BRANCHE}:catalog/scan-references.json")
        return next(r for r in json.loads(brut)["references"] if r["name"] == "jeu-a")

    def test_ajout_d_un_tag_sur_un_commit_ancien(self):
        ancien = self.world.commits["jeu-a"]
        self.world.git(self.jeu, "tag", "-d", "v1.0")
        self.remplacer()
        self._base()
        asset_id, _ = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        self._sync()
        self.world.git(self.jeu, "tag", "v1.0", ancien)  # tête inchangée
        second = self._sync()
        self.assertGreaterEqual(second["scannedCopies"], 1, f"tag ajouté à tête constante ignoré : {second}")
        fiche = self._fiche_sur_branche(asset_id)
        self.assertIn(_sha(self.orig), [v["sha256"] for v in fiche["versions"]],
                      "la version du tag v1.0 doit entrer au catalogue de la branche de sync")

    def test_deplacement_d_un_tag(self):
        intermediaire = self.remplacer(AUTRE, "2026-03-05T10:00:00+00:00")
        self.remplacer()
        self._base()  # v1.0 sur le premier commit
        asset_id, _ = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        self.assertNotIn(_sha(AUTRE), [v["sha256"] for v in C.assets(self.reg)[asset_id]["versions"]],
                         "fixture : le commit intermédiaire n'est pas encore une version")
        self._sync()
        self.world.git(self.jeu, "tag", "-f", "v1.0", intermediaire)  # tête inchangée
        second = self._sync()
        self.assertGreaterEqual(second["scannedCopies"], 1, f"tag déplacé à tête constante ignoré : {second}")
        fiche = self._fiche_sur_branche(asset_id)
        self.assertIn(_sha(AUTRE), [v["sha256"] for v in fiche["versions"]],
                      "la version du tag déplacé doit entrer au catalogue de la branche de sync")

    def test_retrait_d_un_tag(self):
        ancien = self.world.commits["jeu-a"]
        self.remplacer()
        self._base()
        asset_id, _ = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        self._sync()
        self.world.git(self.jeu, "tag", "-d", "v1.0")  # tête inchangée
        second = self._sync()
        self.assertGreaterEqual(second["scannedCopies"], 1, f"tag retiré à tête constante ignoré : {second}")
        self.assertNotIn(ancien, self._refs_sur_branche()["releaseCommits"],
                         "le tag retiré ne doit plus figurer dans les commits de release de référence")
        self.assertIn(_sha(self.orig), [v["sha256"] for v in self._fiche_sur_branche(asset_id)["versions"]],
                      "aucune version n'est effacée par le retrait d'un tag")


# ------------------------------------------------------------------------------------------------
# 4. Identité d'un sprite d'atlas
# ------------------------------------------------------------------------------------------------

def _atlas_retouche(y: int, x: int) -> bytes:
    brut, _ = M.atlas_elements()
    with Image.open(io.BytesIO(brut)) as image:
        pixels = np.asarray(image.convert("RGBA")).astype(np.int32).copy()
    pixels[y, x] = (255 - pixels[y, x, 0], 17, 211, 255)
    return M.png(pixels)


class L5IdentiteSpriteAtlas(_Monde):
    """Constat majeur : « Si une source modifie ensuite la planche au même chemin, le SHA de planche change,
    la clé de région change et le sprite obtient un autre ID à la version 1. L'identité du sprite suit ainsi
    le SHA de la planche. » (sheets.py:20, sheets.py:183, importer.py:414)

    Contrat : identité d'un sprite d'atlas = source logique + chemin logique de l'atlas + nom de frame ;
    SHA de planche et coordonnées sont des preuves par révision."""

    CADRE = C.PREFIXE_CADRE + "etoile"   # frame x=2..41, y=2..25 dans elements.png (128×32)

    def _etoiles(self):
        return {i: a for i, a in C.assets(self.reg).items()
                if isinstance(a.get("family"), dict)
                and a["family"].get("sprite", {}).get("frameName") == self.CADRE}

    def _avant(self):
        _scan(self)
        etoiles = self._etoiles()
        self.assertEqual(len(etoiles), 1, f"fixture : un sprite {self.CADRE} attendu : {list(etoiles)}")
        return next(iter(etoiles.items()))

    def test_retouche_hors_region_garde_id_et_version(self):
        sprite_id, avant = self._avant()
        self.remplacer(_atlas_retouche(30, 120), chemin=M.ATLAS_ELEMENTS_PNG)  # hors de tout cadre
        _scan(self)
        etoiles = self._etoiles()
        self.assertEqual(list(etoiles), [sprite_id], "retoucher l'atlas hors de la région ne doit pas "
                                                    "créer un autre ID de sprite")
        self.assertEqual((etoiles[sprite_id].get("version", 1), etoiles[sprite_id]["sha256"]),
                         (avant.get("version", 1), avant["sha256"]))

    def test_retouche_dans_la_region_meme_id_version_2(self):
        sprite_id, avant = self._avant()
        self.remplacer(_atlas_retouche(10, 10), chemin=M.ATLAS_ELEMENTS_PNG)  # dans le cadre de l'étoile
        _scan(self)
        etoiles = self._etoiles()
        self.assertEqual(list(etoiles), [sprite_id], "retoucher la région du sprite garde son ID")
        fiche = etoiles[sprite_id]
        self.assertEqual(fiche.get("version"), 2, "pixels de la région modifiés : version 2")
        self.assertNotEqual(fiche["sha256"], avant["sha256"])
        self.assertEqual([v["sha256"] for v in fiche["versions"]][0], avant["sha256"])


# ------------------------------------------------------------------------------------------------
# 5. Un même tag pointe des commits différents selon le fournisseur
# ------------------------------------------------------------------------------------------------

def _sources(world, mutate):
    document = C.lire_json(world.registre / C.SOURCES)
    mutate(document)
    (world.registre / C.SOURCES).write_text(json.dumps(document), encoding="utf-8")


def _miroir(world, provider, url):
    """Copie « distante » simulée (reprise de tests/unit/test_branche_defaut.py)."""
    mirror = world.cache / provider / "jeu-a.git"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    world.git(world.depot("jeu-a"), "clone", "--mirror", "--no-local", ".", str(mirror))
    world.git(mirror, "remote", "set-url", "origin", url)
    return mirror


def _miroir_local(world):
    mirror = world.cache / "local" / "jeu-a.git"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    world.git(world.depot("jeu-a"), "clone", "--mirror", "--no-local", world.depot("jeu-a").as_uri(), str(mirror))


def _avec_copies_distantes(world):
    _miroir(world, "github", "https://github.com/fixture/jeu-a")
    _miroir(world, "forgejo", "https://forgejo.pingfr.duckdns.org/fixture/jeu-a")

    def mutate(document):
        source = next(e for e in document["sources"] if e["name"] == "jeu-a")
        source["copies"].extend([
            {"provider": "github", "url": "https://github.com/fixture/jeu-a", "visibility": "public"},
            {"provider": "forgejo", "url": "https://forgejo.pingfr.duckdns.org/fixture/jeu-a",
             "visibility": "private"}])
        for entry in document["sources"]:
            for copy in entry["copies"]:
                copy["defaultBranch"] = "main"
    _sources(world, mutate)


class L5TagDivergentEntreFournisseurs(_Monde):
    """Constat majeur : « Si GitHub et Forgejo partagent la même tête mais que `v1` pointe vers deux commits
    aux contenus différents, `_divergences` accepte les deux copies. La boucle d'import lit ensuite les deux
    commits de release et peut les rattacher à la même lignée. » (scan.py:102, scan.py:195, importer.py:271)

    Contrat : une seule version par contenu de la source pour un même nom de tag ; la divergence est
    signalée par nom de tag (`divergentSources` du résultat, ou `divergentTags` du rapport de migration)."""

    def test_v1_divergent_une_seule_version_et_signalement_par_tag(self):
        ancien = self.world.commits["jeu-a"]
        self.world.git(self.jeu, "checkout", "-q", "-b", "fourche-release", ancien)
        fourche = self.remplacer(AUTRE, "2026-03-04T10:00:00+00:00")
        self.world.git(self.jeu, "checkout", "-q", "main")
        self.world.git(self.jeu, "branch", "-q", "-D", "fourche-release")
        self.remplacer()  # tête commune aux trois copies
        _avec_copies_distantes(self.world)
        _miroir_local(self.world)
        # Sur GitHub seulement, v1.0 pointe la fourche (contenu AUTRE) ; ailleurs, le premier commit.
        github = self.world.cache / "github" / "jeu-a.git"
        self.world.git(github, "fetch", "-q", str(self.jeu), f"+{fourche}:refs/tags/v1.0")
        self.assertEqual(self.world.git(github, "rev-parse", "v1.0^{commit}"), fourche, "fixture")
        r = _scan(self, "--no-fetch", "--only", "jeu-a")
        _, fiche = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        contenus = [v["sha256"] for v in fiche["versions"]]
        self.assertEqual(len(contenus), 2, "tête + UNE version pour le tag v1.0, jamais une par fournisseur : "
                                           f"{contenus}")
        self.assertFalse({_sha(self.orig), _sha(AUTRE)} <= set(contenus),
                         "les deux contenus de v1.0 ne doivent pas entrer tous deux dans la lignée")
        migration = C.lire_json(C.rapport(self.reg, "migration"))
        signalements = [*(r.json or {}).get("divergentSources", []),
                        *(t for d in C.dicts(migration, lambda d: "divergentTags" in d) for t in d["divergentTags"])]
        self.assertTrue(C.contient_texte(signalements, "v1.0"),
                        f"la divergence doit être signalée par nom de tag (v1.0) : {signalements}")


# ------------------------------------------------------------------------------------------------
# 6. Alias exact, puis divergent
# ------------------------------------------------------------------------------------------------

class L5AliasPuisDivergent(_Monde):
    """Constat majeur : « Deux chemins identiques deviennent une fiche unique, comportement exigé par T13.
    Si les chemins évoluent ensuite vers deux contenus différents en restant tous deux actifs, chaque chemin
    retrouve la même lignée et peut promouvoir son contenu. » (importer.py:251, importer.py:303)

    Contrat : après divergence, l'asset initial garde comme courant le contenu de A ; B ouvre sa propre
    lignée (autre ID) ; les usages de A restent sur l'ID initial."""

    ALIAS = "public/assets/fouet-alias.png"

    def test_alias_divergent_ouvre_sa_propre_lignee(self):
        M.ajouter_commit(self.world, "jeu-a", {self.ALIAS: self.orig}, (), "2026-03-04T10:00:00+00:00",
                         "Alias exact du fouet")
        _scan(self)
        initial, fiche_a = _un_actif(self, self.reg, "jeu-a", M.FOUET)
        self.assertEqual(_un_actif(self, self.reg, "jeu-a", self.ALIAS)[0], initial,
                         "fixture (T13) : un même contenu à deux chemins = un seul asset")
        tete = self.remplacer(chemin=self.ALIAS)  # B change, A reste
        _scan(self)
        id_a, a = _un_actif(self, self.reg, "jeu-a", M.FOUET)
        self.assertEqual(id_a, initial, "A garde l'ID initial")
        self.assertEqual(a["sha256"], _sha(self.orig), "le courant de l'asset initial reste le contenu de A")
        self.assertEqual(a.get("version", 1), fiche_a.get("version", 1), "A n'a pas changé : pas de version")
        id_b, b = _un_actif(self, self.reg, "jeu-a", self.ALIAS)
        self.assertNotEqual(id_b, initial, "B divergent ouvre sa propre lignée")
        self.assertEqual(b["sha256"], _sha(NOUVEAU))
        usages_a = [u for u in a["usages"] if u.get("commit") == tete and u.get("status", "active") != "removed"]
        self.assertTrue(usages_a, f"les usages de A restent sur l'ID initial : {a['usages']}")
        self.assertFalse(any(u.get("commit") == tete and u.get("status", "active") != "removed"
                             for u in b["usages"]), f"aucun usage de A ne migre vers B : {b['usages']}")


# ------------------------------------------------------------------------------------------------
# 7. Un dérivé est versionné selon la révision de son parent
# ------------------------------------------------------------------------------------------------

class L5DeriveSelonRevisionParent(_Monde):
    """Constat majeur : « Une recette de dérivation réutilise le résultat d'une ancienne révision du parent.
    La clé contient l'ID du parent et le SHA de la recette. Après évolution du parent, la même commande rend
    le dérivé existant avant de lire les octets du parent courant. Sa provenance indique le parent sans
    version ni SHA. » (creation.py:183)

    Contrat : la même dérivation relancée sur un parent en v2 reflète la v2 (nouvelle version du dérivé ou
    nouveau dérivé, jamais l'ancien résultat rendu tel quel) ; la provenance porte `parentId`,
    `parentVersion` et `parentSha256`."""

    def test_meme_recette_parent_v2(self):
        _scan(self)
        parent_id, v1 = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        recette = self.world.racine / "recette-l5.json"
        recette.write_text('{"mirror": true}\n', encoding="utf-8")
        args = ["derive", parent_id, "--recipe", str(recette), "--json"]
        premier = _ctl(self, self.world, args)["asset"]
        self.remplacer()
        _scan(self)
        parent = C.assets(self.reg)[parent_id]
        self.assertEqual(parent["version"], 2, "fixture : parent en v2")
        second = _ctl(self, self.world, args)["asset"]
        self.assertNotEqual(second["sha256"], premier["sha256"],
                            "la dérivation relancée sur le parent v2 a rendu l'ancien résultat tel quel")
        for fiche, version, sha in ((premier, 1, v1["sha256"]), (second, 2, parent["sha256"])):
            provenance = fiche["provenance"]
            self.assertEqual((provenance.get("parentId"), provenance.get("parentVersion"),
                              provenance.get("parentSha256")), (parent_id, version, sha),
                             f"provenance du dérivé sans révision du parent : {provenance}")


# ------------------------------------------------------------------------------------------------
# 8. L'ordre des versions suit l'ascendance Git
# ------------------------------------------------------------------------------------------------

class L5OrdreCausal(_Monde):
    """Verdict de la relecture : « Acceptable comme identifiant immuable, trompeur comme ordre historique.
    […] Les liens `previousVersion` et `nextVersion` permettent la lecture dans les deux sens, dans l'ordre
    des numéros. Pour un tag découvert tardivement, cet ordre peut différer de l'ascendance Git. »
    (asset_versions.py:31, importer.py:438)

    Contrat : numéros immuables, pointeur courant `version`, et sur chaque entrée de `versions`
    `causalPrevious`/`causalNext` (numéros) déduits de l'ascendance Git ; pour des commits incomparables,
    `null` et `causalOrder: "incomparable"`."""

    def test_tag_tardif_precede_causalement_la_version_courante(self):
        ancien = self.world.commits["jeu-a"]
        self.world.git(self.jeu, "tag", "-d", "v1.0")
        self.remplacer()
        _scan(self)
        asset_id, premiere = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        self.world.git(self.jeu, "tag", "v1.0", ancien)
        _scan(self)
        fiche = C.assets(self.reg)[asset_id]
        self.assertEqual((fiche["version"], fiche["sha256"]), (1, premiere["sha256"]), "numéros immuables")
        par_numero = {v["version"]: v for v in fiche["versions"]}
        self.assertEqual(par_numero[2]["commit"], ancien, "fixture : la version du tag tardif est la 2")
        self.assertEqual((par_numero[1].get("causalPrevious", "absent"), par_numero[1].get("causalNext", "absent")),
                         (2, None), "la version du tag (2) est le prédécesseur causal de la courante (1)")
        self.assertEqual((par_numero[2].get("causalPrevious", "absent"), par_numero[2].get("causalNext", "absent")),
                         (None, 1))

    def test_commits_incomparables(self):
        ancien = self.world.commits["jeu-a"]
        self.world.git(self.jeu, "tag", "-d", "v1.0")
        self.world.git(self.jeu, "checkout", "-q", "-b", "cote", ancien)
        cote = self.remplacer(AUTRE, "2026-03-04T10:00:00+00:00")
        self.world.git(self.jeu, "tag", "v-cote", cote)
        self.world.git(self.jeu, "checkout", "-q", "main")
        self.world.git(self.jeu, "branch", "-q", "-D", "cote")
        self.remplacer()  # main : ni ancêtre ni descendant de `cote`
        _scan(self)
        _, fiche = C.asset_par_chemin(self.reg, "jeu-a", M.FOUET)
        entree = next((v for v in fiche["versions"] if v["sha256"] == _sha(AUTRE)), None)
        self.assertIsNotNone(entree, f"fixture : la version du tag v-cote est importée : {fiche['versions']}")
        self.assertEqual((entree.get("causalPrevious", "absent"), entree.get("causalNext", "absent"),
                          entree.get("causalOrder")), (None, None, "incomparable"),
                         f"commits incomparables : liens causaux nuls et causalOrder « incomparable » : {entree}")


# ------------------------------------------------------------------------------------------------
# 9. pHash des aplats
# ------------------------------------------------------------------------------------------------

class L5PhashAplats(_Monde):
    """Constat mineur : « Deux images visuellement différentes peuvent avoir pHash et dHash identiques. La
    sonde sur deux aplats opaques rouge et bleu de 16 × 16 donne les deux mêmes empreintes et deux distances
    de zéro. Le rapport rend une candidature `needs-review`. » (dedup.py:21, dedup.py:42)

    Contrat : deux aplats opaques 16×16 rouge et bleu ne sortent PAS en paire `similar` de
    `generated/duplicates.json`."""

    ROUGE = "public/assets/aplat-rouge.png"
    BLEU = "public/assets/aplat-bleu.png"

    def test_aplats_rouge_et_bleu_non_similaires(self):
        M.ajouter_commit(self.world, "jeu-a", {self.ROUGE: M.png(M.uni(16, 16, (220, 20, 20, 255))),
                                               self.BLEU: M.png(M.uni(16, 16, (20, 20, 220, 255)))},
                         (), "2026-03-04T10:00:00+00:00", "Deux aplats")
        _scan(self)
        rouge, _ = C.asset_par_chemin(self.reg, "jeu-a", self.ROUGE)
        bleu, _ = C.asset_par_chemin(self.reg, "jeu-a", self.BLEU)
        _ctl(self, self.world, ["duplicates", "--json"])
        paires = C.lire_json(self.reg / "generated" / "duplicates.json")["similar"]
        self.assertNotIn({rouge, bleu}, [{p["a"], p["b"]} for p in paires],
                         "un aplat rouge et un aplat bleu ne sont pas visuellement similaires")


# ------------------------------------------------------------------------------------------------
# 10. Mutation M4 : doublon exact hors Git
# ------------------------------------------------------------------------------------------------

class M4DoublonsHorsGit(_Monde):
    """Mutation recommandée par la relecture : « dedup.py:75 — supprimer `or len(identities[sha]) > 1` du
    filtre exact. Test à ajouter avec deux fiches issues de `register` et `derive`, de même SHA et sans
    emplacement Git. Le rapport doit contenir un groupe exact avec les deux IDs. »

    VERT sur `34a1455` ; ROUGE si la mutation est appliquée."""

    def test_register_et_derive_identite_groupe_exact(self):
        from tools.extract.commands import _image
        from tools.extract.regions import canonical_png

        brut = canonical_png(_image(M.png(M.damier(12, 10, (200, 40, 40, 255), (40, 40, 200, 255)))))
        fichier = self.world.racine / "aplat-manuel.png"
        fichier.write_bytes(brut)
        recu = self.world.racine / "recu-m4.json"
        trouves = _ctl(self, self.world, ["search", "damier manuel", "--receipt", str(recu), "--json"])["results"]
        rejets = [a for r in trouves for a in ("--reject", f"{r['id']}:fixture M4")]
        parent = _ctl(self, self.world, C.cmd_register(fichier, "Damier manuel", "kitchen", "--receipt", str(recu),
                                                       *rejets))["id"]
        recette = self.world.racine / "recette-identite.json"
        recette.write_text(EXPORT_IDENTITE, encoding="utf-8")
        enfant = _ctl(self, self.world, ["derive", parent, "--recipe", str(recette), "--json"])["asset"]
        fiches = C.assets(self.reg)
        self.assertEqual(enfant["sha256"], fiches[parent]["sha256"], "fixture : dérivation identité, même SHA")
        self.assertNotEqual(enfant["id"], parent)
        for i in (parent, enfant["id"]):
            self.assertEqual(fiches[i]["files"]["locations"], [], f"fixture : {i} sans emplacement Git")
        rapport = _ctl(self, self.world, ["duplicates", "--json"])
        groupes = [g for g in rapport["exact"] if g["sha256"] == _sha(brut)]
        self.assertEqual(len(groupes), 1, f"un groupe exact attendu pour le SHA partagé : {rapport['exact']}")
        self.assertEqual(set(groupes[0]["ids"]), {parent, enfant["id"]})
        self.assertEqual(C.lire_json(self.reg / "generated" / "duplicates.json")["exact"], rapport["exact"])


if __name__ == "__main__":
    unittest.main()
