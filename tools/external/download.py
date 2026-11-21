"""DownloadManager (EXT-001 § 8) : téléchargements bornés, empreinte SHA-256, reprise sur erreur réseau.

Bornes : taille (MAX_BYTES), durée (TIMEOUT par essai), 3 essais avec attente croissante, au plus une requête
par seconde et par hôte. HTTPS ou file:// seulement ; aucun dialogue, aucune authentification contournée.
"""

import hashlib
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MAX_BYTES = 200 * 1024 * 1024
TIMEOUT = 60
ATTEMPTS = 3


class DownloadError(OSError):
    pass


class DownloadManager:
    def __init__(self, max_bytes=MAX_BYTES, timeout=TIMEOUT, attempts=ATTEMPTS, pause=1.0):
        self.max_bytes, self.timeout, self.attempts, self.pause = max_bytes, timeout, attempts, pause
        self.last = {}

    def _throttle(self, host):
        wait = self.last.get(host, 0) + self.pause - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last[host] = time.monotonic()

    def fetch(self, url, destination):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in {"https", "file"}:
            raise DownloadError(f"Schéma refusé : {parts.scheme or '—'} (HTTPS ou file:// seulement).")
        destination = Path(destination)
        error = None
        for attempt in range(self.attempts):
            if attempt and parts.scheme == "https":
                time.sleep(min(2 ** attempt, 8) * self.pause)
            if parts.scheme == "https":
                self._throttle(parts.netloc)
            try:
                return self._once(url, destination)
            except DownloadError:
                raise
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                error = exc
        raise DownloadError(f"Téléchargement impossible après {self.attempts} essais ({type(error).__name__}).")

    def _once(self, url, destination):
        digest, size = hashlib.sha256(), 0
        partial = destination.with_name(destination.name + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": "opencade-asset-registry"})
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=self.timeout) as response, open(partial, "wb") as out:
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > self.max_bytes:
                raise DownloadError(f"Archive trop grande ({declared} octets > {self.max_bytes}).")
            while chunk := response.read(1 << 16):
                size += len(chunk)
                if size > self.max_bytes:
                    out.close()
                    partial.unlink(missing_ok=True)
                    raise DownloadError(f"Archive trop grande (> {self.max_bytes} octets).")
                if time.monotonic() - started > self.timeout:
                    out.close()
                    partial.unlink(missing_ok=True)
                    raise DownloadError("Durée de téléchargement dépassée.")
                digest.update(chunk)
                out.write(chunk)
            etag, modified = response.headers.get("ETag"), response.headers.get("Last-Modified")
        partial.replace(destination)
        return {"sha256": digest.hexdigest(), "bytes": size, "etag": etag, "lastModified": modified}
