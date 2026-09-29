from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class ParsedTx:
    account_number: str
    account_name: str
    account_kind: str  # bank | card
    date: date
    amount_cents: int
    description: str
    merchant: str
    value_date: date | None = None
    details: str = ""
    message: str = ""
    counterparty_iban: str | None = None
    counterparty_name: str | None = None
    fingerprint: str = field(default="")


class ParseError(ValueError):
    pass


def assign_fingerprints(items: list[ParsedTx], prefix: str, keys) -> None:
    """Empreinte stable ; un compteur distingue les lignes identiques d'un même fichier."""
    seen: Counter[str] = Counter()
    for it in items:
        base = "|".join([prefix, *map(str, keys(it))])
        seen[base] += 1
        it.fingerprint = hashlib.sha1(f"{base}|{seen[base]}".encode()).hexdigest()


def parse_file(path: Path) -> tuple[str, list[ParsedTx]]:
    """Détecte le format d'après l'extension et renvoie (source, transactions)."""
    from . import ing_csv, visa_pdf

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "ing_csv", ing_csv.parse(path)
    if suffix == ".pdf":
        return "visa_pdf", visa_pdf.parse(path)
    raise ParseError(f"{path.name} : format non reconnu (attendu .csv ING ou .pdf VISA)")
