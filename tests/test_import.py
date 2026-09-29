import re

import pdfplumber
from sqlalchemy import func, select

from jbudget.classifier import Classifier, reclassify
from jbudget.importer import import_file
from jbudget.models import Category, Rule, Transaction
from jbudget.normalize import parse_amount
from jbudget.parsers import visa_pdf as visa_parser


def test_visa_statement_total_matches_new_balance(visa_pdf):
    rows = visa_parser.parse(visa_pdf)
    with pdfplumber.open(visa_pdf) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    new_balance = re.search(r"Nouveau Solde ([\d.]+,\d{2})-", text)[1]
    # Le relevé part d'un solde remboursé : la somme des achats vaut le nouveau solde.
    assert rows and sum(r.amount_cents for r in rows) == -parse_amount(new_balance)


def test_import_is_idempotent(session, ing_csv):
    first = import_file(session, ing_csv)
    second = import_file(session, ing_csv)
    assert first.added > 0 and first.skipped == 0
    assert second.added == 0 and second.skipped == first.added


def test_visa_payment_is_neutral_transfer(session, ing_csv):
    import_file(session, ing_csv)
    kinds = {
        tx.category.kind
        for tx in session.scalars(select(Transaction).where(Transaction.description.like("Paiement ING : VISA%")))
    }
    assert kinds == {"transfer"}


def test_zero_amount_lines_are_ignored(session, ing_csv):
    import_file(session, ing_csv)
    zero = session.scalars(select(Transaction).where(Transaction.amount_cents == 0)).all()
    assert all(t.category.kind == "ignore" for t in zero)


def _first_todo(session):
    return session.scalar(
        select(Transaction).join(Transaction.category).where(Category.kind == "todo", Transaction.merchant != "")
    )


def test_correction_is_remembered_for_next_import(session, ing_csv, visa_pdf):
    import_file(session, ing_csv)
    import_file(session, visa_pdf)
    tx = _first_todo(session)
    snacks = session.scalar(select(Category).where(Category.name == "Snacks & cafés"))

    tx.category_id, tx.locked, tx.source = snacks.id, True, "manual"
    session.commit()
    clone = Transaction(**{c: getattr(tx, c) for c in ("account_id", "date", "amount_cents", "description", "merchant")},
                        fingerprint="x" * 40)
    Classifier(session).apply(clone)
    assert clone.category_id == snacks.id and clone.source == "memory"


def test_learned_rule_beats_seed_rule(session, ing_csv):
    import_file(session, ing_csv)
    tx = session.scalar(select(Transaction).where(Transaction.merchant.like("%COLRUYT%")))
    resto = session.scalar(select(Category).where(Category.name == "Restaurants"))
    session.add(Rule(field="merchant", match_type="equals", pattern=tx.merchant, category_id=resto.id,
                     direction="out", priority=200, origin="learned"))
    reclassify(session)
    cats = set(session.scalars(select(Transaction.category_id).where(Transaction.merchant == tx.merchant,
                                                                     Transaction.amount_cents < 0)))
    assert cats == {resto.id}


def test_locked_transactions_survive_reclassify(session, ing_csv):
    import_file(session, ing_csv)
    tx = session.scalar(select(Transaction).where(Transaction.merchant.like("%COLRUYT%")))
    divers = session.scalar(select(Category).where(Category.name == "Divers"))
    tx.category_id, tx.locked = divers.id, True
    reclassify(session)
    assert tx.category_id == divers.id


def test_most_lines_are_classified(session, ing_csv, visa_pdf):
    import_file(session, ing_csv)
    import_file(session, visa_pdf)
    total = session.scalar(select(func.count(Transaction.id)))
    todo = session.scalar(select(func.count(Transaction.id)).join(Transaction.category).where(Category.kind == "todo"))
    assert todo / total < 0.5
