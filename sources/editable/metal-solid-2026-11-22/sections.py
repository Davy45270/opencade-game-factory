"""Sections des 14 planches « Metal Solid » (Drive Homelab/assets/Metal Solid, 2026-11-22), lues sur les planches 1536x1024.

Une section : (animation, libellé lu sur la planche, nombre de cadres ou None, rectangle x0, y0, x1, y1, exclusions).
- Le rectangle couvre la rangée de cadres ; le titre de section et les numéros sous les cadres qui y tombent sont retirés
  par decoupe_ms.py (lignes de texte clair, peu saturé, de moins de 28 px de haut).
- None : décor ; les éléments sont séparés par découpe XY (bandes vides), sans nombre attendu.
- exclusions : rectangles remis au fond avant la découpe (titre qui chevauche un cadre, nuancier, flèches).
MARQUES : zones remises au fond dans la planche importée (bandeau de style en haut à droite, et logo de la planche 01),
parce qu'elles portent une marque commerciale tierce que le registre ne reprend pas.
"""

def perso(px, nuancier, sep):
    """Gabarit commun aux trois joueurs (01-03) ; sep = abscisses des séparateurs lues sur chaque planche."""
    s = sep
    return [
        ("portrait", "portrait", 1, (0, 130, px, 492), [nuancier]),
        ("idle", "Idle (repos, en boucle)", 4, (s["idle"][0], 130, s["idle"][1] - 6, 272), []),
        ("marche", "Marche", 6, (s["idle"][1] + 6, 130, 1532, 272), []),
        ("course", "Course", 5, (s["course"][0], 318, s["course"][1] - 6, 470), []),
        ("saut", "Saut", 5, (s["course"][1] + 6, 288, 1532, 470), [(s["course"][1] + 6, 284, s["course"][1] + 80, 322)]),
        ("tir-sol", "Tir (au sol)", 4, (16, 536, s["tir"] - 6, 664), []),
        ("tir-air", "Tir (en l'air)", 4, (s["tir"] + 6, 504, 1532, 664), [(s["tir"] + 6, 500, s["tir"] + 150, 534)]),
        ("accroupi", "Accroupi / Tir accroupi", 4, (16, 712, s["objet"][0] - 6, 842), []),
        ("objet", "Prendre un objet", 4, (s["objet"][0] + 6, 684, s["objet"][1] - 6, 842), [(s["objet"][0] + 6, 678, s["objet"][0] + 190, 709)]),
        ("degats", "Dégâts", 3, (s["objet"][1] + 6, 698, 1532, 842), [(s["objet"][1] + 6, 680, s["objet"][1] + 110, 710)]),
        ("ko", "K.O. / Mort", 5, (16, 884, s["ko"] - 6, 1016), []),
        ("relever", "Se relever (optionnel)", 4, (s["ko"] + 6, 884, 1532, 1016), []),
    ]


def vehicule(px, nuancier, sep, y):
    """Gabarit commun au tank (04, 06) et à l'hélicoptère (07) : y = (haut rangée 1, sep 1, sep 2, sep 3, sep 4)."""
    s = sep
    return [
        ("portrait", "portrait", 1, (0, y[0] + 15, px, y[2] - 8), [nuancier]),
        (s["n"][0], s["t"][0], 4, (s["a"][0], y[0], s["a"][1] - 6, y[1] - 4), []),
        (s["n"][1], s["t"][1], 4, (s["a"][1] + 6, y[0], 1532, y[1] - 4), []),
        (s["n"][2], s["t"][2], 6, (s["b"][0], y[1] + 30, s["b"][1] - 6, y[2] - 6), []),
        (s["n"][3], s["t"][3], 4, (s["b"][1] + 6, y[1] + 30, 1532, y[2] - 6), []),
        (s["n"][4], s["t"][4], 5, (16, y[2] + 34, s["c"] - 6, y[3] - 6), []),
        (s["n"][5], s["t"][5], 4, (s["c"] + 6, y[2] + 34, 1532, y[3] - 6), []),
    ]


