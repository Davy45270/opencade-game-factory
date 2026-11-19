"""Codes de retour COMMUNS à toutes les sous-commandes de l'usine (assetctl, et demain specctl, levelctl, blocks).
Table unique : docs/ARCHITECTURE.md § Codes de retour (alignée sur specctl, HL-525 7-2957)."""
from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    CHECK_FAILED = 1
    USAGE = 2
    SAFETY = 3
    IO = 4  # source indisponible : entrée/sortie, réseau, dépendance, miroir injoignable
    VERSION_CONFLICT = 5  # conflit de versions : base ou catalogue modifié entre lecture et écriture, ID déjà pris
