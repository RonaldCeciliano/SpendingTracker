from html.parser import HTMLParser
import sqlite3

import pytest

from app import EXPENSE_CATEGORIES, EXPENSE_TEXT_LIMITS
from database.db import get_db


class FormParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.textarea = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input":
            self.values[attrs.get("name")] = attrs.get("value", "")
        elif tag == "option" and "selected" in attrs:
            self.values["category"] = attrs["value"]
        elif tag == "textarea":
            self.textarea = attrs["name"]
            self.values[self.textarea] = ""

    def handle_data(self, data):
        if self.textarea:
            self.values[self.textarea] += data

    def handle_endtag(self, tag):
        if tag == "textarea":
            self.textarea = None


@pytest.fixture
def expense_form(client):
    page = client.get("/expenses/add")
    token = FormParser(page.get_data(as_text=True)).values["csrf_token"]
    return {
        "csrf_token": token,
        "date": "09-22-2026",
        "vendor": "Nail Supply Shop",
        "amount": "12.34",
        "category": "Nail Supplies",
        "payment_method": "Debit card",
        "description": "Gel polish",
        "notes": "For client appointments",
    }


def expense_rows(app):
    with app.app_context():
        return get_db().execute("SELECT * FROM expenses").fetchall()


def test_page_and_navigation(client, app):
    assert 'href="/expenses/add"' in client.get("/").get_data(as_text=True)
    response = client.get("/expenses/add")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Add Expense — Spendly" in html
    assert "Date (MM-DD-YYYY)" in html
    assert 'placeholder="09-22-2026"' in html
    assert 'name="receipt_path"' not in html
    assert expense_rows(app) == []


def test_save_redirect_success_and_refresh(client, app, expense_form):
    response = client.post("/expenses/add", data=expense_form)
    assert response.status_code == 303
    assert response.headers["Location"] == "/expenses/add"
    rows = expense_rows(app)
    assert len(rows) == 1
    assert dict(rows[0]) == {
        "id": rows[0]["id"], "date": "2026-09-22", "vendor": "Nail Supply Shop",
        "amount": 1234, "category": "Nail Supplies", "payment_method": "Debit card",
        "description": "Gel polish", "notes": "For client appointments", "receipt_path": None,
    }
    page = client.get(response.headers["Location"])
    assert "Expense saved successfully." in page.get_data(as_text=True)
    assert FormParser(page.get_data(as_text=True)).values["vendor"] == ""
    refreshed = client.get("/expenses/add")
    assert "Expense saved successfully." not in refreshed.get_data(as_text=True)
    assert len(expense_rows(app)) == 1


@pytest.mark.parametrize("category", EXPENSE_CATEGORIES)
def test_supported_categories(client, app, expense_form, category):
    expense_form["category"] = category
    assert client.post("/expenses/add", data=expense_form).status_code == 303
    assert expense_rows(app)[0]["category"] == category


@pytest.mark.parametrize("value,cents", [
    ("0.01", 1), ("0.29", 29), ("10", 1000), ("12.3", 1230),
    (" 12.34 ", 1234), ("92233720368547758.07", 9223372036854775807),
])
def test_exact_amount_conversion(client, app, expense_form, value, cents):
    expense_form["amount"] = value
    assert client.post("/expenses/add", data=expense_form).status_code == 303
    assert expense_rows(app)[0]["amount"] == cents


