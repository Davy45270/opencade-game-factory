"""Client HTTP générique des catalogues publics (EXT-001 § 2, § 8, § 9).

- En-têtes : un User-Agent générique (`opencade-asset-registry`), rien d'autre ; aucun cookie, aucune adresse,
  aucun nom, aucun jeton (une URL qui en porte est refusée).
- robots.txt respecté AVANT toute requête : pour l'agent du registre ET pour les agents IA qui le pilotent
  (Codex, Claude Code : spec § 1). Un site qui refuse l'un d'eux est refusé : un client « générique » ne sert pas
  à contourner un refus (§ 2 : pas de scraping contournant les conditions).
- Crawl-delay du site respecté (1 s au moins), requêtes conditionnelles (ETag, Last-Modified) pour la
  synchronisation incrémentale : un 304 ne relit rien.
- Toute panne ou tout refus lève ProviderUnavailable : jamais un « aucun résultat ».
"""

import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from tools.external.adapters import ProviderUnavailable, _carries_secret

USER_AGENT = "opencade-asset-registry"
# Agents IA qui pilotent le registre (spec § 1) : jetons « utilisateur » et robots de leurs éditeurs.
AGENT_TOKENS = ("Claude-User", "Claude-Code", "ClaudeBot", "anthropic-ai", "ChatGPT-User", "GPTBot", "OAI-SearchBot")
MAX_BYTES = 20 * 1024 * 1024


class RobotsRefusal(ProviderUnavailable):
    """Le site refuse ce chemin à l'agent du registre ou à un agent IA qui le pilote."""


class Client:
    def __init__(self, opener=None, pause=1.0, timeout=30):
        self.opener = opener or urllib.request.urlopen
        self.pause, self.timeout = pause, timeout
        self.robots, self.last = {}, {}

    def _raw(self, url, headers=None):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ProviderUnavailable(f"Réponse trop grande ({url}).")
                return getattr(response, "status", 200), body, dict(response.headers or {})
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return 304, b"", dict(exc.headers or {})
            raise ProviderUnavailable(f"{urllib.parse.urlsplit(url).netloc} répond {exc.code}.") from None
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ProviderUnavailable(f"{urllib.parse.urlsplit(url).netloc} injoignable ({type(exc).__name__}).") \
                from None

    def _rules(self, host_url):
        if host_url not in self.robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                status, body, _ = self._raw(host_url + "/robots.txt")
                parser.parse(body.decode("utf-8", errors="replace").splitlines())
            except ProviderUnavailable as exc:
                # robots.txt absent (404) : tout est permis ; injoignable : le site l'est aussi.
                if " 404" in str(exc) or " 410" in str(exc):
                    parser.parse([])
                else:
                    raise
            self.robots[host_url] = parser
        return self.robots[host_url]

    def check(self, url):
        """Rend le délai à respecter, ou lève RobotsRefusal en nommant l'agent refusé."""
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https":
            raise ProviderUnavailable(f"HTTPS seulement : {parts.scheme or '—'}.")
        if _carries_secret(url):
            raise ProviderUnavailable("URL porteuse d'un identifiant ou d'un jeton : refusée.")
        rules = self._rules(f"https://{parts.netloc}")
        for agent in (USER_AGENT, *AGENT_TOKENS):
            if not rules.can_fetch(agent, url):
                raise RobotsRefusal(f"robots.txt de {parts.netloc} refuse {parts.path or '/'} à {agent}.")
        return max(self.pause, float(rules.crawl_delay(USER_AGENT) or 0))

    def get(self, url, etag=None, modified=None):
        """GET poli : rend (statut, octets, en-têtes) ; 304 quand la ressource n'a pas changé."""
        delay = self.check(url)
        host = urllib.parse.urlsplit(url).netloc
        wait = self.last.get(host, 0) + delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        try:
            return self._raw(url, headers)
        finally:
            self.last[host] = time.monotonic()
