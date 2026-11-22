"""ProviderAdapter, registre des fournisseurs et ExternalIndex (EXT-001 § 4, EXT-01).

Un adaptateur lit l'index d'un fournisseur : un JSON versionné (`external/<fournisseur>/index.json` du registre,
ou le chemin/URL de ASSETCTL_EXTERNAL_INDEX_<FOURNISSEUR>). L'index ne fait que DÉCRIRE des packs ; la licence
d'un pack n'est tenue pour vérifiée qu'après lecture de son texte dans l'archive (licenses.py).
Aucun scraping : l'adaptateur ne contourne ni authentification, ni anti-bot, ni condition de téléchargement (§ 2).
"""

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
EXTERNAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
CONFIDENCE = ("verified", "inferred", "unknown")


class ProviderUnavailable(OSError):
    """Fournisseur injoignable ou index illisible : jamais un « aucun résultat » (EXT-T07)."""


class NotHarvested(ProviderUnavailable):
    """Aucun index collecté pour ce fournisseur : il n'a pas été consulté (dit tel quel, jamais « rien »)."""


@dataclass(frozen=True)
class ExternalAssetCandidate:
    provider: str
    externalId: str
    title: str
    sourceUrl: str
    downloadUrl: str | None = None
    author: str | None = None
    licenseSpdx: str | None = None
    licenseEvidenceUrl: str | None = None
    tags: tuple = ()
    mediaType: str | None = None
    metadataConfidence: str = "unknown"
    sourceVersion: str | None = None
    # Licences offertes au choix par la source (licences mixtes, EXT-08/EXT-09) et crédits exigés (auteurs, URL).
    licenseOptions: tuple = ()
    credits: dict | None = None

    def to_json(self):
        data = asdict(self)
        data["tags"] = list(self.tags)
        data["licenseOptions"] = list(self.licenseOptions)
        return data


@dataclass
class ProviderAdapter:
    """Interface commune : search, inspect, download (EXT-001 § 4)."""

    id: str
    policy: str
    priority: str
    root: Path = field(default_factory=Path)

    def search(self, query, filters):
        raise NotImplementedError

    def inspect(self, external_id):
        raise NotImplementedError

    def download(self, external_id, destination, manager):
        raise NotImplementedError


def _carries_secret(url):
    """Jamais de jeton dans un index, un plan ou une fiche (EXT-001 § 7)."""
    if not url:
        return False
    parts = urllib.parse.urlsplit(str(url))
    query = {key.lower() for key, _ in urllib.parse.parse_qsl(parts.query)}
    return bool(parts.username or parts.password or query & {"token", "access_token", "key", "apikey", "api_key",
                                                              "signature", "sig", "auth"})


def _terms(text):
    return {word for word in re.findall(r"[a-z0-9]+", str(text).casefold()) if len(word) > 1}


