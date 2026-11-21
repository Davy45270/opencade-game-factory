"""EXT-002 — Level & World Library : inventaire, import, recherche, génération, validation et publication de niveaux.

Module du dépôt unique de l'usine (décision de David, HL-525 7-2955) : `assetctl level …` tient lieu de `levelctl`,
avec les codes de retour communs (docs/ARCHITECTURE.md § Codes de retour). Rien hors de ce paquet n'en dépend ;
`ASSETCTL_LEVELS=off` le désactive.
"""

import os


def enabled():
    return os.environ.get("ASSETCTL_LEVELS", "on").lower() not in {"off", "0", "false", "no"}
