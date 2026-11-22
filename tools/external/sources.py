"""Adaptateurs P1/P2 d'EXT-001 (§ 2, § 10 EXT-08 à EXT-11) : OpenGameArt, LPC, itch.io et sources sur liste blanche.

Chaque fournisseur sait **collecter** (`harvest`) son index de packs depuis le site public, par le client générique
(tools/external/client.py : robots.txt respecté pour le registre et pour les agents IA qui le pilotent, aucune
donnée personnelle, aucun jeton). L'index collecté est le même ExternalIndex que celui de Kenney : `search`,
`inspect`, `plan-import`, `import`, `sync` n'ont rien de particulier à un fournisseur.

Licences : jamais présumées. Une licence n'est `verified` qu'après lecture de son texte (licenses.py). Les licences
mixtes (un fichier offert sous plusieurs licences au choix) sont conservées en `licenseOptions` ; la vérification
retient la moins contraignante que le texte confirme.
"""

import csv
import hashlib
import html
import io
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from tools.external.adapters import EXTERNAL_ID, IndexedProvider, ProviderUnavailable, _terms

# Libellés des sources → SPDX. Un libellé absent de la table reste tel quel (non pris en charge = `unknown`).
LABELS = {
    "cc0": "CC0-1.0", "cc0 1.0": "CC0-1.0", "public domain cc0": "CC0-1.0",
    "cc-by 4.0": "CC-BY-4.0", "cc-by 3.0": "CC-BY-3.0", "cc by 4.0": "CC-BY-4.0", "cc by 3.0": "CC-BY-3.0",
    "cc-by-sa 4.0": "CC-BY-SA-4.0", "cc-by-sa 3.0": "CC-BY-SA-3.0", "cc by-sa 4.0": "CC-BY-SA-4.0",
    "cc by-sa 3.0": "CC-BY-SA-3.0", "oga-by 3.0": "LicenseRef-OGA-BY-3.0",
    "gpl 3.0": "GPL-3.0-only", "gpl 2.0": "GPL-2.0-only", "mit": "MIT", "ofl 1.1": "OFL-1.1",
}
# Ordre de préférence entre licences offertes au choix : la moins contraignante d'abord.
PREFERENCE = ("CC0-1.0", "MIT", "CC-BY-4.0", "CC-BY-3.0", "LicenseRef-OGA-BY-3.0", "OFL-1.1", "CC-BY-SA-4.0",
              "CC-BY-SA-3.0", "GPL-3.0-only", "GPL-2.0-only")
MEDIA = re.compile(r"(?i)\.(png|webp|gif|jpe?g|svg|ogg|wav|mp3|ttf|otf|tmx|tsx|json)$")


def spdx(label):
    key = re.sub(r"\s+", " ", str(label).strip().casefold().replace("_", " "))
    return LABELS.get(key, LABELS.get(key.replace("-", " ").replace("cc by sa", "cc by-sa"), str(label).strip()))


def ordered(options):
    unique = list(dict.fromkeys(o for o in options if o))
    return sorted(unique, key=lambda o: PREFERENCE.index(o) if o in PREFERENCE else len(PREFERENCE))


def slug_id(text):
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-.")
    if len(value) > 128:
        value = value[:111] + "-" + hashlib.sha256(str(text).encode()).hexdigest()[:16]
    if not EXTERNAL_ID.fullmatch(value):
        raise ProviderUnavailable(f"identifiant externe inutilisable : {text!r}")
    return value


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _matches(query, *fields):
    words = _terms(query)
    return not words or words <= _terms(" ".join(str(f) for f in fields))


class HarvestingProvider(IndexedProvider):
    """Fournisseur dont l'index se collecte sur le site public (EXT-11 : incrémental)."""

    def harvest(self, client, query, previous=None):
        raise NotImplementedError

    def write_index(self, rows, source, previous=None):
        """Index du fournisseur : jamais de jeton (vérifié à la relecture par IndexedProvider.candidate)."""
        index = {"provider": self.id, "harvestedAt": _now(), "source": source,
                 "packs": sorted(rows, key=lambda r: r["externalId"])}
        for row in index["packs"]:
            self.candidate(row)
        return index


# --- OpenGameArt (EXT-08) ----------------------------------------------------------------------------------------

