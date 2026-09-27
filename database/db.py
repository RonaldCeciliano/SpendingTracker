"""SQLite expense storage. Amounts are integer cents, never floating-point money.

For example, an expense of 12.34 is stored as amount=1234. Dates use
YYYY-MM-DD. All expenses use the same currency with two decimal places;
currency conversion and receipt file handling are outside this module.
"""

import sqlite3
from pathlib import Path

import click
from flask import current_app, g


def get_db():
    """Reuse one connection for the current Flask application context."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.create_function("casefold", 1, lambda value: (value or "").casefold(), deterministic=True)
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def create_expense(*, date, vendor, amount, category, payment_method=None,
                   description=None, notes=None, receipt_path=None):
    """Save validated expense data, with amount already expressed in cents."""
    db = get_db()
    with db:
        cursor = db.execute(
            """INSERT INTO expenses
               (date, vendor, amount, category, payment_method, description, notes, receipt_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (date, vendor, amount, category, payment_method, description, notes, receipt_path),
        )
    return cursor.lastrowid


def get_expenses(*, search="", category="", start_date="", end_date=""):
    """Filter history with validated ISO date bounds; preserve date/ID ordering."""
    conditions = []
    parameters = []
    if search:
        conditions.append("(instr(casefold(vendor), ?) > 0 OR instr(casefold(description), ?) > 0)")
        parameters.extend([search.casefold(), search.casefold()])
    if category:
        conditions.append("category = ?")
        parameters.append(category)
    if start_date:
        conditions.append("date >= ?")
        parameters.append(start_date)
    if end_date:
        conditions.append("date <= ?")
        parameters.append(end_date)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    return get_db().execute(
        """SELECT id, date, vendor, amount, category, payment_method, description, receipt_path
           FROM expenses""" + where + " ORDER BY date DESC, id DESC", parameters,
    ).fetchall()


def get_spending_summary(reference_date, categories):
    """Summarize stored cents using one reference date and exact Python integers.

    Category totals/count cover all time. Month/year totals include the entire
    calendar period, including any future-dated entries in that period. Stream
    only summary fields so totals cannot overflow SQLite's 64-bit SUM.
    """
    year = f"{reference_date.year:04d}"
    month_totals = [0] * 12
    category_totals = dict.fromkeys(categories, 0)
    expense_count = 0
    for expense in get_db().execute("SELECT date, amount, category FROM expenses"):
        expense_count += 1
        category = expense["category"]
        category_totals[category] = category_totals.get(category, 0) + expense["amount"]
        if expense["date"][:4] == year:
            month_totals[int(expense["date"][5:7]) - 1] += expense["amount"]
    recent_expenses = get_db().execute(
        """SELECT id, date, vendor, amount, category FROM expenses
           ORDER BY date DESC, id DESC LIMIT ?""", (5,),
    ).fetchall()
    return {
        "month_total": month_totals[reference_date.month - 1],
        "year_total": sum(month_totals),
        "expense_count": expense_count,
        "category_totals": category_totals,
        "month_totals": month_totals,
        "recent_expenses": recent_expenses,
    }


def get_expense(expense_id):
    """Return one expense, or None when its ID does not exist."""
    if not 0 < expense_id <= 9223372036854775807:
        return None
    return get_db().execute(
        "SELECT * FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()


def update_expense(expense_id, *, date, vendor, amount, category,
                   payment_method=None, description=None, notes=None, receipt_path=None):
    """Update validated fields in place; return whether a record was found."""
    db = get_db()
    with db:
        cursor = db.execute(
            """UPDATE expenses SET date = ?, vendor = ?, amount = ?, category = ?,
               payment_method = ?, description = ?, notes = ?, receipt_path = ? WHERE id = ?""",
            (date, vendor, amount, category, payment_method, description, notes, receipt_path, expense_id),
        )
    return cursor.rowcount == 1


def delete_expense(expense_id):
    """Delete only the selected expense; return whether it existed."""
    db = get_db()
    with db:
        cursor = db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    return cursor.rowcount == 1


def close_db(exception=None):
    """Close the context's connection, including after request failures."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create the expense table without deleting existing expense records."""
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL CHECK (
                length(date) = 10
                AND date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                AND date(date, '+0 days') IS date
            ),
            vendor TEXT NOT NULL CHECK (length(trim(vendor)) > 0),
            amount INTEGER NOT NULL CHECK (
                typeof(amount) = 'integer' AND amount >= 0
            ),
            category TEXT NOT NULL CHECK (length(trim(category)) > 0),
            payment_method TEXT,
            description TEXT,
            notes TEXT,
            receipt_path TEXT
        )
    """)
    db.commit()


@click.command("init-db")
def init_db_command():
    """Initialize database tables, preserving any existing data."""
    init_db()
    click.echo("Expense database initialized.")


def init_app(app):
    """Register database configuration, cleanup, and the initialization command."""
    app.config.setdefault("DATABASE", str(Path(app.root_path) / "expense_tracker.db"))
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
