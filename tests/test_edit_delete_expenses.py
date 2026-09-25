import sqlite3

import pytest

from app import EXPENSE_CATEGORIES, EXPENSE_TEXT_LIMITS
from database.db import delete_expense, get_expense, get_expenses, update_expense
from test_add_expense import FormParser, expense_rows
from test_view_expenses import save_expense


@pytest.fixture
def existing(app):
    return save_expense(app, payment_method="Debit card", description="Gel polish",
                        notes="Client appointments")


@pytest.fixture
def edit_form(client, existing):
    response = client.get(f"/expenses/{existing}/edit")
    assert response.status_code == 200
    return FormParser(response.get_data(as_text=True)).values


def test_edit_prepopulates_all_fields(client, app, existing, edit_form):
    assert {k: v for k, v in edit_form.items() if k != "csrf_token"} == {
        "date": "2026-09-22", "vendor": "Nail Supply Shop", "amount": "74.38",
        "category": "Nail Supplies", "payment_method": "Debit card",
        "description": "Gel polish", "notes": "Client appointments",
    }
    assert len(expense_rows(app)) == 1
    html = client.get(f"/expenses/{existing}/edit").get_data(as_text=True)
    assert "Edit Expense — Spendly" in html
    assert 'type="date" name="date"' in html
    assert 'href="/expenses"' in html


@pytest.mark.parametrize("amount,display", [(1, "0.01"), (125000, "1250.00"),
    (9223372036854775807, "92233720368547758.07")])
def test_edit_exact_money_and_empty_optional_fields(client, app, amount, display):
    expense_id = save_expense(app, amount=amount)
    values = FormParser(client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)).values
    assert values["amount"] == display
    for field in ("description", "notes", "payment_method"):
        assert values[field] == ""
    assert client.post(f"/expenses/{expense_id}/edit", data=values).status_code == 303
    assert expense_rows(app)[0]["amount"] == amount


def test_edit_updates_only_selected_record_and_reorders_history(client, app, existing, edit_form):
    other = save_expense(app, vendor="Unaffected")
    before_other = dict(expense_rows(app)[1])
    edit_form.update(date="2024-02-29", vendor=" Updated vendor ", amount="0.29",
                     category="Other", payment_method="Cash", description="Files", notes="Updated")
    response = client.post(f"/expenses/{existing}/edit", data=edit_form)
    assert response.status_code == 303
    assert response.location == "/expenses"
    rows = expense_rows(app)
    assert len(rows) == 2
    assert dict(rows[1]) == before_other
    assert dict(rows[0]) == dict(id=existing, date="2024-02-29", vendor="Updated vendor",
        amount=29, category="Other", payment_method="Cash", description="Files",
        notes="Updated", receipt_path=None)
    with app.app_context():
        assert [r["id"] for r in get_expenses()] == [other, existing]
    assert "Expense updated successfully." in client.get(response.location).get_data(as_text=True)
    assert "Expense updated successfully." not in client.get(response.location).get_data(as_text=True)
    assert len(expense_rows(app)) == 2


@pytest.mark.parametrize("category", EXPENSE_CATEGORIES)
def test_edit_categories(client, app, existing, edit_form, category):
    edit_form["category"] = category
    assert client.post(f"/expenses/{existing}/edit", data=edit_form).status_code == 303
    assert expense_rows(app)[0]["category"] == category


@pytest.mark.parametrize("field,value", [
    ("date", ""), ("vendor", "  "), ("amount", ""), ("category", ""),
    ("date", "09-22-2026"), ("date", "2026-02-29"), ("date", "9-2-2026"),
    ("date", "2026-9-22"), ("date", "10000-01-01"),
    ("amount", "0"), ("amount", "-1"), ("amount", "1.234"), ("amount", "NaN"),
    ("amount", "1e2"), ("amount", "92233720368547758.08"), ("category", "Personal"),
    *[(field, "a" * (limit + 1)) for field, limit in EXPENSE_TEXT_LIMITS.items()],
])
def test_invalid_edit_preserves_form_and_record(client, app, existing, edit_form, field, value):
    before = dict(expense_rows(app)[0])
    edit_form[field] = value
    response = client.post(f"/expenses/{existing}/edit", data=edit_form)
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    assert f'id="{field}-error"' in html
    values = FormParser(html).values
    for name, original in edit_form.items():
        if name == "category" and not original:
            continue
        assert values[name] == original
    assert dict(expense_rows(app)[0]) == before


