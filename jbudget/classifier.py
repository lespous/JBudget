"""Classement : règles (par priorité), puis mémoire des corrections, sinon « À classer »."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import KIND_IGNORE, KIND_TODO, Category, Rule, Transaction
from .normalize import fold, strip_accents

FIELDS = {
    "merchant": "Marchand",
    "label": "Libellé complet",
    "counterparty": "Contrepartie (nom ou IBAN)",
}
MATCH_TYPES = {
    "contains": "contient",
    "startswith": "commence par",
    "equals": "est égal à",
    "regex": "expression régulière",
}
DIRECTIONS = {"": "entrées et sorties", "out": "sorties", "in": "entrées"}

# Priorités par défaut : une règle apprise d'une correction passe avant les règles de départ.
PRIORITY_SEED = 100
PRIORITY_LEARNED = 200
PRIORITY_MANUAL = 300


def sign(cents: int) -> int:
    return (cents > 0) - (cents < 0)


def field_text(tx, field: str) -> str:
    if field == "merchant":
        return fold(tx.merchant)
    if field == "label":
        return fold(" ".join(filter(None, [tx.description, tx.details, tx.message])))
    if field == "counterparty":
        return fold(f"{tx.counterparty_iban or ''} {tx.counterparty_name or ''}")
    raise ValueError(f"champ inconnu : {field}")


def validate_rule(field: str, match_type: str, pattern: str) -> str | None:
    """Renvoie un message d'erreur, ou None si la règle est valide."""
    if field not in FIELDS:
        return "Champ inconnu."
    if match_type not in MATCH_TYPES:
        return "Type de correspondance inconnu."
    if not pattern.strip():
        return "Le motif est vide."
    if match_type == "regex":
        try:
            re.compile(strip_accents(pattern), re.IGNORECASE)
        except re.error as e:
            return f"Expression régulière invalide : {e}"
    return None


class CompiledRule:
    """Accepte une Rule ou tout objet ayant les mêmes attributs (test d'une règle non enregistrée)."""

    def __init__(self, rule):
        self.rule = rule
        self.rx = None
        self.pattern = fold(rule.pattern)
        if rule.match_type == "regex":
            try:
                self.rx = re.compile(strip_accents(rule.pattern), re.IGNORECASE)
            except re.error:
                self.pattern = None

    def matches(self, tx) -> bool:
        r = self.rule
        if self.pattern is None:
            return False
        if r.direction == "in" and tx.amount_cents <= 0:
            return False
        if r.direction == "out" and tx.amount_cents >= 0:
            return False
        amount = abs(tx.amount_cents)
        if r.min_cents is not None and amount < r.min_cents:
            return False
        if r.max_cents is not None and amount > r.max_cents:
            return False
        text = field_text(tx, r.field)
        match r.match_type:
            case "contains":
                return self.pattern in text
            case "startswith":
                return text.startswith(self.pattern)
            case "equals":
                return text == self.pattern
            case "regex":
                return bool(self.rx.search(text))
        return False


def system_category(session: Session, kind: str) -> Category:
    cat = session.scalar(select(Category).where(Category.kind == kind).order_by(Category.id))
    if cat is None:
        raise RuntimeError(f"catégorie système « {kind} » manquante")
    return cat


class Classifier:
    def __init__(self, session: Session):
        rules = session.scalars(select(Rule).where(Rule.enabled)).all()
        self.rules = sorted(
            (CompiledRule(r) for r in rules),
            key=lambda c: (-c.rule.priority, -len(c.rule.pattern), c.rule.id),
        )
        # Mémoire : catégorie choisie à la main pour chaque (marchand, sens).
        self.memory: dict[tuple[str, int], Counter] = defaultdict(Counter)
        rows = session.execute(
            select(Transaction.merchant, Transaction.amount_cents, Transaction.category_id).where(
                Transaction.locked, Transaction.category_id.is_not(None)
            )
        )
        for merchant, cents, cat_id in rows:
            if merchant:
                self.memory[(fold(merchant), sign(cents))][cat_id] += 1
        self.todo_id = system_category(session, KIND_TODO).id
        self.ignore_id = system_category(session, KIND_IGNORE).id

    def classify(self, tx) -> tuple[int, str, int | None]:
        if tx.amount_cents == 0:
            return self.ignore_id, "system", None
        for c in self.rules:
            if c.matches(tx):
                return c.rule.category_id, "rule", c.rule.id
        seen = self.memory.get((fold(tx.merchant), sign(tx.amount_cents)))
        if seen:
            return seen.most_common(1)[0][0], "memory", None
        return self.todo_id, "none", None

    def apply(self, tx: Transaction) -> bool:
        """Classe une transaction non verrouillée. Renvoie True si sa catégorie change."""
        if tx.locked:
            return False
        cat_id, source, rule_id = self.classify(tx)
        changed = tx.category_id != cat_id
        tx.category_id, tx.source, tx.rule_id = cat_id, source, rule_id
        return changed


def reclassify(session: Session) -> int:
    """Réapplique les règles à toutes les transactions non verrouillées."""
    session.flush()
    clf = Classifier(session)
    return sum(clf.apply(tx) for tx in session.scalars(select(Transaction)))
