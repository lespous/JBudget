from pathlib import Path

import pytest

from jbudget import db as dbm

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def session(tmp_path):
    dbm.init_db(tmp_path / "test.db")
    with dbm.new_session() as s:
        yield s


@pytest.fixture
def ing_csv():
    files = sorted(DATA.glob("*.csv"))
    if not files:
        pytest.skip("aucun CSV ING dans data/")
    return files[0]


@pytest.fixture
def visa_pdf():
    files = sorted(DATA.glob("*.pdf"))
    if not files:
        pytest.skip("aucun PDF VISA dans data/")
    return files[0]
