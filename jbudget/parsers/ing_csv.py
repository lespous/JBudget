"""Export CSV des mouvements ING Belgique (séparateur ';', montants '-39,10')."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path

from ..normalize import TRANSFER_RE, merchant_from_ing, parse_amount
from . import ParseError, ParsedTx, assign_fingerprints

REQUIRED = ("Numéro de compte", "Date comptable", "Montant", "Libellés")


def _read_text(path: Path) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ParseError(f"{path.name} : encodage illisible")


def _date(raw: str | None) -> date | None:
    raw = (raw or "").strip()
    return datetime.strptime(raw, "%d/%m/%Y").date() if raw else None


def _squash(s: str | None) -> str:
    return " ".join((s or "").split())


def parse(path: Path) -> list[ParsedTx]:
    reader = csv.DictReader(io.StringIO(_read_text(path)), delimiter=";")
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise ParseError(f"{path.name} : colonnes manquantes {missing}, ce n'est pas un export ING")

    items: list[ParsedTx] = []
    numbers: list[str] = []
    for row in reader:
        label = _squash(row["Libellés"])
        m = TRANSFER_RE.search(label)
        items.append(
            ParsedTx(
                account_number=row["Numéro de compte"].strip(),
                account_name=_squash(row.get("Nom du compte")) or "Compte ING",
                account_kind="bank",
                date=_date(row["Date comptable"]),
                value_date=_date(row.get("Date valeur")),
                amount_cents=parse_amount(row["Montant"]),
                description=label,
                details=_squash(row.get("Détails du mouvement")),
                message=_squash(row.get("Message")),
                counterparty_iban=(row.get("Compte contrepartie") or "").strip() or None,
                counterparty_name=m["m"].strip() if m else None,
                merchant=merchant_from_ing(label),
            )
        )
        numbers.append((row.get("Numéro de mouvement") or "").strip())

    num_of = {id(it): n for it, n in zip(items, numbers)}
    assign_fingerprints(
        items,
        "ing",
        lambda it: (it.account_number, num_of[id(it)], it.date, it.amount_cents, it.description),
    )
    return items
