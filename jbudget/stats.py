"""Agrégats mensuels partagés par le tableau de bord et la CLI."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .models import (
    KIND_EXPENSE,
    KIND_INCOME,
    KIND_SAVINGS,
    KIND_TODO,
    KIND_TRANSFER,
    Category,
    CategoryGroup,
    Transaction,
)

MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def month_label(ym: str) -> str:
    y, m = map(int, ym.split("-"))
    return f"{MONTHS_FR[m - 1]} {y}"


def month_bounds(ym: str) -> tuple[date, date]:
    y, m = map(int, ym.split("-"))
    return date(y, m, 1), date(y + m // 12, m % 12 + 1, 1)


def add_months(ym: str, n: int) -> str:
    y, m = map(int, ym.split("-"))
    total = y * 12 + (m - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def available_months(session: Session) -> list[str]:
    dates = session.scalars(select(Transaction.date).distinct())
    return sorted({d.strftime("%Y-%m") for d in dates}, reverse=True)


def _transactions(session: Session, start: date, end: date) -> list[Transaction]:
    return session.scalars(
        select(Transaction)
        .options(joinedload(Transaction.category).joinedload(Category.group))
        .where(Transaction.date >= start, Transaction.date < end)
    ).all()


@dataclass
class GroupLine:
    group: CategoryGroup
    spent: int = 0  # centimes, positif = dépense nette
    budget: int | None = None
    cats: dict[Category, int] = field(default_factory=lambda: defaultdict(int))


@dataclass
class MonthSummary:
    month: str
    income: int = 0
    expenses: int = 0
    savings: int = 0
    transfers: int = 0
    todo: int = 0
    todo_count: int = 0
    groups: list[GroupLine] = field(default_factory=list)

    @property
    def balance(self) -> int:
        """Rentrées moins dépenses (et lignes à classer), avant épargne."""
        return self.income - self.expenses - self.todo


def month_summary(session: Session, ym: str) -> MonthSummary:
    summary = MonthSummary(ym)
    lines: dict[int, GroupLine] = {}
    for tx in _transactions(session, *month_bounds(ym)):
        cat = tx.category
        kind = cat.kind if cat else KIND_TODO
        if kind == KIND_INCOME:
            summary.income += tx.amount_cents
        elif kind == KIND_SAVINGS:
            summary.savings -= tx.amount_cents
        elif kind == KIND_TRANSFER:
            summary.transfers -= tx.amount_cents
        elif kind == KIND_TODO:
            summary.todo -= tx.amount_cents
            summary.todo_count += 1
        elif kind == KIND_EXPENSE:
            summary.expenses -= tx.amount_cents
            line = lines.setdefault(cat.group_id, GroupLine(cat.group))
            line.spent -= tx.amount_cents
            line.cats[cat] -= tx.amount_cents

    # Les groupes budgétés apparaissent même sans dépense ce mois-ci.
    budgeted = session.scalars(
        select(Category).options(joinedload(Category.group)).where(Category.budget_cents.is_not(None))
    ).all()
    for cat in budgeted:
        line = lines.setdefault(cat.group_id, GroupLine(cat.group))
        line.budget = (line.budget or 0) + cat.budget_cents
        line.cats.setdefault(cat, 0)

    summary.groups = sorted(lines.values(), key=lambda g: -g.spent)
    for g in summary.groups:
        g.cats = dict(sorted(g.cats.items(), key=lambda kv: -kv[1]))
    return summary


def monthly_series(session: Session, last: str, n: int = 12) -> list[dict]:
    first = add_months(last, -(n - 1))
    series = {add_months(first, i): {"income": 0, "expenses": 0, "savings": 0} for i in range(n)}
    start, _ = month_bounds(first)
    _, end = month_bounds(last)
    for tx in _transactions(session, start, end):
        row = series[tx.date.strftime("%Y-%m")]
        kind = tx.category.kind if tx.category else KIND_TODO
        if kind == KIND_INCOME:
            row["income"] += tx.amount_cents
        elif kind in (KIND_EXPENSE, KIND_TODO):
            row["expenses"] -= tx.amount_cents
        elif kind == KIND_SAVINGS:
            row["savings"] -= tx.amount_cents
    return [{"month": ym, "label": month_label(ym), **v} for ym, v in series.items()]