def test_edit_can_clear_optional_fields(client, app, existing, edit_form):
    for field in ("description", "notes", "payment_method"):
        edit_form.pop(field)
    edit_form["receipt_path"] = "untrusted"
    assert client.post(f"/expenses/{existing}/edit", data=edit_form).status_code == 303
    for field in ("description", "notes", "payment_method", "receipt_path"):
        assert expense_rows(app)[0][field] is None


@pytest.mark.parametrize("action", ["edit", "delete"])
@pytest.mark.parametrize("token", [None, "wrong", "☃"])
def test_mutations_require_csrf(client, app, existing, edit_form, action, token):
    before = dict(expense_rows(app)[0])
    if token is None:
        edit_form.pop("csrf_token")
    else:
        edit_form["csrf_token"] = token
    response = client.post(f"/expenses/{existing}/{action}", data=edit_form)
    assert response.status_code == 400
    assert "form session expired" in response.get_data(as_text=True)
    assert dict(expense_rows(app)[0]) == before


@pytest.mark.parametrize("action", ["edit", "delete"])
def test_csrf_without_prior_session(client, app, existing, action):
    assert client.post(f"/expenses/{existing}/{action}", data={"csrf_token": ""}).status_code == 400
    assert len(expense_rows(app)) == 1


@pytest.mark.parametrize("expense_id", ["999", "0", "-1", "abc", "1.5", "9223372036854775808"])
@pytest.mark.parametrize("action,method", [("edit", "get"), ("edit", "post"), ("delete", "post")])
def test_missing_or_invalid_id(client, expense_id, action, method):
    assert getattr(client, method)(f"/expenses/{expense_id}/{action}").status_code == 404


def test_history_actions_and_delete_only_selected(client, app, existing):
    other = save_expense(app, vendor="Keep this")
    html = client.get("/expenses").get_data(as_text=True)
    for expense_id in (existing, other):
        assert f'href="/expenses/{expense_id}/edit"' in html
        assert f'method="post" action="/expenses/{expense_id}/delete"' in html
    token = FormParser(html).values["csrf_token"]
    response = client.post(f"/expenses/{existing}/delete", data={"csrf_token": token})
    assert response.status_code == 303
    assert response.location == "/expenses"
    assert [row["id"] for row in expense_rows(app)] == [other]
    html = client.get(response.location).get_data(as_text=True)
    assert "Expense deleted successfully." in html
    assert "Keep this" in html
    assert "Nail Supply Shop" not in html
    assert "Expense deleted successfully." not in client.get("/expenses").get_data(as_text=True)


@pytest.mark.parametrize("method", ["get", "head", "put", "patch"])
def test_delete_requires_post(client, app, existing, method):
    assert getattr(client, method)(f"/expenses/{existing}/delete").status_code == 405
    assert len(expense_rows(app)) == 1


def test_delete_last_expense_shows_empty_state(client, existing):
    html = client.get("/expenses").get_data(as_text=True)
    response = client.post(f"/expenses/{existing}/delete", data={
        "csrf_token": FormParser(html).values["csrf_token"]}, follow_redirects=True)
    assert "No expenses yet" in response.get_data(as_text=True)
    assert "Expense deleted successfully." in response.get_data(as_text=True)


@pytest.mark.parametrize("action,target", [("edit", "update_expense"), ("delete", "delete_expense_record")])
def test_storage_failures_preserve_record(client, app, existing, edit_form, monkeypatch, action, target):
    before = dict(expense_rows(app)[0])
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(f"app.{target}", fail)
    response = client.post(f"/expenses/{existing}/{action}", data=edit_form)
    assert response.status_code == 503
    assert "Please try again shortly" in response.get_data(as_text=True)
    assert dict(expense_rows(app)[0]) == before
    if action == "edit":
        assert FormParser(response.get_data(as_text=True)).values == edit_form


def test_database_operations(app, existing):
    with app.app_context():
        assert get_expense(existing)["notes"] == "Client appointments"
        assert get_expense(999) is None
        values = dict(date="2026-09-25", vendor="'); DROP TABLE expenses; --", amount=123,
                      category="Other")
        assert update_expense(existing, **values)
        assert get_expense(existing)["vendor"] == values["vendor"]
        assert not update_expense(999, **values)
        assert delete_expense(existing)
        assert not delete_expense(existing)
        assert get_expense(existing) is None


def test_confirmation_dialog_markup(client, existing):
    html = client.get("/expenses").get_data(as_text=True)
    assert '<dialog id="expense-delete-dialog"' in html
    assert 'aria-labelledby="expense-delete-title"' in html
    assert "This expense will be permanently deleted. This action cannot be undone." in html
    assert '>Cancel</button>' in html
    assert '>Delete Expense</button>' in html
    assert 'data-expense-summary="Nail Supply Shop · 09-22-2026 · $74.38"' in html