@pytest.mark.parametrize("field", ["date", "vendor", "amount", "category"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_required_fields(client, app, expense_form, field, value):
    if value is None:
        expense_form.pop(field)
    else:
        expense_form[field] = value
    response = client.post("/expenses/add", data=expense_form)
    assert response.status_code == 400
    assert f"{field.title()} is required." in response.get_data(as_text=True)
    assert expense_rows(app) == []


@pytest.mark.parametrize("field,value", [
    ("date", "02-29-2026"), ("date", "04-31-2026"), ("date", "20260922"),
    ("date", "09/22/2026"), ("date", "9-2-2026"), ("date", "bad date"),
    ("date", "2026-09-22"), ("date", "13-01-2026"), ("date", "09-00-2026"),
    ("date", "09-22-0000"), ("date", " 02-29-2026 "),
    ("category", "Personal"), ("category", "nail supplies"),
    ("amount", "0"), ("amount", "0.00"), ("amount", "-1"),
    ("amount", "12.345"), ("amount", "NaN"), ("amount", "Infinity"),
    ("amount", "1e2"), ("amount", "$12.00"), ("amount", "1,000.00"),
    ("amount", "92233720368547758.08"), ("amount", "9" * 100),
    ("amount", "１２.３４"), ("amount", "abc"),
])
def test_invalid_values_preserved_without_saving(client, app, expense_form, field, value):
    expense_form[field] = value
    response = client.post("/expenses/add", data=expense_form)
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    assert f'id="{field}-error"' in html
    if field == "date":
        assert "Enter a valid date in MM-DD-YYYY format." in html
    values = FormParser(html).values
    for name, original in expense_form.items():
        assert values[name] == original
    assert expense_rows(app) == []


@pytest.mark.parametrize("field,limit", EXPENSE_TEXT_LIMITS.items())
def test_text_lengths_validated(client, app, expense_form, field, limit):
    expense_form[field] = "a" * (limit + 1)
    response = client.post("/expenses/add", data=expense_form)
    assert response.status_code == 400
    assert f"{limit} characters or fewer" in response.get_data(as_text=True)
    assert expense_rows(app) == []


def test_optional_fields_and_receipt_not_accepted(client, app, expense_form):
    for field in ("payment_method", "description", "notes"):
        expense_form.pop(field)
    expense_form["receipt_path"] = "/untrusted/path"
    assert client.post("/expenses/add", data=expense_form).status_code == 303
    row = expense_rows(app)[0]
    for field in ("payment_method", "description", "notes", "receipt_path"):
        assert row[field] is None


def test_trims_text_and_accepts_leap_day(client, app, expense_form):
    expense_form.update(date="02-29-2024", vendor="  Nail Shop  ", notes=" \n ")
    assert client.post("/expenses/add", data=expense_form).status_code == 303
    row = expense_rows(app)[0]
    assert row["date"] == "2024-02-29"
    assert row["vendor"] == "Nail Shop"
    assert row["notes"] is None


def test_valid_date_preserved_exactly_when_another_field_is_invalid(client, app, expense_form):
    expense_form.update(date=" 09-22-2026 ", amount="0")
    response = client.post("/expenses/add", data=expense_form)
    assert response.status_code == 400
    assert FormParser(response.get_data(as_text=True)).values["date"] == " 09-22-2026 "
    assert expense_rows(app) == []


@pytest.mark.parametrize("token", [None, "incorrect", "☃"])
def test_csrf_rejected(client, app, expense_form, token):
    if token is None:
        expense_form.pop("csrf_token")
    else:
        expense_form["csrf_token"] = token
    response = client.post("/expenses/add", data=expense_form)
    assert response.status_code == 400
    assert "form session expired" in response.get_data(as_text=True)
    assert expense_rows(app) == []


def test_escaped_output_and_parameterized_save(client, app, expense_form):
    expense_form.update(vendor="'); DROP TABLE expenses; --", notes="<script>alert(1)</script>", amount="0")
    response = client.post("/expenses/add", data=expense_form)
    assert "<script>alert(1)</script>" not in response.get_data(as_text=True)
    assert FormParser(response.get_data(as_text=True)).values["notes"] == expense_form["notes"]
    expense_form["amount"] = "1"
    assert client.post("/expenses/add", data=expense_form).status_code == 303
    assert expense_rows(app)[0]["vendor"] == expense_form["vendor"]


def test_storage_failure_preserves_form(client, app, expense_form, monkeypatch):
    def fail(**kwargs):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr("app.create_expense", fail)
    response = client.post("/expenses/add", data=expense_form)
    assert response.status_code == 503
    assert "could not be saved" in response.get_data(as_text=True)
    assert FormParser(response.get_data(as_text=True)).values["vendor"] == expense_form["vendor"]
    assert expense_rows(app) == []
