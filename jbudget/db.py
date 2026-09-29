from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base
from .seed import seed

SessionLocal = sessionmaker(expire_on_commit=False)


def default_db_path() -> Path:
    return Path(os.environ.get("JBUDGET_DB") or Path.cwd() / "jbudget.db")


def init_db(path: str | Path | None = None) -> Path:
    """Ouvre (ou crée) la base SQLite et y place les catégories de départ si elle est vide."""
    p = Path(path) if path else default_db_path()
    engine = create_engine(f"sqlite:///{p}")
    SessionLocal.configure(bind=engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed(s)
        s.commit()
    return p


def new_session() -> Session:
    return SessionLocal()
