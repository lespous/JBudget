from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Nature d'une catégorie : détermine comment elle compte dans les statistiques.
KIND_EXPENSE = "expense"
KIND_INCOME = "income"
KIND_SAVINGS = "savings"
KIND_TRANSFER = "transfer"
KIND_TODO = "todo"
KIND_IGNORE = "ignore"

KINDS = {
    KIND_EXPENSE: "Dépense",
    KIND_INCOME: "Rentrée",
    KIND_SAVINGS: "Épargne",
    KIND_TRANSFER: "Transfert (hors stats)",
    KIND_TODO: "À classer",
    KIND_IGNORE: "Ignoré",
}


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10))  # bank | card

    @property
    def short(self) -> str:
        return "VISA" if self.kind == "card" else "ING"


class ImportBatch(Base):
    __tablename__ = "imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(20))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    added: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)


class CategoryGroup(Base):
    __tablename__ = "category_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    categories: Mapped[list[Category]] = relationship(
        back_populates="group", order_by="(Category.position, Category.name)"
    )


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("group_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("category_groups.id"))
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10), default=KIND_EXPENSE)
    budget_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    group: Mapped[CategoryGroup] = relationship(back_populates="categories")

    @property
    def label(self) -> str:
        return f"{self.group.name} › {self.name}"


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    field: Mapped[str] = mapped_column(String(20))  # merchant | label | counterparty
    match_type: Mapped[str] = mapped_column(String(20))  # contains | startswith | equals | regex
    pattern: Mapped[str] = mapped_column(String(255))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    origin: Mapped[str] = mapped_column(String(10), default="manual")  # seed | learned | manual
    direction: Mapped[str | None] = mapped_column(String(3), nullable=True)  # in | out
    min_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    category: Mapped[Category] = relationship()


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    import_id: Mapped[int | None] = mapped_column(ForeignKey("imports.id"), nullable=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    details: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text, default="")
    counterparty_iban: Mapped[str | None] = mapped_column(String(40), nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    merchant: Mapped[str] = mapped_column(String(200), default="", index=True)
    fingerprint: Mapped[str] = mapped_column(String(40), unique=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    # rule | memory | manual | system | none
    source: Mapped[str] = mapped_column(String(10), default="none")
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id"), nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)

    account: Mapped[Account] = relationship()
    category: Mapped[Category | None] = relationship()
    rule: Mapped[Rule | None] = relationship()
