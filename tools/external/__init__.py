"""EXT-001 — découverte et import de bibliothèques d'assets externes (spec EXT-001 v1.0).

Module optionnel et indépendant (§ 1) : ASSETCTL_EXTERNAL=off le désactive ; la recherche et les imports
internes n'en dépendent pas (aucun import de ce paquet hors de `assetctl external`).

Correspondance des interfaces de la spec (§ 4, écrites en TypeScript ; le registre est en Python) :
ProviderAdapter, ExternalAssetCandidate (adapters.py), LicenseEvaluator (licenses.py), DownloadManager
(download.py), ImportPlanner et ImportExecutor (importer.py), ExternalIndex (adapters.py), ImportDecision
(decision.py).
"""

import os


def enabled(environ=None):
    value = (os.environ if environ is None else environ).get("ASSETCTL_EXTERNAL", "on")
    return value.strip().lower() not in {"0", "off", "false", "no", "non"}
