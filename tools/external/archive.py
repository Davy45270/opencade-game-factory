"""Inspection d'archive avant tout import (EXT-001 § 8, EXT-T06) — rien n'est extrait ni exécuté ici.

Refus : chemins absolus ou traversants (`../`), liens symboliques, exécutables, bombes ZIP (taille décompressée,
nombre de fichiers, taux de compression), formats annoncés que le contenu dément. Une archive refusée part en
quarantaine (build/quarantine/), avec son rapport ; rien n'est importé.
"""

import hashlib
import json
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from tools.discovery.formats import Unreadable, inspect

MAX_FILES = 5000
MAX_TOTAL = 500 * 1024 * 1024
MAX_RATIO = 200
MEDIA = {"png", "jpg", "jpeg", "webp", "gif", "svg", "ogg", "wav", "mp3", "ttf", "otf", "woff", "woff2"}
TEXT = {"txt", "md", "json", "xml", "tmx", "tsx", "tmj", "tsj", "csv", "url", "html"}
EXECUTABLE = {"exe", "dll", "so", "dylib", "bat", "cmd", "com", "sh", "ps1", "vbs", "js", "jar", "py", "app",
              "msi", "scr", "lua", "command"}
MAGIC = (b"MZ", b"\x7fELF", b"#!", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")
QUARANTINE = Path("build") / "quarantine"


def _kind(name):
    return PurePosixPath(name).suffix.lower().lstrip(".")


def inspect_archive(path):
    """Rend {ok, problems, media: [{path, sha256, format, family, dimensions, alpha}], texts: {path: texte}}."""
    problems, media, texts = [], [], {}
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        return {"ok": False, "problems": ["archive illisible ou format réel différent de ZIP"], "media": [], "texts": {}}
    with archive:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        if len(entries) > MAX_FILES:
            problems.append(f"trop de fichiers ({len(entries)} > {MAX_FILES})")
        total = sum(info.file_size for info in entries)
        if total > MAX_TOTAL:
            problems.append(f"taille décompressée excessive ({total} octets)")
        for info in archive.infolist():
            name = info.filename
            parts = PurePosixPath(name.replace("\\", "/")).parts
            if name.startswith(("/", "\\")) or (len(name) > 1 and name[1] == ":") or ".." in parts:
                problems.append(f"chemin traversant ou absolu : {name}")
                continue
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                problems.append(f"lien symbolique : {name}")
                continue
            if info.is_dir():
                continue
            if info.compress_size and info.file_size / info.compress_size > MAX_RATIO and info.file_size > 1 << 20:
                problems.append(f"taux de compression suspect : {name}")
                continue
            kind = _kind(name)
            if kind in EXECUTABLE or mode & 0o111:
                problems.append(f"exécutable non sollicité : {name}")
                continue
            if kind not in MEDIA | TEXT:
                continue
            data = archive.read(info)
            if data.startswith(MAGIC):
                problems.append(f"contenu exécutable sous l'extension .{kind} : {name}")
                continue
            if kind in TEXT:
                texts[name] = data.decode("utf-8", errors="replace")
                continue
            try:
                measured = inspect(name, data)
            except Unreadable:
                problems.append(f"format réel différent de .{kind} : {name}")
                continue
            media.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "format": kind,
                          "family": measured.family if measured else None,
                          "dimensions": measured.dimensions if measured else None,
                          "alpha": measured.alpha if measured else None})
    return {"ok": not problems, "problems": problems, "media": sorted(media, key=lambda row: row["path"]),
            "texts": texts}


def quarantine(root, archive, sha256, report):
    """Isole l'archive refusée et son rapport ; rend le chemin relatif du rapport."""
    folder = Path(root) / QUARANTINE
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(archive, folder / f"{sha256}.zip")
    target = folder / f"{sha256}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(target.relative_to(root))
