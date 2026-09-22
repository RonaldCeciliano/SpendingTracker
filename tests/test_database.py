import sqlite3

import pytest

from database.db import get_db, init_db


def insert_expense(db, **overrides):
    values = {
        "date": "2026-09-22",
        "vendor": "Nail Supply Shop",
        "amount": 1234,
        "category": "Nail supplies",
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    return db.execute(
        f"INSERT INTO expenses ({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    ).lastrowid


def test_expense_persists_with_all_fields(app):
    with app.app_context():
        db = get_db()
        expense_id = insert_expense(
            db,
            payment_method="Debit card",
            description="Gel polish and files",
            notes="Supplies for client appointments",
            receipt_path="receipts/example.jpg",
        )
        db.commit()

    with app.app_context():
        row = get_db().execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        assert dict(row) == {
            "id": expense_id,
            "date": "2026-09-22",
            "vendor": "Nail Supply Shop",
            "amount": 1234,
            "category": "Nail supplies",
            "payment_method": "Debit card",
            "description": "Gel polish and files",
            "notes": "Supplies for client appointments",
            "receipt_path": "receipts/example.jpg",
        }


def test_optional_fields_default_to_null_and_ids_are_unique(db):
    first_id = insert_expense(db)
    second_id = insert_expense(db)
    assert first_id != second_id
    row = db.execute("SELECT * FROM expenses WHERE id = ?", (first_id,)).fetchone()
    for field in ("payment_method", "description", "notes", "receipt_path"):
        assert row[field] is None


@pytest.mark.parametrize("field", ["date", "vendor", "amount", "category"])
def test_required_fields_reject_null(db, field):
    with pytest.raises(sqlite3.IntegrityError):
        insert_expense(db, **{field: None})


@pytest.mark.parametrize("field", ["vendor", "category"])
@pytest.mark.parametrize("value", ["", "   "])
def test_required_text_rejects_blank_values(db, field, value):
    with pytest.raises(sqlite3.IntegrityError):
        insert_expense(db, **{field: value})


@pytest.mark.parametrize("value", [
    "", "not a date", "09/22/2026", "2026-9-2", "2026-02-29",
    "2026-04-31", "2026-13-01", "2026-01-00",
])
def test_invalid_dates_are_rejected(db, value):
    with pytest.raises(sqlite3.IntegrityError):
        insert_expense(db, date=value)


def test_leap_day_and_iso_date_sorting(db):
    for value in ("2026-01-01", "2024-02-29", "2025-12-31"):
        insert_expense(db, date=value)
    rows = db.execute("SELECT date FROM expenses ORDER BY date").fetchall()
    assert [row["date"] for row in rows] == ["2024-02-29", "2025-12-31", "2026-01-01"]


@pytest.mark.parametrize("value", [-1, 12.34, "invalid", "", b"1234"])
def test_invalid_amounts_are_rejected(db, value):
    with pytest.raises(sqlite3.IntegrityError):
        insert_expense(db, amount=value)


def test_money_is_stored_and_summed_as_exact_integer_cents(db):
    for amount in (0, 10, 20, 1234):
        insert_expense(db, amount=amount)
    assert db.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] == 1264
    types = db.execute("SELECT DISTINCT typeof(amount) FROM expenses").fetchall()
    assert [row[0] for row in types] == ["integer"]


def test_initialization_preserves_existing_records(db):
    expense_id = insert_expense(db)
    db.commit()
    init_db()
    assert db.execute("SELECT id FROM expenses").fetchone()[0] == expense_id


def test_connection_is_reused_and_closed_with_context(app):
    with app.app_context():
        db = get_db()
        assert get_db() is db
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute("SELECT 1")


def test_init_db_command_creates_database_and_is_repeatable(app, tmp_path):
    app.config["DATABASE"] = str(tmp_path / "fresh.db")
    runner = app.test_cli_runner()
    result = runner.invoke(args=["init-db"])
    assert result.exit_code == 0
    assert "Expense database initialized." in result.output
    with app.app_context():
        insert_expense(get_db())
        get_db().commit()
    assert runner.invoke(args=["init-db"]).exit_code == 0
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1
