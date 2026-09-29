"""Relevé mensuel VISA ING / Worldline au format PDF."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pdfplumber

from ..normalize import merchant_from_visa, parse_amount
from . import ParseError, ParsedTx, assign_fingerprints

PERIOD_RE = re.compile(r"Transactions du (\d{2}/\d{2}/\d{4}) au (\d{2}/\d{2}/\d{4})")
CARD_RE = re.compile(r"Num\.carte : ([\dX-]+)")
LINE_RE = re.compile(r"^(\d{2})/(\d{2}) (\d{2})/(\d{2}) (.+?) ([\d.]+,\d{2})([+-])$")
# Lignes de solde : le paiement du relevé par le compte à vue n'est pas une dépense.
SKIP = ("DOMICILIATION AUPRES DE VOTRE BANQUE",)


def _infer(day: str, month: str, end: date) -> date:
    """Les lignes n'ont pas d'année : on prend celle qui place la date avant la fin de période."""
    d = date(end.year, int(month), int(day))
    return date(end.year - 1, int(month), int(day)) if d > end + timedelta(days=7) else d


def parse(path: Path) -> list[ParsedTx]:
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    period = PERIOD_RE.search(text)
    if not period:
        raise ParseError(f"{path.name} : période introuvable, ce n'est pas un relevé VISA ING")
    end = datetime.strptime(period[2], "%d/%m/%Y").date()

    card = None
    items: list[ParsedTx] = []
    for line in text.splitlines():
        line = " ".join(line.split())
        if m := CARD_RE.search(line):
            card = m[1]
            continue
        m = LINE_RE.match(line)
        if not m or any(s in m[5].upper() for s in SKIP):
            continue
        if card is None:
            raise ParseError(f"{path.name} : numéro de carte introuvable avant les transactions")
        cents = parse_amount(m[6])
        items.append(
            ParsedTx(
                account_number=card,
                account_name=f"VISA …{card[-4:]}",
                account_kind="card",
                date=_infer(m[1], m[2], end),
                value_date=_infer(m[3], m[4], end),
                amount_cents=-cents if m[7] == "-" else cents,
                description=m[5],
                details=f"Relevé VISA {period[1]} – {period[2]}",
                merchant=merchant_from_visa(m[5]),
            )
        )

    assign_fingerprints(
        items,
        "visa",
        lambda it: (it.account_number, it.date, it.value_date, it.amount_cents, it.description),
    )
    return items
