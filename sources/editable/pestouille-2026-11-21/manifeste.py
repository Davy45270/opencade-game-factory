"""Manifeste des sources Pestouille enregistrées au registre (HL-538, 2026-11-21). Aucune valeur inventée :
sujet, type et taille sont lus sur le cartouche de chaque planche (INVENTAIRE.md du 21/11) ; les familles
viennent du rangement de David dans Drive."""
DRIVE = "Drive « Homelab/assets/Pestouille » (dossier 1scASvVoE8lhWVHn6bViMsocWWMrAkJ65), déposé par David le 2026-11-21 entre 12:37 et 12:39 UTC"
SPEC = "Drive de David (dossier 1QcNf1uDi8to793k8sFR4LnHmsB0PtAGv, sources de la spec Pestouille RPG v1.x), déposé le 2026-11-18 entre 18:00 et 18:45 UTC ; copie sans modification dans homelab-docs/specs/pestouille-rpg-sources/planches/"
TELEGRAM = "Telegram, envoyé par David le 2026-11-21 (HL-541) ; copie sans modification dans homelab-docs/specs/pestouille-rpg-sources/planches/"

# fichier, préfixe d'ID, sujet, famille, gabarit, options de découpe, requête de recherche
DECOUPEES = [
    ("pestouille_face.png", "pestouille-face", "Pestouille de face", "heros", "planche19", [], "pestouille"),
    ("pestouille_dos.png", "pestouille-dos", "Pestouille de dos", "heros", "planche19", ["--seuil-alpha", "128"], "pestouille"),
    ("pestouille_profil_droit.png", "pestouille-profil-droit", "Pestouille de profil droit", "heros", "planche19", [], "pestouille"),
    ("pestouille_4directions.png", "pestouille-4directions", "Pestouille, planche 4 directions", "heros", "gabarit4", ["--attaque-verifiee"], "pestouille"),
    ("pestouille_armure.png", "pestouille-armure", "Pestouille en armure (chevalier)", "heros", "gabarit4", [], "pestouille"),
    ("pestouille_noel.png", "pestouille-noel", "Pestouille en Père Noël", "heros", "gabarit4", [], "pestouille"),
    ("golem_pierre.png", "golem-pierre", "Golem de pierre (type Golem, taille M)", "creature", "gabarit4", ["--attaque-verifiee"], "golem"),
    ("arbre_vivant.png", "arbre-vivant", "Arbre vivant (type Plante, taille M)", "creature", "gabarit4", [], "arbre"),
    ("araignee_grotte.png", "araignee-grotte", "Araignée de grotte (taille M)", "creature", "gabarit4", [], "araignee"),
    ("chauve_souris.png", "chauve-souris", "Chauve-souris de grotte (type Volant, taille M)", "creature", "gabarit4", [], "chauve-souris"),
    ("telephone_malicieux.png", "telephone-malicieux", "Téléphone malicieux (type Objet animé, taille M)", "creature", "gabarit4", ["--attaque-reelle", "bas=5,haut=5"], "telephone"),
    ("troll.png", "troll", "Troll des cavernes (taille M)", "creature", "gabarit4", [], "troll"),
    ("requin.png", "requin", "Requin des récifs (type Aquatique, taille M)", "creature", "gabarit4", [], "requin"),
    ("meduse.png", "meduse", "Méduse luminescente (type Aquatique, taille M)", "creature", "gabarit4", [], "meduse"),
    ("pieuvre.png", "pieuvre", "Pieuvre des profondeurs (type Aquatique, taille L)", "creature", "gabarit4", [], "pieuvre"),
    ("moustique.png", "moustique", "Moustique piqueur (type Aérien, taille S)", "creature", "gabarit4", ["--attaque-reelle", "bas=5,haut=5"], "moustique"),
    ("guepe.png", "guepe", "Guêpe guerrière (type Aérien, taille S)", "creature", "gabarit4", [], "guepe"),
    ("poubelle.png", "poubelle", "Poubelle malicieuse (type Objet vivant, taille M)", "creature", "gabarit4", [], "poubelle"),
    ("robot.png", "robot", "Robot « Netoyer X1 » (type Mécanique, taille M)", "creature", "gabarit4", [], "robot"),
    ("diable.png", "diable", "Diable malicieux (type Démon, taille M)", "creature", "gabarit4", [], "diable"),
    ("amanite.png", "amanite", "Champignon malicieux, amanite (type Végétal, taille M)", "creature", "gabarit4", [], "amanite"),
    ("cepe.png", "cepe", "Cep malicieux, bolet (type Végétal, taille M)", "creature", "gabarit4", [], "cepe"),
    ("vampire.png", "vampire", "Vampire malicieux (type Mort-vivant, taille M)", "creature", "gabarit4", ["--attaque-reelle", "bas=5,haut=5"], "vampire"),
    ("koala.png", "koala", "Koala malicieux (type Animal, taille M)", "creature", "gabarit4", [], "koala"),
    ("blob_vert_4directions.png", "blob-vert-4directions", "Blob vert, 4 directions (type Blob, taille M)", "variante", "gabarit4", ["--attaque-reelle", "bas=7,haut=7"], "blob"),
    ("plante_verte_4directions.png", "plante-verte-4directions", "Plante carnivore verte, 4 directions (type Plante, taille M)", "variante", "gabarit4", ["--attaque-verifiee"], "plante"),
    ("blobs_variantes.png", "blobs-variantes", "Six blobs (vert, bleu, feu, glace, poison, or), profil droit", "variante", "variantes", ["--variantes", "vert,bleu,feu,glace,poison,or"], "blob"),
    ("plantes_variantes.png", "plantes-variantes", "Six plantes carnivores (verte, feu, glace, poison, électrique, épines), profil droit", "variante", "variantes", ["--variantes", "verte,feu,glace,poison,electrique,epines"], "plante"),
]
# planches enregistrées seules (fichier, chemin, sujet, canal, raison)
SEULES = [
    ("plantes_tailles.png", None, "Bestiaire plantes carnivores et tailles S/M/L", DRIVE,
     "Doublon partiel de plantes_variantes.png (même tableau, plus petit) ; seule la rangée des tailles S/M/L est nouvelle. Non découpée : pas de découpe automatique fiable des deux zones."),
    ("Pestouille_RPG_Animations_Face_HL541.jpg", "planches", "Pestouille de face (JPEG)", TELEGRAM,
     "Version JPEG du dessin dont pestouille_face.png est la version PNG sans perte ; non découpée ici pour ne pas créer de doublon."),
    ("Pestouille_RPG_Animations_Dos_HL541.jpg", "planches", "Pestouille de dos (JPEG)", TELEGRAM,
     "Version JPEG du dessin dont pestouille_dos.png est la version PNG sans perte ; non découpée ici pour ne pas créer de doublon."),
    ("Pestouille_RPG_Animations_Profil_HL541.jpg", "planches", "Pestouille de profil droit (JPEG)", TELEGRAM,
     "Version JPEG du dessin dont pestouille_profil_droit.png est la version PNG sans perte ; non découpée ici pour ne pas créer de doublon."),
    ("Pestouille_Planche_01_Univers_Gameplay.png", "planches", "Planche 01 : univers et gameplay", SPEC, "Planche de spécification déjà découpée par le jeu (tables assets/source/*.decoupe.json de pestouille-rpg) ; ses cadres relèvent de l'inventaire du jeu."),
    ("Pestouille_Planche_02_Sprites_Tilesets_Enigmes.png", "planches", "Planche 02 : sprites, tilesets, énigmes", SPEC, "Planche déjà découpée par le jeu (p02-*.decoupe.json) ; ses cadres relèvent de l'inventaire du jeu."),
    ("Pestouille_RPG_Elements_03_Monde_Interface.png", "planches", "Éléments 03 : monde et interface", SPEC, "Planche déjà découpée par le jeu (e03-*.decoupe.json) ; ses cadres relèvent de l'inventaire du jeu."),
    ("Pestouille_RPG_Elements_04_Combat_Progression.png", "planches", "Éléments 04 : combat et progression", SPEC, "Planche déjà découpée par le jeu (e04-*.decoupe.json) ; ses cadres relèvent de l'inventaire du jeu."),
    ("Pestouille_RPG_Maquette_01_Exploration_Combat.png", "planches", "Maquette 01 : exploration et combat", SPEC, "Maquette d'écran déjà découpée par le jeu (m01-*.decoupe.json) ; ses cadres relèvent de l'inventaire du jeu."),
    ("Pestouille_RPG_Maquette_02_Metiers_Recrutement.png", "planches", "Maquette 02 : métiers et recrutement", SPEC, "Maquette d'écran déjà découpée par le jeu (m02-*.decoupe.json) ; ses cadres relèvent de l'inventaire du jeu."),
]
JPEG_DE = {"pestouille_face.png": "Pestouille_RPG_Animations_Face_HL541.jpg",
           "pestouille_dos.png": "Pestouille_RPG_Animations_Dos_HL541.jpg",
           "pestouille_profil_droit.png": "Pestouille_RPG_Animations_Profil_HL541.jpg"}
RMSE = {"pestouille_face.png": "0,024", "pestouille_dos.png": "0,020", "pestouille_profil_droit.png": "0,034"}
