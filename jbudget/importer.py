from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .classifier import Classifier
from .models import Account, ImportBatch, Transaction
from .parsers import parse_file


@dataclass
class ImportResult:
    filename: str
    source: str
    added: int
    skipped: int
    todo: int


def import_file(session: Session, path: Path, display_name: str | None = None) -> ImportResult:
    """Importe un fichier ; les lignes déjà présentes (même empreinte) sont ignorées."""
    source, items = parse_file(path)
    clf = Classifier(session)
    batch = ImportBatch(filename=display_name or path.name, source=source)
    session.add(batch)
    session.flush()

    known = set(session.scalars(select(Transaction.fingerprint)))
    accounts = {a.number: a for a in session.scalars(select(Account))}
    added = skipped = todo = 0
    for it in items:
        if it.fingerprint in known:
            skipped += 1
            continue
        known.add(it.fingerprint)
        account = accounts.get(it.account_number)
        if account is None:
            account = Account(number=it.account_number, name=it.account_name, kind=it.account_kind)
            session.add(account)
            session.flush()
            accounts[it.account_number] = account
        tx = Transaction(
            account_id=account.id,
            import_id=batch.id,
            date=it.date,
            value_date=it.value_date,
            amount_cents=it.amount_cents,
            description=it.description,
            details=it.details,
            message=it.message,
            counterparty_iban=it.counterparty_iban,
            counterparty_name=it.counterparty_name,
            merchant=it.merchant,
            fingerprint=it.fingerprint,
        )
        clf.apply(tx)
        session.add(tx)
        added += 1
        todo += tx.category_id == clf.todo_id

    batch.added, batch.skipped = added, skipped
    session.commit()
    return ImportResult(batch.filename, source, added, skipped, todo)