class _OgaPage(HTMLParser):
    """Champs d'une page « content » d'OpenGameArt (Drupal) : titre, auteur, licences, fichiers, étiquettes."""

    def __init__(self):
        super().__init__()
        self.stack, self.field, self.title, self.author = [], None, "", None
        self.licenses, self.files, self.tags, self._text = [], [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "") or ""
        match = re.search(r"field-name-([\w-]+)", classes)
        if match:
            self.field = match.group(1)
        if tag == "a" and self.field in ("field-art-files",) and attrs.get("href"):
            self.files.append(attrs["href"])
        if tag == "a" and self.field in ("author-submitter",) and not self.author:
            self._text = ["@author"]
        if tag == "a" and self.field in ("field-art-tags",):
            self._text = ["@tag"]
        if "license-name" in classes:
            self._text = ["@license"]
        if tag == "h1" or (tag == "div" and "field-name-title" in classes):
            self._text = ["@title"]
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if self._text and self._text[0].startswith("@"):
            kind, text = self._text[0], html.unescape("".join(self._text[1:])).strip()
            if text:
                if kind == "@license":
                    self.licenses.append(text)
                elif kind == "@author" and not self.author:
                    self.author = text
                elif kind == "@tag":
                    self.tags.append(text)
                elif kind == "@title" and not self.title:
                    self.title = text
                self._text = []
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if self._text:
            self._text.append(data)


def parse_oga_page(text, url):
    page = _OgaPage()
    page.feed(text)
    options = ordered(spdx(label) for label in page.licenses)
    slug = urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    files = [urllib.parse.urljoin(url, f) for f in page.files]
    archive = next((f for f in files if f.lower().endswith(".zip")), files[0] if files else None)
    return {"externalId": slug_id(slug), "title": page.title or slug, "sourceUrl": url, "downloadUrl": archive,
            "author": page.author, "licenseSpdx": options[0] if options else None, "licenseOptions": options,
            "licenseEvidenceUrl": url if options else None, "tags": sorted(set(page.tags)),
            # Une licence lue sur la page n'est qu'annoncée : la preuve reste le texte dans l'archive.
            "metadataConfidence": "inferred" if options else "unknown", "files": files}


class OpenGameArtAdapter(HarvestingProvider):
    """Découverte ; import automatique uniquement pour licence confirmée et téléchargement autorisé (§ 2)."""

    def harvest(self, client, query, previous=None, pages=()):
        pages = list(pages)
        if not pages:
            # Résultats de recherche publics : liens vers les pages « content » (20 au plus par collecte).
            _, body, _ = client.get(f"https://opengameart.org/art-search-advanced?keys={urllib.parse.quote(query)}")
            links = re.findall(r'href="(/content/[a-z0-9-]+)"', body.decode("utf-8", errors="replace"))
            pages = [f"https://opengameart.org{link}" for link in dict.fromkeys(links)][:20]
        rows = []
        for url in pages:
            _, body, headers = client.get(url)
            row = parse_oga_page(body.decode("utf-8", errors="replace"), url)
            row["sourceVersion"] = headers.get("Last-Modified") or hashlib.sha256(body).hexdigest()[:16]
            rows.append(row)
        return self.write_index(rows, {"pages": pages}, previous)


# --- Liberated Pixel Cup (EXT-09) --------------------------------------------------------------------------------

LPC_REPO = "LiberatedPixelCup/Universal-LPC-Spritesheet-Character-Generator"


def parse_lpc_credits(text, repo, ref):
    """CREDITS.csv du générateur LPC : licences au choix, auteurs et URL d'origine PAR FICHIER (obligations)."""
    rows = []
    for line in csv.DictReader(io.StringIO(text), skipinitialspace=True):
        name = (line.get("filename") or "").strip()
        if not name or not MEDIA.search(name):
            continue
        options = ordered(spdx(x) for x in (line.get("licenses") or "").split(",") if x.strip())
        authors = [a.strip() for a in (line.get("authors") or "").split(",") if a.strip()]
        urls = [u.strip() for u in (line.get("urls") or "").split(",") if u.strip()]
        rows.append({
            "externalId": slug_id(name.replace("/", "-")), "title": name, "path": f"spritesheets/{name}",
            "sourceUrl": f"https://github.com/{repo}/blob/{ref}/spritesheets/{name}",
            "downloadUrl": f"https://raw.githubusercontent.com/{repo}/{ref}/spritesheets/{name}",
            "author": ", ".join(authors) or None, "licenseSpdx": options[0] if options else None,
            "licenseOptions": options, "licenseEvidenceUrl": f"https://raw.githubusercontent.com/{repo}/{ref}/CREDITS.csv",
            "tags": sorted({"lpc", *re.findall(r"[a-z0-9]+", name.casefold().rsplit(".", 1)[0])} - {"png"}),
            "mediaType": "image/png" if name.lower().endswith(".png") else None,
            "metadataConfidence": "inferred" if options else "unknown", "sourceVersion": ref,
            "credits": {"authors": authors, "urls": urls, "notes": (line.get("notes") or "").strip()},
            "obligations": ["attribution de chaque auteur listé", "licences au choix : " + ", ".join(options),
                            "partage à l'identique si une licence SA/GPL est retenue"]})
    return rows


