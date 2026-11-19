"""Export en mode batch des planches Aseprite."""

import os
import shutil
import subprocess
from pathlib import Path

BUILT_ASEPRITE = Path("/home/david/Projets/outils/aseprite/build/bin/aseprite")


def executable():
    configured = os.environ.get("ASEPRITE")
    if configured and (binary := shutil.which(configured)):
        return binary
    if os.access(BUILT_ASEPRITE, os.X_OK):
        return str(BUILT_ASEPRITE)
    return shutil.which("libresprite")


def export(source, png, metadata):
    binary = executable()
    if not binary:
        raise OSError("Aseprite indisponible. Renseignez ASEPRITE ou installez LibreSprite.")
    try:
        result = subprocess.run(
            [binary, "--batch", str(source.resolve()), "--sheet", str(png.resolve()),
             "--data", str(metadata.resolve()), "--format", "json-hash"],
            env={**os.environ, "SDL_VIDEODRIVER": "dummy"}, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise OSError("Délai d’export Aseprite dépassé.") from exc
    if result.returncode or not png.is_file() or not metadata.is_file():
        raise OSError("L’export Aseprite en PNG et JSON hash a échoué.")
