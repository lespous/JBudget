"""Catégories et règles de départ, créées au premier lancement."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .classifier import PRIORITY_SEED
from .models import (
    KIND_EXPENSE,
    KIND_IGNORE,
    KIND_INCOME,
    KIND_SAVINGS,
    KIND_TODO,
    KIND_TRANSFER,
    Category,
    CategoryGroup,
    Rule,
)

GROUPS: list[tuple[str, list]] = [
    ("Rentrées", [("Rentrées", KIND_INCOME)]),
    ("Logement", ["Crédit hypothécaire", "Énergie", "Eau", "Internet & téléphone", "Entretien & bricolage"]),
    ("Alimentation", ["Courses", "Boulangerie & pâtisserie", "Restaurants", "Snacks & cafés"]),
    ("Transport", ["Carburant", "Train & transports publics", "Parking & péages", "Entretien véhicule"]),
    ("Santé", ["Pharmacie", "Médecins & hôpital", "Mutuelle & assurance santé",
               "Remboursements mutuelle", "Optique & dentiste"]),
    ("Enfants & école", ["Frais scolaires", "Activités & stages", "Argent de poche"]),
    ("Loisirs", ["Sport", "Sorties & cinéma", "Jeux vidéo", "Jeux & loterie", "Vacances & voyages"]),
    ("Abonnements", ["Streaming", "Logiciels & services"]),
    ("Shopping", ["Vêtements & chaussures", "Achats en ligne", "Maison & déco", "Cadeaux"]),
    ("Assurances", ["Assurance vie", "Assurance habitation & auto"]),
    ("Dons", ["Associations"]),
    ("Banque & impôts", ["Frais bancaires", "Intérêts & taxes", "Impôts & taxes"]),
    ("Retraits", ["Retraits d'espèces"]),
    ("Divers", ["Divers"]),
    ("Épargne", [("Épargne", KIND_SAVINGS), ("Investissement", KIND_SAVINGS)]),
    ("Transferts", [("Remboursement carte VISA", KIND_TRANSFER)]),
    ("Système", [("À classer", KIND_TODO), ("Ignoré", KIND_IGNORE)]),
]

# (champ, motif, catégorie, sens, priorité). Un motif « ^X » signifie « commence par X ».
_P = PRIORITY_SEED + 50
RULES: list[tuple[str, str, str, str | None, int]] = [
    ("label", "^Paiement ING : VISA", "Remboursement carte VISA", None, _P),
    ("label", "Compte d'investissement", "Investissement", None, _P),
    ("merchant", "SOLIDARIS", "Remboursements mutuelle", "in", _P),
    ("merchant", "SOLIDARIS", "Mutuelle & assurance santé", "out", _P),
    ("label", "^CREDIT HYPOTHECAIRE", "Crédit hypothécaire", None, PRIORITY_SEED),
    ("label", "^Décompte de frais", "Frais bancaires", None, PRIORITY_SEED),
    ("label", "^Intérêts-Frais", "Intérêts & taxes", None, PRIORITY_SEED),
    ("label", "^Retrait d'espèces", "Retraits d'espèces", None, PRIORITY_SEED),
    ("label", "^Paiement carburant", "Carburant", None, PRIORITY_SEED),
    ("label", "^Prime d'assurance", "Assurance vie", None, PRIORITY_SEED),
]

MERCHANTS: dict[str, tuple[str | None, list[str]]] = {
    "Rentrées": ("in", ["CAISSE PUBLIQUE WALLONNE", "FAMIWAL", "MANGOPAY"]),
    "Courses": (None, ["COLRUYT", "DELHAIZE", "LIDL", "ALDI", "^SPAR", "^CRF", "CARREFOUR",
                       "^MATCH", "INTERMARCHE", "PROXY", "OKAY", "CORA", "AUCHAN", "LECLERC"]),
    "Boulangerie & pâtisserie": (None, ["BOULANGERIE", "PATISSERIE"]),
    "Snacks & cafés": (None, ["STARBUCKS", "FRITERIE"]),
    "Restaurants": (None, ["REST.", "RESTAURANT", "PIZZERIA", "TRATTORIA"]),
    "Carburant": (None, ["ESSO", "SHELL", "^TOTAL", "^Q8", "LUKOIL", "TEXACO"]),
    "Train & transports publics": (None, ["NMBS", "SNCB", "^STIB", "^TEC "]),
    "Parking & péages": (None, ["INDIGO", "PARKING"]),
    "Pharmacie": (None, ["PHARMACIE", "MEDI-MARKET", "FARMACIA", "APOTHEKE"]),
    "Médecins & hôpital": (None, ["HELORA", "CENTRE HOSPITALIER", "^DR "]),
    "Mutuelle & assurance santé": (None, ["DKV"]),
    "Frais scolaires": (None, ["ATHENEE", "LUMYS"]),
    "Énergie": (None, ["ENGIE"]),
    "Eau": (None, ["SOCIETE WALLONNE DES EAUX", "SWDE"]),
    "Internet & téléphone": (None, ["PROXIMUS", "ORANGE", "TELENET", "^VOO"]),
    "Sport": (None, ["DECATHLON", "INTERSPORT", "CABLE PARK", "SPORTSDIRECT", "RACE RESULT"]),
    "Sorties & cinéma": (None, ["IMAGIX", "I-MAGIX", "KINEPOLIS"]),
    "Jeux vidéo": (None, ["NINTENDO", "G2A", "STEAM", "PLAYSTATION"]),
    "Jeux & loterie": (None, ["NATIONALELOTERIJ", "LOTERIE NATIONALE"]),
    "Streaming": ("out", ["NETFLIX", "SPOTIFY", "DISNEY"]),
    "Logiciels & services": (None, ["ANTHROPIC", "AMAZONPRIME", "SNAPCHAT", "GOOGLE", "OPENAI"]),
    "Vêtements & chaussures": (None, ["PRIMARK", "AW LAB", "ADIDAS", "ZARA", "KIABI", "H&M", "JD SPORTS"]),
    "Achats en ligne": (None, ["AMAZON", "ALIPAY", "ALIEXPRESS", "VENTE PRIVEE", "VENTE-PRIVEE", "VEEPEE",
                               "BOL.COM", "TEMU", "ZALANDO", "VINTED"]),
    "Maison & déco": (None, ["^ACTION", "IKEA", "HUBO", "BRICO", "GAMMA", "TRAFIC"]),
    "Cadeaux": (None, ["LEETCHI"]),
    "Assurance vie": (None, ["NN INSURANCE"]),
    "Assurance habitation & auto": (None, ["ETHIAS"]),
    "Associations": (None, ["UNICEF", "MEDECINS SANS FRONTIERES", "GREENPEACE"]),
    "Impôts & taxes": (None, ["SERVICE PUBLIC FEDERAL FINANCES"]),
}


def _rule(field: str, pattern: str, cat: Category, direction: str | None, priority: int) -> Rule:
    match_type = "startswith" if pattern.startswith("^") else "contains"
    return Rule(
        field=field,
        match_type=match_type,
        pattern=pattern.lstrip("^"),
        category_id=cat.id,
        direction=direction,
        priority=priority,
        origin="seed",
    )


def local_rules_path() -> Path:
    return Path(os.environ.get("JBUDGET_RULES") or Path.cwd() / "rules.local.json")


def load_local_rules(path: Path | None = None) -> list[tuple[str, str, str, str | None, int]]:
    """Règles personnelles (IBAN, noms de proches…) gardées hors du dépôt Git.

    Format : [{"field": "merchant", "pattern": "^DUPONT", "category": "Argent de poche",
               "direction": "out", "priority": 150}, ...]
    """
    path = path or local_rules_path()
    if not path.exists():
        return []
    entries = json.loads(path.read_text(encoding="utf-8"))
    return [
        (e.get("field", "merchant"), e["pattern"], e["category"], e.get("direction"),
         e.get("priority", PRIORITY_SEED))
        for e in entries
    ]


def seed(session: Session) -> bool:
    """Crée catégories et règles si la base est vide. Renvoie True si quelque chose a été créé."""
    if session.scalar(select(func.count(Category.id))):
        return False
    by_name: dict[str, Category] = {}
    for gpos, (gname, cats) in enumerate(GROUPS):
        group = CategoryGroup(name=gname, position=gpos)
        session.add(group)
        for cpos, entry in enumerate(cats):
            name, kind = entry if isinstance(entry, tuple) else (entry, KIND_EXPENSE)
            cat = Category(group=group, name=name, kind=kind, position=cpos)
            session.add(cat)
            by_name[name] = cat
    session.flush()

    for field, pattern, cat_name, direction, priority in RULES + load_local_rules():
        if cat_name not in by_name:
            raise ValueError(f"rules.local.json : catégorie « {cat_name} » inconnue")
        session.add(_rule(field, pattern, by_name[cat_name], direction, priority))
    for cat_name, (direction, patterns) in MERCHANTS.items():
        for pattern in patterns:
            session.add(_rule("merchant", pattern, by_name[cat_name], direction, PRIORITY_SEED))
    session.flush()
    return True