PLANCHES = {
    "01_panda_guerrier.png": dict(
        prefixe="ms-panda", sujet="Panda guerrier (joueur)", role="joueur",
        marques=[(1250, 4, 1536, 44), (16, 0, 256, 132)],
        sections=perso(372, (334, 148, 368, 312), dict(idle=(420, 880), course=(372, 968), tir=767, objet=(604, 1103), ko=768))),
    "02_kangourou_guerrier.png": dict(
        prefixe="ms-kangourou", sujet="Kangourou guerrier (joueur)", role="joueur",
        marques=[(1250, 4, 1536, 44)],
        sections=perso(336, (303, 145, 338, 312), dict(idle=(372, 865), course=(360, 952), tir=748, objet=(605, 1107), ko=770))),
    "03_dodo_guerrier.png": dict(
        prefixe="ms-dodo", sujet="Dodo guerrier (joueur)", role="joueur",
        marques=[(1250, 4, 1536, 44)],
        sections=perso(336, (300, 145, 338, 315), dict(idle=(364, 865), course=(350, 948), tir=738, objet=(603, 1107), ko=768))),
}

_TANK = dict(n=["idle", "demarrage", "deplacement", "arret", "tir-canon", "tir-missile"],
             t=["Idle (repos, en boucle)", "Démarrage (accélération)", "Déplacement (marche)", "Arrêt (freinage)",
                "Tir principal (canon)", "Tir alternatif (missile)"])
_TANK_BAS = lambda sep_saut, sep_destr: [
    ("saut", "Saut (bosses / tremplin)", 5, (16, 664, sep_saut - 6, 800), []),
    ("degats", "Dégâts", 4, (sep_saut + 6, 650, 1532, 800), [(sep_saut + 6, 640, sep_saut + 110, 664)]),
    ("destruction", "Destruction (K.O. / explosion)", 5, (16, 848, sep_destr - 6, 995), []),
    ("reparation", "Réapparition / Réparation (optionnel)", 4, (sep_destr + 6, 848, 1532, 995), []),
]
PLANCHES["04_tank_equipe.png"] = dict(
    prefixe="ms-tank-equipe", sujet="Tank d'équipe avec les trois joueurs (véhicule joueur)", role="vehicule",
    marques=[(1240, 4, 1536, 44)],
    sections=vehicule(404, (404, 122, 436, 265), dict(_TANK, a=(448, 990), b=(430, 1102), c=852), (125, 272, 452, 622))
    + _TANK_BAS(839, 821))
PLANCHES["06_tank_sans_personnage.png"] = dict(
    prefixe="ms-tank", sujet="Tank d'équipe sans personnage (véhicule joueur)", role="vehicule",
    marques=[(1240, 4, 1536, 44)],
    sections=vehicule(380, (378, 118, 412, 285), dict(_TANK, a=(440, 990), b=(430, 1102), c=852), (125, 272, 452, 622))
    + _TANK_BAS(839, 821))
PLANCHES["05_tank_gabarit_vide.png"] = dict(
    prefixe="ms-tank-gabarit", sujet="Tank d'équipe : gabarit vide (cases à remplir)", role="gabarit",
    marques=[(1240, 4, 1536, 44)], sections=[])
