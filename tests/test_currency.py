"""USD display regressions; stored amounts remain integer cents."""
from html import unescape
from pathlib import Path
import re

import pytest
from flask import render_template

from app import format_expense_amount
from test_add_expense import FormParser, expense_form
from test_view_expenses import save_expense


LEGACY_CURRENCY = re.compile(r"₹|\bINR\b|rupees?|en[-_]IN|\\u20b9", re.IGNORECASE)


def assert_us_currency(text):
    assert not LEGACY_CURRENCY.search(unescape(text))


def test_first_party_ui_has_no_legacy_currency():
    root = Path(__file__).resolve().parents[1]
    paths = [root / "app.py"]
    for directory in ("templates", "static/js", "static/css"):
        paths.extend(path for path in (root / directory).rglob("*") if path.is_file())
    for path in paths:
        assert not LEGACY_CURRENCY.search(unescape(path.read_text())), str(path)


@pytest.mark.parametrize("cents,expected", [
    (0, "$0.00"), (1250, "$12.50"), (125000, "$1,250.00"),
    (12345678, "$123,456.78"),
    (9223372036854775807, "$92,233,720,368,547,758.07"),
])
def test_usd_formatter(cents, expected):
    assert format_expense_amount(cents) == expected


@pytest.mark.parametrize("path", [
    "/", "/expenses/add", "/expenses", "/expenses?search=missing",
    "/login", "/register", "/terms", "/privacy",
])
def test_pages_and_empty_states_use_us_currency(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert_us_currency(response.text)


def test_dashboard_totals_use_usd(client):
    html = client.get("/").text
    assert "Dashboard — ExpenseHQ" in html
    assert 'id="month-total">$0.00' in html
    assert 'id="year-total">$0.00' in html
    assert "$18,240.00" not in html


@pytest.mark.parametrize("query", ["", "?search=Nail", "?category=Nail+Supplies",
    "?start_date=2026-09-01&end_date=2026-09-30"])
def test_history_and_filtered_results_use_usd(client, app, query):
    save_expense(app, amount=125000, receipt_path="receipt.png")
    response = client.get("/expenses" + query)
    assert response.status_code == 200
    assert "$1,250.00" in response.text
    assert_us_currency(response.text)


def test_edit_preserves_dollar_input_and_integer_cents(client, app):
    expense_id = save_expense(app, amount=125000)
    response = client.get(f"/expenses/{expense_id}/edit")
    assert response.status_code == 200
    assert 'Amount ($)' in response.text
    assert FormParser(response.text).values["amount"] == "1250.00"
    assert_us_currency(response.text)


@pytest.mark.parametrize("editing", [False, True])
def test_money_validation_uses_dollars(client, app, expense_form, editing):
    url = "/expenses/add"
    if editing:
        url = f"/expenses/{save_expense(app)}/edit"
    response = client.post(url, data=dict(expense_form, amount="12.345"))
    assert response.status_code == 400
    assert "Enter a dollar amount" in response.text
    assert_us_currency(response.text)


def test_receipt_error_screen_uses_us_currency(app):
    with app.test_request_context():
        assert_us_currency(render_template("receipt_error.html"))
