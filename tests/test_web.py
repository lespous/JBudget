import io

import pytest
from sqlalchemy import select

from jbudget import db as dbm
from jbudget.models import Category, Rule, Transaction
from jbudget.web import create_app


@pytest.fixture
def client(tmp_path, ing_csv, visa_pdf):
    app = create_app(tmp_path / "web.db")
    app.config["TESTING"] = True
    c = app.test_client()
    files = [(io.BytesIO(p.read_bytes()), p.name) for p in (ing_csv, visa_pdf)]
    r = c.post("/import", data={"files": files}, content_type="multipart/form-data")
    assert r.status_code == 200
    return c


def test_pages_render(client):
    for url in ["/", "/?month=2026-03", "/transactions", "/transactions?month=all&dir=out&q=colruyt",
                "/rules", "/rules?edit=1", "/categories", "/import",
                "/rules/test?field=merchant&match_type=contains&pattern=colruyt&category_id=1"]:
        assert client.get(url).status_code == 200, url


def test_recategorize_with_learned_rule(client):
    with dbm.new_session() as s:
        tx = s.scalar(select(Transaction).join(Transaction.category)
                      .where(Category.kind == "todo", Transaction.merchant != "", Transaction.amount_cents < 0))
        resto = s.scalar(select(Category).where(Category.name == "Restaurants"))
        tx_id, cat_id, merchant = tx.id, resto.id, tx.merchant

    r = client.get(f"/tx/{tx_id}/recat?category_id={cat_id}", headers={"Referer": "/transactions"})
    assert r.status_code == 200 and b"Restaurants" in r.data
    r = client.post(f"/tx/{tx_id}/recat", data={"category_id": cat_id, "scope": "merchant", "next": "/transactions"})
    assert r.status_code == 302

    with dbm.new_session() as s:
        cats = set(s.scalars(select(Transaction.category_id).where(Transaction.merchant == merchant,
                                                                   Transaction.amount_cents < 0)))
        assert cats == {cat_id}
        rule = s.scalar(select(Rule).where(Rule.pattern == merchant))
        assert rule.origin == "learned"


def test_bad_regex_is_rejected(client):
    r = client.post("/rules/save", data={"field": "label", "match_type": "regex", "pattern": "(",
                                         "category_id": 1}, follow_redirects=True)
    assert "Expression régulière invalide".encode() in r.data