class IndexedProvider(ProviderAdapter):
    """Adaptateur fondé sur un index de packs (ExternalIndex)."""

    def index_location(self):
        override = os.environ.get(f"ASSETCTL_EXTERNAL_INDEX_{self.id.upper().replace('-', '_')}")
        return override or str(self.root / "external" / self.id / "index.json")

    def packs(self):
        location = self.index_location()
        overridden = f"ASSETCTL_EXTERNAL_INDEX_{self.id.upper().replace('-', '_')}" in os.environ
        if not overridden and not Path(location).exists():
            raise NotHarvested(f"Index {self.id} jamais collecté (assetctl external refresh --provider {self.id}).")
        try:
            if re.match(r"https?://", location):
                with urllib.request.urlopen(location, timeout=20) as response:
                    data = json.loads(response.read(5_000_000))
            else:
                data = json.loads(Path(location).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProviderUnavailable(f"Index {self.id} indisponible ({type(exc).__name__}).") from None
        if not isinstance(data, dict) or data.get("provider") != self.id or not isinstance(data.get("packs"), list):
            raise ProviderUnavailable(f"Index {self.id} invalide.")
        return [self.candidate(row) for row in data["packs"]]

    def candidate(self, row):
        if not isinstance(row, dict) or not EXTERNAL_ID.fullmatch(str(row.get("externalId", ""))):
            raise ProviderUnavailable(f"Index {self.id} : pack sans externalId valide.")
        for name in ("sourceUrl", "downloadUrl", "licenseEvidenceUrl"):
            if _carries_secret(row.get(name)):
                raise ProviderUnavailable(f"Index {self.id} : {name} porte un identifiant ou un jeton ; refusé.")
        license_id = row.get("licenseSpdx")
        evidence = row.get("licenseEvidenceUrl")
        confidence = row.get("metadataConfidence")
        if confidence not in CONFIDENCE:
            confidence = "inferred" if license_id and evidence else "unknown"
        return ExternalAssetCandidate(
            provider=self.id, externalId=row["externalId"], title=str(row.get("title") or row["externalId"]),
            sourceUrl=str(row.get("sourceUrl") or ""), downloadUrl=row.get("downloadUrl"), author=row.get("author"),
            licenseSpdx=license_id, licenseEvidenceUrl=evidence, tags=tuple(row.get("tags") or ()),
            mediaType=row.get("mediaType"), metadataConfidence=confidence, sourceVersion=row.get("sourceVersion"),
            licenseOptions=tuple(row.get("licenseOptions") or ()), credits=row.get("credits"))

    def row(self, external_id):
        """Ligne brute de l'index (champs propres au fournisseur : chemin, fichier de licence, crédits)."""
        self.inspect(external_id)
        location = self.index_location()
        data = json.loads(Path(location).read_text(encoding="utf-8")) if not re.match(r"https?://", location) else None
        for row in (data or {}).get("packs", []):
            if row.get("externalId") == external_id:
                return row
        raise KeyError(external_id)

    def search(self, query, filters):
        words = _terms(query)
        results = []
        for candidate in self.packs():
            text = _terms(" ".join((candidate.title, *candidate.tags, candidate.externalId)))
            if words and not words <= text:
                continue
            if filters.get("license") and filters["license"] not in (candidate.licenseSpdx, *candidate.licenseOptions):
                continue
            results.append(candidate)
        return results

    def inspect(self, external_id):
        for candidate in self.packs():
            if candidate.externalId == external_id:
                return candidate
        raise KeyError(external_id)

    def download(self, external_id, destination, manager):
        candidate = self.inspect(external_id)
        if not candidate.downloadUrl:
            raise ProviderUnavailable(f"{self.id}/{external_id} : aucune URL de téléchargement autorisée.")
        return manager.fetch(candidate.downloadUrl, destination)


class KenneyAdapter(IndexedProvider):
    pass


def providers(root):
    """Registre des fournisseurs (EXT-01, § 2) : P0 Kenney ; P1 OpenGameArt, LPC, itch.io ; P2 liste blanche."""
    from tools.external.sources import ItchioAdapter, LpcAdapter, OpenGameArtAdapter, WhitelistAdapter

    root = Path(root)
    return {
        "kenney": KenneyAdapter("kenney", "Import CC0 de packs dont la licence et la provenance sont vérifiées", "P0",
                                root),
        "opengameart": OpenGameArtAdapter(
            "opengameart", "Découverte ; import automatique uniquement pour licence confirmée et téléchargement "
            "autorisé", "P1", root),
        "lpc": LpcAdapter("lpc", "Référencement avec obligations de licence et d'attribution ; revue de compatibilité "
                          "CC BY-SA/GPL avant redistribution", "P1", root),
        "itchio": ItchioAdapter("itchio", "Découverte de packs explicitement licenciés ; respect des accès, API et "
                                "conditions de téléchargement", "P1", root),
        "whitelist": WhitelistAdapter("whitelist", "Adaptateurs sur liste blanche, ajout par PR avec revue de licence "
                                      "et sécurité", "P2", root),
    }


def search_all(root, query, filters, selected=None):
    """Recherche externe : statut par fournisseur ; une panne rend `unavailable`, jamais « rien n'existe »."""
    statuses, results = {}, []
    for name, adapter in providers(root).items():
        if selected and name != selected:
            continue
        try:
            found = adapter.search(query, filters)
        except NotHarvested as exc:
            statuses[name] = {"status": "not-harvested", "reason": str(exc)}
            continue
        except ProviderUnavailable as exc:
            statuses[name] = {"status": "unavailable", "reason": str(exc)}
            continue
        statuses[name] = {"status": "available", "results": len(found)}
        results.extend(found)
    states = {row["status"] for row in statuses.values()} - {"not-harvested"}
    overall = ("available" if states == {"available"} else "unavailable" if states <= {"unavailable"}
               else "partial")
    return overall, statuses, results
