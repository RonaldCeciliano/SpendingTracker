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
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def create_expense(*, date, vendor, amount, category, payment_method=None,
                   description=None, notes=None):
    """Save validated expense data, with amount already expressed in cents."""
    db = get_db()
    with db:
        cursor = db.execute(
            """INSERT INTO expenses
               (date, vendor, amount, category, payment_method, description, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (date, vendor, amount, category, payment_method, description, notes),
        )
    return cursor.lastrowid


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
