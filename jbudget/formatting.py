from __future__ import annotations

from decimal import Decimal, InvalidOperation

NBSP = " "


def money(cents: int | None, signed: bool = True) -> str:
    """1234,5 € au format belge : « −1 234,50 € »."""
    if cents is None:
        return ""
    whole = f"{abs(cents) / 100:,.2f}".replace(",", NBSP).replace(".", ",")
    prefix = "−" if cents < 0 else ("+" if signed and cents > 0 else "")
    return f"{prefix}{whole} €"


def parse_euros(raw: str | None) -> int | None:
    """« 12,50 » ou « 12.5 » -> 1250 ; vide -> None."""
    raw = (raw or "").strip().replace(" ", "").replace(",", ".")
    if not raw:
        return None
    try:
        return int((Decimal(raw) * 100).to_integral_value())
    except InvalidOperation:
        raise ValueError(f"montant invalide : {raw}")