PLANCHES["07_helicoptere_dodo.png"] = dict(
    prefixe="ms-helico-dodo", sujet="Hélicoptère piloté par le dodo (véhicule joueur)", role="vehicule",
    marques=[(1250, 4, 1536, 44)],
    sections=vehicule(382, (382, 112, 414, 256), dict(
        n=["idle", "demarrage", "deplacement", "stationnaire", "tir-mitrailleuse", "tir-missile"],
        t=["Idle (repos, en boucle)", "Démarrage (mise en route)", "Déplacement (vol horizontal)",
           "Stationnaire (vol sur place)", "Tir principal (mitrailleuse)", "Tir alternatif (missile)"],
        a=(416, 970), b=(390, 1062), c=862), (105, 258, 437, 608)) + [
        ("montee", "Montée", 4, (62, 640, 481, 792), [(16, 640, 62, 760)]),
        ("descente", "Descente", 4, (538, 640, 944, 792), [(493, 640, 538, 760)]),
        ("degats", "Dégâts", 4, (958, 650, 1532, 792), [(958, 612, 1080, 646)]),
        ("destruction", "Destruction (K.O. / explosion)", 5, (16, 838, 814, 972), []),
        ("reparation", "Réapparition / Réparation (optionnel)", 4, (826, 838, 1532, 972), []),
    ])


def ennemi(px, nuancier, rangs, var_y, titre_var, haut=120):
    """Ennemis champignons (08-12) : rangs = sections propres à la planche, puis la rangée des variantes."""
    return [("portrait", "portrait", 1, (0, haut, px, 420), [nuancier])] + rangs + [
        ("variantes", "Variantes (exemples de level design)", 0, (16, var_y, 1532, 1018), [titre_var])]


PLANCHES["08_escargots_champignons.png"] = dict(
    prefixe="ms-escargot", sujet="Escargot champignon (ennemi)", role="ennemi",
    marques=[(1250, 4, 1536, 44)],
    sections=ennemi(342, (344, 115, 380, 280), [
        ("idle", "Idle (repos, en boucle)", 4, (395, 115, 854, 250), []),
        ("deplacement", "Déplacement (marche / avancée)", 6, (866, 115, 1532, 250), []),
        ("alerte", "Alerte / Détection", 4, (395, 286, 912, 428), [(395, 268, 590, 300)]),
        ("preparation", "Préparation d'attaque", 4, (925, 300, 1532, 428), []),
        ("attaque-spores", "Attaque : tir de spores (projectile)", 4, (16, 470, 763, 610), []),
        ("attaque-saut", "Attaque : saut / charge courte (option)", 4, (775, 444, 1532, 610), [(775, 440, 1192, 470)]),
        ("degats", "Dégâts (réaction)", 4, (16, 650, 569, 790), [(16, 628, 215, 657)]),
        ("ko", "K.O. / Destruction", 4, (581, 650, 1230, 790), []),
        ("elements", "Élément de gameplay : spore (projectile), champignon (bonus / loot)", 2, (1242, 662, 1532, 735), []),
    ], 806, (16, 800, 405, 838), haut=127))
PLANCHES["09_koalas_champignons.png"] = dict(
    prefixe="ms-koala", sujet="Koala champignon (ennemi)", role="ennemi",
    marques=[(1250, 4, 1536, 44)],
    sections=ennemi(338, (342, 115, 375, 285), [
        ("idle", "Idle (repos, en boucle)", 4, (400, 118, 950, 252), []),
        ("demarrage", "Démarrage (mise en mouvement)", 4, (962, 118, 1532, 252), []),
        ("deplacement", "Déplacement (marche / course)", 6, (380, 298, 1064, 424), []),
        ("arret", "Arrêt (freinage)", 4, (1076, 298, 1532, 424), []),
        ("alerte", "Alerte / Détection (repère le joueur)", 4, (16, 458, 703, 598), [(16, 436, 390, 466)]),
        ("attaque-spores", "Attaque principale : lancer de spores", 4, (715, 466, 1532, 598), []),
        ("attaque-charge", "Attaque secondaire : charge / bond", 4, (16, 642, 559, 768), []),
        ("degats", "Dégâts (réaction)", 4, (571, 640, 1054, 768), [(571, 615, 760, 645)]),
        ("ko", "K.O. / Destruction", 4, (1066, 642, 1532, 768), []),
    ], 782, (16, 784, 395, 816)))
