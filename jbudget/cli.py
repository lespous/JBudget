from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from . import db as dbm
from .classifier import (
    DIRECTIONS,
    FIELDS,
    MATCH_TYPES,
    PRIORITY_MANUAL,
    reclassify as reclassify_all,
    system_category,
    validate_rule,
)
from .formatting import money
from .importer import import_file
from .models import KIND_TODO, KINDS, Category, CategoryGroup, Rule, Transaction
from .parsers import ParseError
from .stats import available_months, month_label, month_summary

app = typer.Typer(help="JBudget : import des relevés ING / VISA et classement des dépenses.", no_args_is_help=True)
rules_app = typer.Typer(help="Consulter et modifier les règles de classement.", no_args_is_help=True)
app.add_typer(rules_app, name="rules")
console = Console()


@app.callback()
def main(
    db: Annotated[Optional[Path], typer.Option("--db", help="Fichier SQLite (défaut : $JBUDGET_DB ou ./jbudget.db)")] = None,
):
    dbm.init_db(db)


def _files(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out += sorted(f for f in p.iterdir() if f.suffix.lower() in (".csv", ".pdf"))
        else:
            out.append(p)
    return out


@app.command("import")
def import_cmd(paths: Annotated[list[Path], typer.Argument(help="Fichiers CSV ING / PDF VISA, ou dossiers", exists=True)]):
    """Importer des relevés. Les lignes déjà importées sont ignorées."""
    table = Table("Fichier", "Format", "Ajoutées", "Doublons", "À classer")
    with dbm.new_session() as s:
        for f in _files(paths):
            try:
                r = import_file(s, f)
            except ParseError as e:
                console.print(f"[red]{e}[/red]")
                continue
            table.add_row(r.filename, r.source, str(r.added), str(r.skipped), str(r.todo))
    console.print(table)


@app.command()
def reclassify():
    """Réappliquer les règles à toutes les transactions non verrouillées."""
    with dbm.new_session() as s:
        n = reclassify_all(s)
        s.commit()
    console.print(f"{n} transaction(s) ont changé de catégorie.")


@app.command()
def todo(limit: Annotated[int, typer.Option(help="Nombre de marchands affichés")] = 30):
    """Lister les marchands encore « À classer », du plus fréquent au moins fréquent."""
    with dbm.new_session() as s:
        todo_id = system_category(s, KIND_TODO).id
        rows = s.execute(
            select(Transaction.merchant, func.count(), func.sum(Transaction.amount_cents))
            .where(Transaction.category_id == todo_id)
            .group_by(Transaction.merchant)
            .order_by(func.count().desc())
            .limit(limit)
        ).all()
    table = Table("Marchand", "Lignes", "Total")
    for merchant, n, total in rows:
        table.add_row(merchant or "—", str(n), money(total))
    console.print(table)


@app.command()
def summary(month: Annotated[Optional[str], typer.Option(help="Mois AAAA-MM (défaut : le plus récent)")] = None):
    """Résumé d'un mois : rentrées, dépenses par groupe, épargne."""
    with dbm.new_session() as s:
        months = available_months(s)
        if not months:
            console.print("Aucune transaction. Lance d'abord `jbudget import`.")
            raise typer.Exit()
        m = month_summary(s, month or months[0])
    console.print(f"[bold]{month_label(m.month)}[/bold]")
    console.print(f"Rentrées {money(m.income)} · Dépenses {money(m.expenses, False)} · "
                  f"Épargne {money(m.savings, False)} · Solde {money(m.balance)}")
    if m.todo_count:
        console.print(f"[yellow]{m.todo_count} ligne(s) à classer ({money(m.todo, False)})[/yellow]")
    table = Table("Groupe", "Dépensé", "Budget")
    for g in m.groups:
        table.add_row(g.group.name, money(g.spent, False), money(g.budget, False) if g.budget else "")
    console.print(table)


@app.command()
def categories():
    """Lister les groupes et catégories."""
    with dbm.new_session() as s:
        groups = s.scalars(select(CategoryGroup).order_by(CategoryGroup.position)).all()
        table = Table("Groupe", "Catégorie", "Nature", "Budget")
        for g in groups:
            for c in g.categories:
                table.add_row(g.name, c.name, KINDS[c.kind], money(c.budget_cents, False) if c.budget_cents else "")
    console.print(table)


@rules_app.command("list")
def rules_list(search: Annotated[Optional[str], typer.Argument(help="Filtrer sur le motif ou la catégorie")] = None):
    """Lister les règles par priorité."""
    with dbm.new_session() as s:
        rules = s.scalars(
            select(Rule).options(joinedload(Rule.category)).order_by(Rule.priority.desc(), Rule.pattern)
        ).all()
        table = Table("#", "Prio", "Champ", "Condition", "Sens", "Catégorie", "Origine", "Actif")
        for r in rules:
            if search and search.lower() not in f"{r.pattern} {r.category.name}".lower():
                continue
            table.add_row(str(r.id), str(r.priority), FIELDS[r.field], f"{MATCH_TYPES[r.match_type]} « {r.pattern} »",
                          DIRECTIONS[r.direction or ""], r.category.name, r.origin, "oui" if r.enabled else "non")
    console.print(table)


@rules_app.command("add")
def rules_add(
    pattern: Annotated[str, typer.Argument(help="Texte recherché")],
    category: Annotated[str, typer.Argument(help="Nom exact de la catégorie")],
    field: Annotated[str, typer.Option(help="merchant | label | counterparty")] = "merchant",
    match: Annotated[str, typer.Option(help="contains | startswith | equals | regex")] = "contains",
    direction: Annotated[Optional[str], typer.Option(help="in | out")] = None,
    priority: Annotated[int, typer.Option()] = PRIORITY_MANUAL,
):
    """Ajouter une règle puis reclasser."""
    if err := validate_rule(field, match, pattern):
        console.print(f"[red]{err}[/red]")
        raise typer.Exit(1)
    with dbm.new_session() as s:
        cat = s.scalar(select(Category).where(Category.name == category))
        if cat is None:
            console.print(f"[red]Catégorie « {category} » introuvable. Voir `jbudget categories`.[/red]")
            raise typer.Exit(1)
        rule = Rule(field=field, match_type=match, pattern=pattern, category_id=cat.id,
                    direction=direction, priority=priority, origin="manual")
        s.add(rule)
        n = reclassify_all(s)
        s.commit()
        console.print(f"Règle #{rule.id} ajoutée. {n} transaction(s) reclassée(s).")


@rules_app.command("delete")
def rules_delete(rule_id: int):
    """Supprimer une règle puis reclasser."""
    with dbm.new_session() as s:
        rule = s.get(Rule, rule_id)
        if rule is None:
            console.print(f"[red]Règle #{rule_id} introuvable.[/red]")
            raise typer.Exit(1)
        for tx in s.scalars(select(Transaction).where(Transaction.rule_id == rule_id)):
            tx.rule_id = None
        s.delete(rule)
        n = reclassify_all(s)
        s.commit()
    console.print(f"Règle #{rule_id} supprimée. {n} transaction(s) reclassée(s).")


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 5000,
    debug: Annotated[bool, typer.Option()] = False,
):
    """Lancer l'interface web sur http://127.0.0.1:5000."""
    from .web import create_app

    console.print(f"JBudget : http://{host}:{port}")
    create_app(init=False).run(host=host, port=port, debug=debug)
