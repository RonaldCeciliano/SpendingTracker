from datetime import date
from html import escape

import pytest

import app as app_module
from app import EXPENSE_CATEGORIES
from database.db import get_db, get_spending_summary
from test_view_expenses import save_expense


REFERENCE_DATE = date(2026, 9, 15)


@pytest.fixture(autouse=True)
def controlled_today(monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return REFERENCE_DATE
    monkeypatch.setattr(app_module, "date", FixedDate)


def summary(app, reference_date=REFERENCE_DATE):
    with app.app_context():
        return get_spending_summary(reference_date, EXPENSE_CATEGORIES)


def test_empty_dashboard(client, app):
    result = summary(app)
    assert result["month_total"] == result["year_total"] == result["expense_count"] == 0
    assert result["category_totals"] == dict.fromkeys(EXPENSE_CATEGORIES, 0)
    assert result["month_totals"] == [0] * 12
    assert result["recent_expenses"] == []
    response = client.get("/")
    assert response.status_code == 200
    for text in ('id="month-total">$0.00', 'id="year-total">$0.00',
                 'id="expense-count">0', "No expenses yet", "Add your first expense",
                 "No category spending recorded yet", "No spending recorded for 2026",
                 'href="/expenses"', 'href="/expenses/add"', "September 2026"):
        assert text in response.text
    for category in EXPENSE_CATEGORIES:
        assert escape(category) in response.text


def test_calendar_totals_and_all_time_count(client, app):
    for day, amount in [("2025-12-31", 9000), ("2026-01-01", 10),
                        ("2026-08-31", 20), ("2026-09-01", 1250),
                        ("2026-09-30", 125000), ("2026-10-01", 30),
                        ("2026-12-31", 40), ("2027-01-01", 8000)]:
        save_expense(app, date=day, amount=amount)
    result = summary(app)
    assert result["month_total"] == 126250
    assert result["year_total"] == 126350
    assert result["expense_count"] == 8
    assert result["month_totals"] == [10, 0, 0, 0, 0, 0, 0, 20, 126250, 30, 0, 40]
    html = client.get("/").text
    assert 'id="month-total">$1,262.50' in html
    assert 'id="year-total">$1,263.50' in html
    assert 'id="expense-count">8' in html
    assert '<th scope="row">September</th><td>$1,262.50</td>' in html
    assert '<th scope="row">February</th><td>$0.00</td>' in html


def test_category_totals_include_all_time_and_repeated_categories(client, app):
    for index, category in enumerate(EXPENSE_CATEGORIES, start=1):
        save_expense(app, category=category, amount=index * 100)
    save_expense(app, category="Nail Supplies", amount=1250)
    save_expense(app, category="Nail Supplies", date="2025-01-01", amount=20)
    expected = {category: index * 100 for index, category in enumerate(EXPENSE_CATEGORIES, start=1)}
    expected["Nail Supplies"] = 1370
    assert summary(app)["category_totals"] == expected
    html = client.get("/").text
    assert '<th scope="row">Nail Supplies</th><td>$13.70</td>' in html
    assert "All time · USD" in html


def test_recent_expenses_limit_and_date_then_id_order(client, app):
    ids = []
    for day, vendor in [("2026-09-10", "Oldest"), ("2026-09-11", "Excluded"),
                        ("2026-09-15", "First tie"), ("2026-09-14", "Fourth"),
                        ("2026-09-13", "Fifth"), ("2026-09-15", "Last tie"),
                        ("2026-09-16", "Newest")]:
        ids.append(save_expense(app, date=day, vendor=vendor, amount=1250))
    assert [row["id"] for row in summary(app)["recent_expenses"]] == [ids[i] for i in (6, 5, 2, 3, 4)]
    html = client.get("/").text
    positions = [html.index(vendor) for vendor in ("Newest", "Last tie", "First tie", "Fourth", "Fifth")]
    assert positions == sorted(positions)
    assert "Oldest" not in html and "Excluded" not in html
    assert html.count('class="dashboard-recent-row"') == 5
    assert '<time datetime="2026-09-16">09-16-2026</time>' in html
    assert "$12.50" in html


@pytest.mark.parametrize("today,day", [
    (date(2026, 1, 1), "2026-01-31"), (date(2026, 12, 31), "2026-12-01"),
    (date(2024, 2, 29), "2024-02-29"),
])
def test_reference_date_boundaries(app, today, day):
    save_expense(app, date=day, amount=29)
    result = summary(app, today)
    assert result["month_total"] == result["year_total"] == 29
    assert result["month_totals"][today.month - 1] == 29


def test_previous_year_only(client, app):
    save_expense(app, date="2025-09-15", amount=1250)
    result = summary(app)
    assert result["year_total"] == result["month_total"] == 0
    assert result["month_totals"] == [0] * 12
    assert result["expense_count"] == 1
    assert result["category_totals"]["Nail Supplies"] == 1250
    assert "No spending recorded for 2026" in client.get("/").text


def test_large_totals_remain_exact_and_storage_unchanged(client, app):
    for _ in range(2):
        save_expense(app, amount=9223372036854775807)
    with app.app_context():
        before = [tuple(row) for row in get_db().execute("SELECT * FROM expenses")]
    result = summary(app)
    assert result["year_total"] == result["month_total"] == 18446744073709551614
    assert result["category_totals"]["Nail Supplies"] == 18446744073709551614
    assert "$184,467,440,737,095,516.14" in client.get("/").text
    with app.app_context():
        assert [tuple(row) for row in get_db().execute("SELECT * FROM expenses")] == before


def test_recent_vendor_is_escaped(client, app):
    save_expense(app, vendor="<script>alert(1)</script>")
    html = client.get("/").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


@pytest.mark.parametrize("path", ["/expenses", "/expenses/add", "/expenses?search=Nail",
    "/login", "/register", "/terms", "/privacy"])
def test_existing_routes_and_dashboard_navigation(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert 'href="/" class="nav-expense">Dashboard</a>' in response.text
