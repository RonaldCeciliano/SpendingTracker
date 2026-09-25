import pytest

from database.db import create_expense, get_db, get_expenses


def save_expense(app, **overrides):
    values = {
        "date": "2026-09-22",
        "vendor": "Nail Supply Shop",
        "amount": 7438,
        "category": "Nail Supplies",
    }
    values.update(overrides)
    with app.app_context():
        return create_expense(**values)


def test_empty_history_and_navigation(client, app):
    with app.app_context():
        assert get_expenses() == []
    response = client.get("/expenses")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "No expenses yet" in html
    assert "Add your first expense" in html
    assert 'href="/expenses/add"' in html
    assert 'class="expense-history-list"' not in html
    for path in ("/", "/expenses/add"):
        html = client.get(path).get_data(as_text=True)
        assert 'href="/expenses"' in html
        assert 'href="/expenses/add"' in html


def test_saved_expense_display_and_read_only_storage(client, app):
    expense_id = save_expense(
        app, payment_method="Debit card", description="Gel polish and files",
        notes="Private notes should not appear",
    )
    with app.app_context():
        before = dict(get_db().execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone())
    response = client.get("/expenses")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for value in ("Nail Supply Shop", "09-22-2026", "$74.38", "Nail Supplies",
                  "Debit card", "Gel polish and files"):
        assert value in html
    assert '<time datetime="2026-09-22">09-22-2026</time>' in html
    assert "Private notes should not appear" not in html
    assert "No expenses yet" not in html
    with app.app_context():
        after = dict(get_db().execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone())
    assert after == before


def test_database_and_page_order_by_date_then_id(client, app):
    save_expense(app, date="2026-01-01", vendor="Middle date")
    save_expense(app, date="2026-09-22", vendor="Earlier same day")
    save_expense(app, date="2025-12-31", vendor="Oldest date")
    save_expense(app, date="2026-09-22", vendor="Later same day")
    expected = ["Later same day", "Earlier same day", "Middle date", "Oldest date"]
    with app.app_context():
        assert [row["vendor"] for row in get_expenses()] == expected
    html = client.get("/expenses").get_data(as_text=True)
    positions = [html.index(vendor) for vendor in expected]
    assert positions == sorted(positions)


@pytest.mark.parametrize("cents,display", [
    (0, "$0.00"), (1, "$0.01"), (29, "$0.29"), (7438, "$74.38"),
    (125000, "$1,250.00"), (9223372036854775807, "$92,233,720,368,547,758.07"),
])
def test_amount_formatting(client, app, cents, display):
    save_expense(app, amount=cents)
    assert display in client.get("/expenses").get_data(as_text=True)


@pytest.mark.parametrize("value", [None, ""])
def test_missing_optional_values(client, app, value):
    save_expense(app, payment_method=value, description=value)
    response = client.get("/expenses")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.count("<dd>—</dd>") == 2
    assert "None" not in html


def test_history_escapes_user_text(client, app):
    save_expense(app, vendor="<script>alert(1)</script>",
                 description="<b>Polish</b>", payment_method="<i>Cash</i>")
    html = client.get("/expenses").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;Polish&lt;/b&gt;" in html
    assert "&lt;i&gt;Cash&lt;/i&gt;" in html


def test_added_expense_appears_in_history(client):
    client.get("/expenses/add")
    with client.session_transaction() as session:
        token = session["expense_csrf_token"]
    response = client.post("/expenses/add", data={
        "csrf_token": token, "date": "2024-02-29", "vendor": "New supplies",
        "amount": "1250.00", "category": "Tools & Equipment",
    })
    assert response.status_code == 303
    assert response.headers["Location"] == "/expenses/add"
    html = client.get("/expenses").get_data(as_text=True)
    assert "New supplies" in html
    assert "02-29-2024" in html
    assert "$1,250.00" in html