PLANCHES["10_moineaux_champignons.png"] = dict(
    prefixe="ms-moineau", sujet="Moineau champignon (ennemi)", role="ennemi",
    marques=[(1250, 4, 1536, 44)],
    sections=ennemi(324, (330, 115, 366, 280), [
        ("idle", "Idle (repos, en boucle)", 4, (388, 112, 919, 245), []),
        ("decollage", "Décollage (envol)", 4, (931, 96, 1532, 245), [(950, 80, 1150, 114)]),
        ("vol", "Vol (boucle)", 6, (380, 290, 1049, 422), []),
        ("atterrissage", "Atterrissage", 4, (1061, 290, 1532, 422), []),
        ("alerte", "Alerte / Détection (repère le joueur)", 4, (16, 440, 699, 598), [(16, 434, 425, 466)]),
        ("attaque-spores", "Attaque principale : tir de spores", 4, (711, 466, 1532, 598), []),
        ("attaque-pique", "Attaque secondaire : piqué (charge aérienne)", 4, (16, 640, 564, 768), []),
        ("degats", "Dégâts (réaction)", 4, (576, 640, 1057, 768), []),
        ("ko", "K.O. / Destruction", 4, (1069, 640, 1532, 768), []),
    ], 778, (16, 778, 415, 814)))
PLANCHES["11_serpents_champignons.png"] = dict(
    prefixe="ms-serpent", sujet="Serpent champignon (ennemi)", role="ennemi",
    marques=[(1250, 4, 1536, 44)],
    sections=ennemi(330, (334, 112, 370, 280), [
        ("idle", "Idle (repos, en boucle)", 4, (378, 112, 898, 248), []),
        ("apparition", "Sortie du sol / Apparition", 5, (910, 108, 1532, 248), [(910, 82, 1195, 112)]),
        ("deplacement", "Déplacement (rampement)", 6, (358, 292, 1047, 412), []),
        ("alerte", "Alerte / Détection (repère le joueur)", 4, (1059, 266, 1532, 412), [(1059, 260, 1432, 293)]),
        ("attaque-spores", "Attaque principale : crachat de spores", 4, (16, 456, 688, 584), []),
        ("attaque-morsure", "Attaque secondaire : morsure / bond court", 5, (700, 440, 1532, 584), [(700, 424, 1166, 457)]),
        ("degats", "Dégâts (réaction)", 4, (16, 616, 559, 748), [(16, 594, 215, 622)]),
        ("ko", "K.O. / Destruction", 4, (571, 620, 1183, 748), []),
        ("elements", "Élément de gameplay : spore (projectile), champignon (bonus / loot)", 2, (1195, 625, 1532, 700), []),
    ], 764, (16, 762, 415, 794)))
PLANCHES["12_alligators_champignons.png"] = dict(
    prefixe="ms-alligator", sujet="Alligator champignon (ennemi)", role="ennemi",
    marques=[(1250, 4, 1536, 44)],
    sections=ennemi(352, (352, 112, 385, 280), [
        ("idle", "Idle (repos, en boucle)", 4, (398, 115, 951, 250), []),
        ("reveil", "Réveil / Sortie de l'eau ou du sol", 4, (963, 115, 1532, 250), []),
        ("deplacement", "Déplacement (marche)", 6, (378, 295, 1056, 424), []),
        ("alerte", "Alerte / Détection (repère le joueur)", 4, (1068, 262, 1532, 424), [(1068, 258, 1445, 293)]),
        ("attaque-spores", "Attaque principale : crachat de spores (projectile)", 4, (16, 468, 687, 594), []),
        ("attaque-morsure", "Attaque secondaire : charge / morsure", 5, (699, 462, 1532, 594), []),
        ("degats", "Dégâts (réaction)", 4, (16, 634, 574, 764), []),
        ("ko", "K.O. / Destruction", 4, (586, 634, 1244, 764), []),
        ("elements", "Élément de gameplay : spore (projectile), champignon (bonus / loot)", 2, (1256, 640, 1532, 712), []),
    ], 780, (16, 780, 415, 814)))

