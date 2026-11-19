"""Normalisation ImageMagick déclarée par une recette de découpe."""

import os
import re
import subprocess
import tempfile
from pathlib import Path
from shutil import which

from PIL import Image

VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9]+)?")
TIMEOUT = 30


class MagickError(ValueError):
    pass


def installed():
    executable = which("magick")
    if executable:
        try:
            result = subprocess.run([executable, "-version"], capture_output=True, check=True, timeout=TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            return None
        match = re.search(rb"ImageMagick (" + VERSION.pattern.encode("ascii") + rb")(?=\s|$)", result.stdout)
        if match:
            return os.path.abspath(executable), match[1].decode("ascii")
    return None


def normalize(executable, image, box, margin, size, anchor):
    x, y, w, h = (box[key] for key in "xywh")
    geometry = f"{w + 2 * margin}x{h + 2 * margin}{x - margin:+d}{y - margin:+d}"
    extent = f"{size[0]}x{size[1]}"
    gravity = "south" if anchor == "bas" else "center"
    try:
        with tempfile.TemporaryDirectory(prefix="assetctl-magick-", dir="/tmp") as temporary:
            source = Path(temporary) / "source.png"
            destination = Path(temporary) / "frame.png"
            image.save(source, format="PNG")
            subprocess.run(
                [executable, str(source), "-crop", geometry, "+repage", "-channel", "A",
                 "-fx", "u<0.04?0:u", "+channel", "-trim", "+repage", "-resize", extent,
                 "-background", "none", "-gravity", gravity, "-extent", extent, f"PNG32:{destination}"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=TIMEOUT,
                cwd=temporary, env={**os.environ, "MAGICK_TEMPORARY_PATH": temporary},
            )
            with Image.open(destination) as result:
                return result.convert("RGBA")
    except (OSError, subprocess.SubprocessError) as exc:
        raise MagickError("magick-normalization-failed") from exc
