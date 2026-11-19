"""Identités canoniques et allocation des identifiants en ajout seul."""

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping

SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
CATEGORY = r"[a-z][a-z0-9]*"
ID = re.compile(
    rf"(?P<prefix>(?:asset-{CATEGORY}-|sheet-)(?P<slug>{SLUG}))-(?P<number>[0-9]{{4}})"
)
SHA256 = r"[0-9a-f]{64}"
OFFSET = r"(?:0|[1-9][0-9]*)"
SIZE = r"[1-9][0-9]*"
REGION = re.compile(rf"region:(sheet-.+):{OFFSET},{OFFSET},{SIZE},{SIZE}")
DERIVED = re.compile(rf"derived:(asset-.+):{SHA256}")
LOGICAL = re.compile(rf"logical:{SLUG}:{SHA256}")
ALIAS = re.compile(rf"alias:({SLUG}):{SHA256}")
CODE = re.compile(r"code:([A-Za-z0-9_-][A-Za-z0-9_./-]*):([^#\\\x00-\x1f]+)#([^#\s]+)")


def parse_id(value):
    match = ID.fullmatch(value) if isinstance(value, str) else None
    if match and len(match["slug"]) <= 32 and match["number"] != "0000":
        return match
    return None


def _valid_identity(key):
    if not isinstance(key, str):
        return False
    if LOGICAL.fullmatch(key) or ALIAS.fullmatch(key):
        return True
    if re.fullmatch(rf"(?:(?:file|sheet):sha256:|file:source:{SHA256}:){SHA256}", key):
        return True
    for pattern in (REGION, DERIVED):
        if match := pattern.fullmatch(key):
            return parse_id(match[1]) is not None
    if match := CODE.fullmatch(key):
        return (
            not re.match(r"[A-Za-z]:", match[2])
            and all(part not in ("", ".", "..") for part in match[1].split("/") + match[2].split("/"))
        )
    return False


def verifier_registre(entries):
    if not isinstance(entries, Mapping):
        return ["Le registre doit associer les clés d’identité aux IDs."]
    errors = []
    primary_ids = []
    aliases = []
    for key, value in entries.items():
        if not _valid_identity(key):
            errors.append(f"Clé d’identité invalide : {key!r}")
        if parse_id(value):
            if isinstance(key, str) and (alias := ALIAS.fullmatch(key)):
                aliases.append((alias[1], value))
            else:
                primary_ids.append(value)
        else:
            errors.append(f"ID invalide : {value!r}")
    primaries = Counter(primary_ids)
    for (scope, value), count in Counter(aliases).items():
        if value not in primaries or count > 1:
            errors.append(f"Alias incohérent pour {value} dans le domaine {scope}.")
    for value, count in primaries.items():
        if count > 1:
            errors.append(f"ID attribué à plusieurs identités : {value}")
    return errors


def verifier_contre_base(ids_base, ids_tete):
    """Renvoie les violations des invariants d’ajout seul, ou une liste vide."""
    errors = verifier_registre(ids_base) + verifier_registre(ids_tete)
    if errors:
        return errors
    ids_restants = set(ids_tete.values())
    for key, value in ids_base.items():
        if key not in ids_tete:
            errors.append(f"Clé retirée : {key}")
        elif ids_tete[key] != value:
            errors.append(f"Clé réattribuée : {key} ({value} → {ids_tete[key]})")
        if value not in ids_restants:
            errors.append(f"ID retiré : {value}")
    return errors


class IdRegistry:
    """Registre en mémoire. Le propriétaire de l’écriture persiste le résultat."""

    def __init__(self, entries):
        if errors := verifier_registre(entries):
            raise ValueError("; ".join(errors))
        self._entries = dict(entries)
        self._primary = {value for key, value in entries.items() if not ALIAS.fullmatch(key)}
        self._alias_scopes = {(match[1], value) for key, value in entries.items() if (match := ALIAS.fullmatch(key))}
        self._last = {}
        for value in self._entries.values():
            parts = parse_id(value)
            prefix, number = parts["prefix"], int(parts["number"])
            self._last[prefix] = max(self._last.get(prefix, 0), number)

    def add_alias(self, key, value):
        match = ALIAS.fullmatch(key)
        if not match or value not in self._primary:
            raise ValueError("Alias d’identité invalide.")
        if self._entries.get(key) == value:
            return value
        scope = match[1], value
        if key in self._entries or scope in self._alias_scopes:
            raise ValueError("Alias d’identité déjà attribué.")
        self._entries[key] = value
        self._alias_scopes.add(scope)
        return value

    @property
    def entries(self):
        return dict(self._entries)

    def allouer(self, key, category, name):
        if not _valid_identity(key) or ALIAS.fullmatch(key):
            raise ValueError(f"Clé d’identité invalide : {key!r}")
        if key in self._entries:
            return self._entries[key]
        if not re.fullmatch(CATEGORY, category):
            raise ValueError(f"Catégorie invalide : {category!r}")
        ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:32].rstrip("-") or "sans-nom"
        prefix = f"sheet-{slug}" if category == "sheet" else f"asset-{category}-{slug}"
        number = self._last.get(prefix, 0) + 1
        if number > 9999:
            raise ValueError(f"Compteur épuisé : {prefix}")
        value = f"{prefix}-{number:04d}"
        self._last[prefix] = number
        self._entries[key] = value
        self._primary.add(value)
        return value