# Décors (13, 14) : None = découpe XY des éléments.
PLANCHES["13_batiments_jungle.png"] = dict(
    prefixe="ms-jungle-batiments", sujet="Décors de jungle : bâtiments", role="decor",
    marques=[(1170, 4, 1536, 44)],
    sections=[
        ("batiment", "Bâtiments", None, (0, 70, 1536, 320), [(0, 0, 210, 114)]),
        ("tuile-terrain", "Tuiles de terrain (32×32)", None, (12, 358, 316, 604), []),
        ("bloc-plateforme", "Blocs et plateformes", None, (326, 358, 578, 604), []),
        ("ouverture", "Ouvertures et passages", None, (588, 358, 1166, 478), []),
        ("module", "Fenêtres, détails & modules", None, (1176, 358, 1532, 528), []),
        ("interactif", "Éléments interactifs / gameplay", None, (588, 496, 1374, 604), [(588, 490, 862, 518), (1176, 480, 1380, 528)]),
        ("vegetation", "Végétation & décoration", None, (8, 648, 464, 796), []),
        ("modulaire", "Éléments modulaires (assemblage)", None, (472, 648, 1044, 796), []),
        ("assemblage", "Exemples d'assemblages (variantes)", None, (1052, 648, 1532, 796), []),
        ("parallaxe", "Arrière-plans (parallaxe, multiples plans)", 1, (12, 834, 1100, 1020), []),
        ("ambiance", "Variantes d'ambiance", None, (1116, 834, 1532, 1020), []),
    ])
PLANCHES["14_habitations_jungle.png"] = dict(
    prefixe="ms-jungle-habitations", sujet="Décors de jungle : habitations", role="decor",
    marques=[(1170, 4, 1536, 44)],
    sections=[
        ("habitation", "Habitations", None, (0, 72, 1536, 288), [(0, 0, 205, 120)]),
        ("habitation-variante", "Habitations : variantes", None, (8, 318, 818, 438), []),
        ("pilotis", "Habitations sur pilotis / passerelles", None, (828, 318, 1532, 438), []),
        ("construction", "Éléments de construction (modulaires)", None, (12, 474, 574, 580), []),
        ("ouverture", "Ouvertures & détails", None, (586, 466, 1114, 580), []),
        ("toit", "Toits (variantes)", None, (1126, 474, 1532, 566), []),
        ("decoration", "Décorations & vie", None, (8, 614, 824, 734), []),
        ("assemblage", "Exemples d'assemblages (habitations complètes)", None, (832, 612, 1532, 740), []),
        ("tuile-terrain", "Tuiles de terrain (32×32)", None, (12, 778, 298, 1020), []),
        ("ambiance", "Palettes & ambiances (exemples)", None, (312, 778, 804, 1020), []),
        ("integration", "Détails d'intégration (exemple in-game)", 1, (816, 778, 1532, 1020), []),
    ])

# Les variantes des ennemis : 5 (escargot) ou 6 colonnes.
VARIANTES = {"ms-escargot": ["classique", "toxique", "blinde", "explosif", "geant"],
             "ms-koala": ["standard", "toxique", "explosif", "blinde", "lanceur", "geant"],
             "ms-moineau": ["standard", "toxique", "explosif", "blinde", "lanceur", "geant"],
             "ms-serpent": ["standard", "toxique", "explosif", "blinde", "lanceur", "geant"],
             "ms-alligator": ["standard", "toxique", "blinde", "explosif", "lanceur", "geant"]}
for _p in PLANCHES.values():
    _p["sections"] = [(a, l, (len(VARIANTES[_p["prefixe"]]) if a == "variantes" else n), r, e) for a, l, n, r, e in _p["sections"]]