class LpcAdapter(HarvestingProvider):
    """Référencement avec obligations de licence et d'attribution, PAR FICHIER (§ 2)."""

    def harvest(self, client, query, previous=None, repo=LPC_REPO, ref=None):
        if not ref:
            _, body, _ = client.get(f"https://api.github.com/repos/{repo}/commits/HEAD")
            ref = json.loads(body)["sha"]
        if previous and previous.get("source", {}).get("ref") == ref:
            return previous
        _, body, _ = client.get(f"https://raw.githubusercontent.com/{repo}/{ref}/CREDITS.csv")
        rows = [r for r in parse_lpc_credits(body.decode("utf-8"), repo, ref) if _matches(query, r["title"], *r["tags"])]
        return self.write_index(rows, {"repo": repo, "ref": ref}, previous)

    def download(self, external_id, destination, manager):
        """Paquet reconstitué : le fichier ET l'extrait de CREDITS.csv qui en porte la licence (la preuve)."""
        row = self.row(external_id)
        return _bundle(manager, destination, {Path(row["path"]).name: row["downloadUrl"]},
                       "LICENSE-LPC.txt", _lpc_license_text(row))


def _lpc_license_text(row):
    credits = row.get("credits") or {}
    return ("Extrait de CREDITS.csv (Universal LPC Spritesheet Character Generator), au commit "
            f"{row['sourceVersion']} :\n\nfichier : {row['title']}\nlicences (au choix) : "
            + ", ".join(row.get("licenseOptions") or []) + "\nauteurs : " + ", ".join(credits.get("authors") or [])
            + "\nsources : " + ", ".join(credits.get("urls") or []) + f"\nnotes : {credits.get('notes', '')}\n"
            f"preuve : {row['licenseEvidenceUrl']}\n")


# --- itch.io (EXT-10) --------------------------------------------------------------------------------------------

def parse_itch_feed(text, feed_url):
    """Flux RSS public d'itch.io : découverte seule. L'étiquette « cc0 » est celle de l'auteur, pas une preuve."""
    root = ET.fromstring(text)
    tag = urllib.parse.urlsplit(feed_url).path.rsplit("tag-", 1)[-1].removesuffix(".xml") if "tag-" in feed_url else None
    rows = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        parts = urllib.parse.urlsplit(link)
        if parts.scheme != "https" or not parts.netloc.endswith(".itch.io"):
            continue
        creator = parts.netloc.removesuffix(".itch.io")
        title = (item.findtext("plainTitle") or item.findtext("title") or "").strip()
        rows.append({"externalId": slug_id(f"{creator}-{parts.path.strip('/')}"), "title": title, "sourceUrl": link,
                     "downloadUrl": None, "author": creator, "licenseSpdx": None, "licenseEvidenceUrl": None,
                     "tags": sorted({*(f"etiquette-auteur-{tag}",) * bool(tag), *_terms(title)}),
                     "metadataConfidence": "unknown",
                     "sourceVersion": (item.findtext("updateDate") or item.findtext("pubDate") or "").strip() or None,
                     "price": (item.findtext("price") or "").strip()})
    return rows


