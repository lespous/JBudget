"""Nettoyage des libellés : extraction d'une clé marchand stable."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def fold(s: str | None) -> str:
    """Forme de comparaison : sans accents, minuscules, espaces simples."""
    return re.sub(r"\s+", " ", strip_accents(s or "")).strip().casefold()


def parse_amount(raw: str) -> int:
    """'-1.234,56' ou '2.078,15' -> centimes (int)."""
    s = raw.strip().replace(" ", "").replace(".", "").replace(",", ".")
    return int((Decimal(s) * 100).to_integral_value())


IBAN = r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}"

TRANSFER_RE = re.compile(r"(?:Vers|De): (?P<m>.+) - (?P<iban>" + IBAN + r")\b")

_CARD_RE = re.compile(
    r"^(?:Paiement (?:carburant )?(?:Bancontact|Debit Mastercard)"
    r"|Retrait d'esp[eè]ces (?:Bancontact|Debit Mastercard)"
    r"|P2P Mobile - Transfert Bancontact)"
    r" \d{2}/\d{2}/\d{2} - \d{1,2}h\d{2} - "
    r"(?P<m>.+?)(?: - .+? - [A-Z]{3}(?=\s|$)| Num[eé]ro de carte|$)"
)
_DOMI_RE = re.compile(r"^Domiciliation en euros \(SEPA\) (?P<m>.+?)(?: Avis en annexe|$)")
_FIXED = [
    (re.compile(r"^Paiement ING : VISA"), "ING VISA"),
    (re.compile(r"^(?:Vers|De) ING Compte d'investissement"), "ING COMPTE D'INVESTISSEMENT"),
    (re.compile(r"^D[ée]compte de frais"), "ING FRAIS BANCAIRES"),
    (re.compile(r"^Int[ée]r[êe]ts-Frais"), "ING INTERETS"),
    (re.compile(r"^CREDIT HYPOTHECAIRE"), "CREDIT HYPOTHECAIRE"),
    (re.compile(r"^Prime d'assurance"), "PRIME D'ASSURANCE"),
]
# Références techniques : mélange lettres + chiffres, au moins 6 caractères (WJ2QM71D5, P4655583B).
_REF_RE = re.compile(r"^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9]{6,}$")


def clean_merchant(raw: str) -> str:
    """Retire numéros de magasin, codes postaux et références, met en majuscules."""
    tokens = [t for t in raw.split() if not (t.isdigit() or _REF_RE.match(t))]
    return " ".join(tokens).upper().strip(" -*")


def merchant_from_ing(label: str) -> str:
    label = re.sub(r"\s+", " ", label or "").strip()
    for rx, name in _FIXED:
        if rx.match(label):
            return name
    for rx in (_CARD_RE, _DOMI_RE):
        if m := rx.match(label):
            return clean_merchant(m["m"]) or m["m"].upper()
    if m := TRANSFER_RE.search(label):
        return clean_merchant(m["m"])
    return clean_merchant(" ".join(label.split()[:5]))


def merchant_from_visa(description: str) -> str:
    return clean_merchant(description)
