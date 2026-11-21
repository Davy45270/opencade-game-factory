"""EXT-002 — Level & World Library : inventaire, import, recherche, génération, validation et publication de niveaux.

Module du dépôt unique de l'usine (décision de David, HL-525 7-2955) : `assetctl level …` tient lieu de `levelctl`,
avec les codes de retour propres à la spec EXT-002 (06_CLI_AGENTS) : `LevelExit`, et leur correspondance vers la
table commune dans docs/ARCHITECTURE.md § Niveaux et mondes. Rien hors de ce paquet n'en dépend ;
`ASSETCTL_LEVELS=off` le désactive.
"""

import os
from enum import IntEnum


class LevelExit(IntEnum):
    """Codes de retour de `assetctl level` (= levelctl), tels que la spec EXT-002 les fixe."""
    OK = 0
    INVALID_INPUT = 2
    MISSING_REFERENCE = 3
    VALIDATION_FAILED = 4
    RIGHTS_BLOCKED = 5
    INCONCLUSIVE = 6
    INFRASTRUCTURE = 7


MISSING_REFERENCE_CODES = {"asset-missing", "level-not-found"}


def status_code(status, diagnostics=()):
    """Code d'un rapport de validation ou de simulation : `inconclusive` n'est jamais un succès ni un échec ; un
    échec dû à une référence absente (asset EXT-001, niveau) rend 3 avant tout autre échec, car il se corrige d'abord."""
    if status == "pass":
        return LevelExit.OK
    if status == "inconclusive":
        return LevelExit.INCONCLUSIVE
    if any(d.get("code") in MISSING_REFERENCE_CODES and d.get("severity", "error") == "error" for d in diagnostics):
        return LevelExit.MISSING_REFERENCE
    return LevelExit.VALIDATION_FAILED


def enabled():
    return os.environ.get("ASSETCTL_LEVELS", "on").lower() not in {"off", "0", "false", "no"}
