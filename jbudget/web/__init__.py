from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from .. import db as dbm
from ..classifier import (
    DIRECTIONS,
    FIELDS,
    MATCH_TYPES,
    PRIORITY_LEARNED,
    PRIORITY_MANUAL,
    CompiledRule,
    Classifier,
    reclassify,
    sign,
    system_category,
    validate_rule,
)
from ..formatting import money, parse_euros
from ..importer import import_file
from ..models import (
    KIND_EXPENSE,
    KIND_IGNORE,
    KIND_TODO,
    KINDS,
    Account,
    Category,
    CategoryGroup,
    ImportBatch,
    Rule,
    Transaction,
)
from ..normalize import fold
from ..parsers import ParseError
from ..stats import add_months, available_months, month_bounds, month_label, month_summary, monthly_series

SOURCES = {"rule": "règle", "memory": "mémoire", "manual": "manuel", "system": "auto", "none": "—"}


def db():
    if "db" not in g:
        g.db = dbm.new_session()
    return g.db


def load_groups(s):
    return s.scalars(
        select(CategoryGroup).options(selectinload(CategoryGroup.categories)).order_by(CategoryGroup.position)
    ).all()


def back(default: str = "transactions"):
    return redirect(request.form.get("next") or request.referrer or url_for(default))


def create_app(db_path: str | Path | None = None, init: bool = True) -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("JBUDGET_SECRET") or os.urandom(16)
    if init:
        dbm.init_db(db_path)

    app.jinja_env.filters["money"] = money
    app.jinja_env.filters["month_label"] = month_label
    app.jinja_env.globals.update(
        FIELDS=FIELDS, MATCH_TYPES=MATCH_TYPES, DIRECTIONS=DIRECTIONS, KINDS=KINDS, SOURCES=SOURCES
    )

    @app.teardown_appcontext
    def close_db(_exc):
        s = g.pop("db", None)
        if s is not None:
            s.close()

    @app.context_processor
    def inject_globals():
        s = db()
        todo = system_category(s, KIND_TODO)
        count = s.scalar(select(func.count()).where(Transaction.category_id == todo.id))

        def url_with(**changes):
            args = {**request.args.to_dict(), **changes}
            return url_for(request.endpoint, **{k: v for k, v in args.items() if v not in (None, "")})

        return {"todo_total": count, "todo_category": todo, "url_with": url_with}

    # ---------------------------------------------------------------- tableau de bord
    @app.get("/")
    def dashboard():
        s = db()
        months = available_months(s)
        if not months:
            return render_template("empty.html")
        month = request.args.get("month") if request.args.get("month") in months else months[0]
        summary = month_summary(s, month)
        series = monthly_series(s, month)
        top = max([g.spent for g in summary.groups] + [g.budget or 0 for g in summary.groups] + [1])
        return render_template(
            "dashboard.html", month=month, months=months, m=summary, series=series, top=top,
            prev=add_months(month, -1) if add_months(month, -1) in months else None,
            next_=add_months(month, 1) if add_months(month, 1) in months else None,
        )

    # ---------------------------------------------------------------- transactions
    @app.get("/transactions")
    def transactions():
        s = db()
        a = request.args
        months = available_months(s)
        month = a.get("month") or (months[0] if months else "all")
        stmt = select(Transaction).options(
            joinedload(Transaction.account), joinedload(Transaction.category).joinedload(Category.group)
        )
        if month != "all":
            start, end = month_bounds(month)
            stmt = stmt.where(Transaction.date >= start, Transaction.date < end)
        if acc := a.get("account", type=int):
            stmt = stmt.where(Transaction.account_id == acc)
        if cat := a.get("category", type=int):
            stmt = stmt.where(Transaction.category_id == cat)
        if grp := a.get("group", type=int):
            stmt = stmt.where(Transaction.category_id.in_(select(Category.id).where(Category.group_id == grp)))
        if rid := a.get("rule", type=int):
            stmt = stmt.where(Transaction.rule_id == rid)
        if a.get("dir") == "out":
            stmt = stmt.where(Transaction.amount_cents < 0)
        elif a.get("dir") == "in":
            stmt = stmt.where(Transaction.amount_cents > 0)
        rows = s.scalars(stmt.order_by(Transaction.date.desc(), Transaction.id.desc())).all()
        if q := fold(a.get("q")):
            rows = [t for t in rows if q in fold(f"{t.merchant} {t.description} {t.message}")]
        return render_template(
            "transactions.html", rows=rows, months=months, month=month, groups=load_groups(s),
            accounts=s.scalars(select(Account)).all(), total=sum(t.amount_cents for t in rows),
            filter_cat=s.get(Category, cat) if cat else None,
            filter_group=s.get(CategoryGroup, grp) if grp else None,
        )

    @app.get("/tx/<int:tx_id>/recat")
    def recat_form(tx_id: int):
        s = db()
        tx = s.get(Transaction, tx_id) or abort(404)
        cat = s.get(Category, request.args.get("category_id", type=int)) or abort(400)
        same = []
        if tx.merchant:
            same = [
                t for t in s.scalars(
                    select(Transaction).where(Transaction.merchant == tx.merchant, Transaction.id != tx.id)
                )
                if sign(t.amount_cents) == sign(tx.amount_cents) and not t.locked
            ]
        changing = sum(1 for t in same if t.category_id != cat.id)
        return render_template("_recat.html", tx=tx, cat=cat, same=len(same), changing=changing,
                               next=request.referrer)

    @app.post("/tx/<int:tx_id>/recat")
    def recat_save(tx_id: int):
        s = db()
        tx = s.get(Transaction, tx_id) or abort(404)
        cat = s.get(Category, request.form.get("category_id", type=int)) or abort(400)
        tx.category_id, tx.locked, tx.source, tx.rule_id = cat.id, True, "manual", None
        if request.form.get("scope") == "merchant" and tx.merchant:
            direction = "in" if tx.amount_cents > 0 else "out"
            rule = s.scalar(select(Rule).where(
                Rule.field == "merchant", Rule.match_type == "equals", Rule.pattern == tx.merchant,
                Rule.direction == direction, Rule.origin == "learned",
            ))
            if rule:
                rule.category_id, rule.enabled = cat.id, True
            else:
                s.add(Rule(field="merchant", match_type="equals", pattern=tx.merchant, category_id=cat.id,
                           direction=direction, priority=PRIORITY_LEARNED, origin="learned"))
            n = reclassify(s)
            flash(f"Règle apprise : « {tx.merchant} » → {cat.name}. {n} autre(s) transaction(s) reclassée(s).")
        else:
            flash(f"« {tx.merchant} » du {tx.date:%d/%m} classé en {cat.name}.")
        s.commit()
        return back()

    @app.post("/tx/<int:tx_id>/unlock")
    def unlock(tx_id: int):
        s = db()
        tx = s.get(Transaction, tx_id) or abort(404)
        tx.locked = False
        Classifier(s).apply(tx)
        s.commit()
        flash(f"Correction retirée : « {tx.merchant} » est de nouveau classé automatiquement.")
        return back()

    # ---------------------------------------------------------------- règles
    def rule_from_form(form):
        errors = []
        try:
            min_c, max_c = parse_euros(form.get("min")), parse_euros(form.get("max"))
        except ValueError as e:
            errors.append(str(e))
            min_c = max_c = None
        data = SimpleNamespace(
            field=form.get("field", "merchant"),
            match_type=form.get("match_type", "contains"),
            pattern=(form.get("pattern") or "").strip(),
            direction=form.get("direction") or None,
            min_cents=min_c,
            max_cents=max_c,
            category_id=form.get("category_id", type=int),
            priority=form.get("priority", type=int) or PRIORITY_MANUAL,
            enabled=form.get("enabled", "on") == "on",
        )
        if err := validate_rule(data.field, data.match_type, data.pattern):
            errors.append(err)
        return data, errors

    @app.get("/rules")
    def rules():
        s = db()
        a = request.args
        edit = s.get(Rule, a.get("edit", type=int)) if a.get("edit") else None
        prefill, _ = rule_from_form(a)
        stmt = select(Rule).options(joinedload(Rule.category).joinedload(Category.group))
        all_rules = s.scalars(stmt.order_by(Rule.priority.desc(), Rule.pattern)).all()
        if q := fold(a.get("q")):
            all_rules = [r for r in all_rules if q in fold(f"{r.pattern} {r.category.name} {r.category.group.name}")]
        hits = dict(s.execute(select(Transaction.rule_id, func.count()).group_by(Transaction.rule_id)).all())
        return render_template("rules.html", rules=all_rules, hits=hits, edit=edit, f=edit or prefill,
                               groups=load_groups(s))

    @app.get("/rules/test")
    def rules_test():
        s = db()
        data, errors = rule_from_form(request.args)
        if errors:
            return render_template("_rule_test.html", errors=errors, matches=[], changing=0, locked=0)
        rule = CompiledRule(data)
        matches = [t for t in s.scalars(
            select(Transaction).options(joinedload(Transaction.category)).order_by(Transaction.date.desc())
        ) if rule.matches(t)]
        edit_id = request.args.get("id", type=int)
        changing = sum(1 for t in matches if t.category_id != data.category_id and not t.locked)
        locked = sum(1 for t in matches if t.locked)
        others = sum(1 for t in matches if t.rule_id and t.rule_id != edit_id and t.category_id != data.category_id)
        return render_template("_rule_test.html", errors=[], matches=matches, changing=changing,
                               locked=locked, others=others)

    @app.post("/rules/save")
    def rules_save():
        s = db()
        data, errors = rule_from_form(request.form)
        if not s.get(Category, data.category_id or 0):
            errors.append("Choisis une catégorie.")
        rule_id = request.form.get("id", type=int)
        if errors:
            for e in errors:
                flash(e, "error")
            return redirect(url_for("rules", edit=rule_id) if rule_id else request.referrer or url_for("rules"))
        rule = s.get(Rule, rule_id) if rule_id else None
        if rule is None:
            rule = Rule(origin="manual")
            s.add(rule)
        for key in ("field", "match_type", "pattern", "direction", "min_cents", "max_cents",
                    "category_id", "priority", "enabled"):
            setattr(rule, key, getattr(data, key))
        n = reclassify(s)
        s.commit()
        flash(f"Règle #{rule.id} enregistrée. {n} transaction(s) reclassée(s).")
        return redirect(url_for("rules"))

    @app.post("/rules/<int:rule_id>/toggle")
    def rules_toggle(rule_id: int):
        s = db()
        rule = s.get(Rule, rule_id) or abort(404)
        rule.enabled = not rule.enabled
        n = reclassify(s)
        s.commit()
        flash(f"Règle #{rule.id} {'activée' if rule.enabled else 'désactivée'}. {n} transaction(s) reclassée(s).")
        return back("rules")

    @app.post("/rules/<int:rule_id>/delete")
    def rules_delete(rule_id: int):
        s = db()
        rule = s.get(Rule, rule_id) or abort(404)
        for tx in s.scalars(select(Transaction).where(Transaction.rule_id == rule_id)):
            tx.rule_id = None
        s.delete(rule)
        n = reclassify(s)
        s.commit()
        flash(f"Règle #{rule_id} supprimée. {n} transaction(s) reclassée(s).")
        return redirect(url_for("rules"))

    @app.post("/rules/reapply")
    def rules_reapply():
        s = db()
        n = reclassify(s)
        s.commit()
        flash(f"Règles réappliquées. {n} transaction(s) ont changé de catégorie.")
        return back("rules")

    # ---------------------------------------------------------------- catégories
    @app.get("/categories")
    def categories():
        s = db()
        tx_counts = dict(s.execute(select(Transaction.category_id, func.count()).group_by(Transaction.category_id)).all())
        rule_counts = dict(s.execute(select(Rule.category_id, func.count()).group_by(Rule.category_id)).all())
        return render_template("categories.html", groups=load_groups(s), tx_counts=tx_counts,
                               rule_counts=rule_counts, confirm=request.args.get("confirm", type=int))

    @app.post("/categories/add")
    def categories_add():
        s = db()
        name = request.form.get("name", "").strip()
        group = s.get(CategoryGroup, request.form.get("group_id", type=int) or 0)
        new_group = request.form.get("new_group", "").strip()
        if new_group:
            group = s.scalar(select(CategoryGroup).where(CategoryGroup.name == new_group))
            if group is None:
                pos = (s.scalar(select(func.max(CategoryGroup.position))) or 0) + 1
                group = CategoryGroup(name=new_group, position=pos)
                s.add(group)
        if not name or group is None:
            flash("Indique un nom et un groupe.", "error")
            return redirect(url_for("categories"))
        s.add(Category(group=group, name=name, kind=request.form.get("kind", KIND_EXPENSE), position=99))
        s.commit()
        flash(f"Catégorie « {name} » ajoutée dans {group.name}.")
        return redirect(url_for("categories"))

    @app.post("/categories/<int:cat_id>/update")
    def categories_update(cat_id: int):
        s = db()
        cat = s.get(Category, cat_id) or abort(404)
        try:
            budget = parse_euros(request.form.get("budget"))
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("categories"))
        cat.name = request.form.get("name", cat.name).strip() or cat.name
        cat.budget_cents = budget
        if cat.kind not in (KIND_TODO, KIND_IGNORE):
            kind = request.form.get("kind", cat.kind)
            cat.kind = kind if kind in KINDS and kind not in (KIND_TODO, KIND_IGNORE) else cat.kind
            cat.group_id = request.form.get("group_id", type=int) or cat.group_id
        s.commit()
        flash(f"Catégorie « {cat.name} » mise à jour.")
        return redirect(url_for("categories") + f"#cat-{cat.id}")

    @app.post("/categories/<int:cat_id>/delete")
    def categories_delete(cat_id: int):
        s = db()
        cat = s.get(Category, cat_id) or abort(404)
        if cat.kind in (KIND_TODO, KIND_IGNORE):
            flash("Cette catégorie système ne peut pas être supprimée.", "error")
            return redirect(url_for("categories"))
        todo = system_category(s, KIND_TODO)
        rules_ = s.scalars(select(Rule).where(Rule.category_id == cat.id)).all()
        for tx in s.scalars(select(Transaction).where(Transaction.category_id == cat.id)):
            tx.category_id, tx.locked, tx.source, tx.rule_id = todo.id, False, "none", None
        for tx in s.scalars(select(Transaction).where(Transaction.rule_id.in_([r.id for r in rules_]))):
            tx.rule_id = None
        for r in rules_:
            s.delete(r)
        name = cat.name
        s.delete(cat)
        n = reclassify(s)
        s.commit()
        flash(f"Catégorie « {name} » supprimée avec {len(rules_)} règle(s). {n} transaction(s) reclassée(s).")
        return redirect(url_for("categories"))

    @app.post("/groups/<int:group_id>/rename")
    def groups_rename(group_id: int):
        s = db()
        group = s.get(CategoryGroup, group_id) or abort(404)
        name = request.form.get("name", "").strip()
        if name:
            group.name = name
            s.commit()
            flash(f"Groupe renommé en « {name} ».")
        return redirect(url_for("categories"))

    # ---------------------------------------------------------------- import
    @app.get("/import")
    def import_page():
        s = db()
        batches = s.scalars(select(ImportBatch).order_by(ImportBatch.imported_at.desc()).limit(20)).all()
        return render_template("import.html", batches=batches, results=None)

    @app.post("/import")
    def import_upload():
        s = db()
        results, errors = [], []
        with tempfile.TemporaryDirectory() as tmp:
            for up in request.files.getlist("files"):
                if not up.filename:
                    continue
                path = Path(tmp) / f"upload{Path(up.filename).suffix.lower()}"
                up.save(path)
                try:
                    results.append(import_file(s, path, display_name=up.filename))
                except ParseError as e:
                    s.rollback()
                    errors.append(str(e).replace(path.name, up.filename))
        for e in errors:
            flash(e, "error")
        if not results and not errors:
            flash("Aucun fichier sélectionné.", "error")
        batches = s.scalars(select(ImportBatch).order_by(ImportBatch.imported_at.desc()).limit(20)).all()
        return render_template("import.html", batches=batches, results=results)

    return app