class ItchioAdapter(HarvestingProvider):
    """Packs explicitement licenciés ; accès, API et conditions de téléchargement respectés (§ 2) : le
    téléchargement passe par /game/download/, fermé aux robots — il reste un geste humain."""

    def harvest(self, client, query, previous=None, feeds=()):
        feeds = list(feeds) or [f"https://itch.io/game-assets/free/tag-{slug}.xml" for slug in
                                (re.sub(r"[^a-z0-9]+", "-", query.casefold()).strip("-") or "cc0",)]
        known = (previous or {}).get("source", {}).get("etags", {}) if isinstance((previous or {}).get("source"),
                                                                                 dict) else {}
        old_rows = (previous or {}).get("packs", [])
        rows, seen, etags = [], set(), {}
        for feed in feeds:
            status, body, headers = client.get(feed, etag=(known.get(feed) or {}).get("etag"),
                                               modified=(known.get(feed) or {}).get("lastModified"))
            if status == 304:
                # Requête conditionnelle : le flux n'a pas changé, ses lignes sont reprises telles quelles.
                found = [r for r in old_rows if r.get("feed") == feed]
                etags[feed] = known[feed]
            else:
                found = [{**r, "feed": feed} for r in parse_itch_feed(body.decode("utf-8", errors="replace"), feed)]
                etags[feed] = {"etag": headers.get("ETag"), "lastModified": headers.get("Last-Modified")}
            for row in found:
                if row["externalId"] not in seen:
                    seen.add(row["externalId"])
                    rows.append(row)
        return self.write_index(rows, {"feeds": feeds, "etags": etags}, previous)


# --- Liste blanche (P2) ------------------------------------------------------------------------------------------

REVIEW = ("licence", "securite", "par", "date", "pr")


def whitelist(root):
    path = Path(root) / "external" / "whitelist.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = []
    for entry in data.get("sources", []):
        review = entry.get("review") or {}
        if entry.get("kind") != "github-repo" or not re.fullmatch(r"[0-9a-f]{40}", str(entry.get("ref", ""))):
            raise ProviderUnavailable(f"liste blanche : {entry.get('id')} doit être un dépôt GitHub à un commit figé")
        missing = [k for k in REVIEW if not str(review.get(k, "")).strip()]
        if missing:
            raise ProviderUnavailable(f"liste blanche : {entry.get('id')} sans revue ({', '.join(missing)})")
        sources.append(entry)
    return sources


class WhitelistAdapter(HarvestingProvider):
    """Autres sources (P2) : seulement celles de external/whitelist.json, ajoutées par PR avec revue de licence et de
    sécurité ; la licence se prouve par le fichier de licence du dépôt, au même commit."""

    def harvest(self, client, query, previous=None):
        rows = []
        for entry in whitelist(self.root):
            repo, ref = entry["repo"], entry["ref"]
            _, body, _ = client.get(f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1")
            tree = json.loads(body)
            pattern = re.compile(entry.get("paths", r".*"))
            for node in tree.get("tree", []):
                path = node.get("path", "")
                if node.get("type") != "blob" or not MEDIA.search(path) or not pattern.search(path):
                    continue
                if not _matches(query, path):
                    continue
                rows.append({"externalId": slug_id(f"{entry['id']}-{path.replace('/', '-')}"), "title": path,
                             "path": path, "source": entry["id"],
                             "sourceUrl": f"https://github.com/{repo}/blob/{ref}/{path}",
                             "downloadUrl": f"https://raw.githubusercontent.com/{repo}/{ref}/{path}",
                             "author": entry.get("author"), "licenseSpdx": entry["license"],
                             "licenseOptions": [entry["license"]],
                             "licenseEvidenceUrl": f"https://raw.githubusercontent.com/{repo}/{ref}/{entry['licenseFile']}",
                             "licenseFile": entry["licenseFile"], "tags": sorted(_terms(path)),
                             "metadataConfidence": "inferred", "sourceVersion": ref})
        return self.write_index(rows, {"whitelist": [e["id"] for e in whitelist(self.root)]}, previous)

    def download(self, external_id, destination, manager):
        row = self.row(external_id)
        return _bundle(manager, destination, {Path(row["path"]).name: row["downloadUrl"],
                                              Path(row["licenseFile"]).name: row["licenseEvidenceUrl"]})


def _bundle(manager, destination, files, extra_name=None, extra_text=None):
    """Archive locale reconstituée depuis des fichiers bruts (même bornes et empreintes que DownloadManager)."""
    destination = Path(destination)
    folder = destination.parent
    buffer = io.BytesIO()
    metas = {}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name, url in files.items():
            part = folder / f"part-{hashlib.sha256(url.encode()).hexdigest()[:12]}"
            metas[name] = manager.fetch(url, part)
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            zipped.writestr(info, part.read_bytes())
            part.unlink()
        if extra_name:
            zipped.writestr(zipfile.ZipInfo(extra_name, date_time=(1980, 1, 1, 0, 0, 0)), extra_text)
    raw = buffer.getvalue()
    destination.write_bytes(raw)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "etag": None, "lastModified": None,
            "parts": {name: meta["sha256"] for name, meta in metas.items()}}
