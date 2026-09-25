import pytest

from app import EXPENSE_CATEGORIES
from database.db import get_expenses
from test_add_expense import FormParser, expense_rows
from test_view_expenses import save_expense


@pytest.fixture
def history(app):
    return [
        save_expense(app, vendor="Sally Beauty", date="2026-09-01",
                     description="Gel polish restock"),
        save_expense(app, vendor="Tool Shop", date="2026-09-15",
                     category="Tools & Equipment", description="Polish mixer"),
        save_expense(app, vendor="Sally Beauty", date="2026-09-30",
                     category="Other"),
        save_expense(app, vendor="Local Supply", date="2026-09-15",
                     description="Files", notes="secret polish"),
    ]


@pytest.mark.parametrize("filters,expected", [
    ({}, [2, 3, 1, 0]),
    ({"search": "Sally Beauty"}, [2, 0]),
    ({"search": "sally"}, [2, 0]),
    ({"search": "SaLlY"}, [2, 0]),
    ({"search": "POLISH"}, [1, 0]),
    ({"search": "restock"}, [0]),
    ({"search": "missing"}, []),
    ({"category": "Nail Supplies"}, [3, 0]),
    ({"category": ""}, [2, 3, 1, 0]),
    ({"start_date": "2026-09-15"}, [2, 3, 1]),
    ({"end_date": "2026-09-15"}, [3, 1, 0]),
    ({"start_date": "2026-09-01", "end_date": "2026-09-15"}, [3, 1, 0]),
    ({"start_date": "2026-09-15", "end_date": "2026-09-15"}, [3, 1]),
    ({"search": "sally", "category": "Nail Supplies"}, [0]),
    ({"category": "Nail Supplies", "start_date": "2026-09-15", "end_date": "2026-09-30"}, [3]),
    ({"search": "polish", "category": "Tools & Equipment", "start_date": "2026-09-15",
      "end_date": "2026-09-30"}, [1]),
    ({"search": "  sally  "}, [2, 0]),
    ({"search": "   ", "start_date": " "}, [2, 3, 1, 0]),
])
def test_filter_results_and_read_only(client, app, history, filters, expected):
    before = [dict(row) for row in expense_rows(app)]
    response = client.get("/expenses", query_string=filters)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    links = [f'href="/expenses/{history[index]}/edit"' for index in expected]
    assert [html.index(link) for link in links] == sorted(html.index(link) for link in links)
    for index, expense_id in enumerate(history):
        assert (f'href="/expenses/{expense_id}/edit"' in html) == (index in expected)
    assert [dict(row) for row in expense_rows(app)] == before
    if not expected:
        assert "No expenses match your filters" in html
        assert "No expenses yet" not in html


@pytest.mark.parametrize("field", ["start_date", "end_date"])
@pytest.mark.parametrize("value", ["09-15-2026", "9-15-2026", "09/15/2026", "bad", "2026-02-29",
                                       "2026-04-31", "2026-13-01", "0000-01-01", "2026-9-15", "10000-01-01", "2026-09-15T12:00:00"])
def test_invalid_dates_preserve_values_without_query(client, monkeypatch, field, value):
    def unexpected_query(**kwargs):
        pytest.fail("Invalid filters should not query expenses")
    monkeypatch.setattr("app.get_expenses", unexpected_query)
    filters = {"search": " sally ", "category": "Other", "start_date": "2026-09-01",
               "end_date": "2026-09-30", field: value}
    response = client.get("/expenses", query_string=filters)
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    assert "Select a valid date." in html
    assert f'aria-describedby="filter-{field}-error"' in html
    assert FormParser(html).values == filters
    assert "No expenses match" not in html
    assert "No expenses yet" not in html


def test_reversed_range(client, history):
    filters = {"start_date": "2026-09-30", "end_date": "2026-09-01"}
    response = client.get("/expenses", query_string=filters)
    assert response.status_code == 400
    assert "End Date must be on or after Start Date." in response.text
    values = FormParser(response.text).values
    assert all(values[key] == value for key, value in filters.items())


def test_applied_values_clear_and_get_form(client, history):
    filters = dict(search=" polish ", category="Tools & Equipment",
                   start_date="2026-09-01", end_date="2026-09-30")
    html = client.get("/expenses", query_string=filters).text
    values = FormParser(html).values
    assert all(values[key] == value for key, value in filters.items())
    assert 'method="get" action="/expenses"' in html
    for field in ("start_date", "end_date"):
        assert f'id="filter-{field}" type="date" name="{field}"' in html
    assert "MM-DD-YYYY" not in html
    assert 'href="/expenses">Clear Filters</a>' in html
    cleared = client.get("/expenses").text
    assert all(FormParser(cleared).values[key] == "" for key in filters)
    assert cleared.count('class="expense-history-card"') == 4
    assert client.post("/expenses", data=filters).status_code == 405


def test_empty_database_with_and_without_filters(client):
    assert "No expenses yet" in client.get("/expenses").text
    html = client.get("/expenses?search=polish").text
    assert "No expenses match your filters" in html
    assert "No expenses yet" not in html
    assert 'href="/expenses">Clear Filters</a>' in html


@pytest.mark.parametrize("category", EXPENSE_CATEGORIES)
def test_supported_categories(client, app, category):
    expense_id = save_expense(app, category=category)
    response = client.get("/expenses", query_string={"category": category})
    assert response.status_code == 200
    assert f'href="/expenses/{expense_id}/edit"' in response.text
    assert FormParser(response.text).values["category"] == category


def test_invalid_category_is_escaped_and_preserved(client):
    value = '<script>alert("x")</script>'
    response = client.get("/expenses", query_string={"category": value, "search": value})
    assert response.status_code == 400
    assert "Choose one of the supported business categories." in response.text
    assert value not in response.text
    assert FormParser(response.text).values["category"] == value
    assert FormParser(response.text).values["search"] == value


@pytest.mark.parametrize("search", ["%", "_", "\\", "' OR 1=1 --", "<script>alert(1)</script>", "ÉCOLE"])
def test_literal_safe_and_unicode_search(client, app, search):
    match = save_expense(app, vendor="Prefix " + search.lower() + " suffix")
    save_expense(app, vendor="Unrelated")
    response = client.get("/expenses", query_string={"search": search})
    assert response.status_code == 200
    assert response.text.count('class="expense-history-card"') == 1
    assert f'href="/expenses/{match}/edit"' in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert len(expense_rows(app)) == 2


def test_database_filters_and_iso_bounds(app, history):
    with app.app_context():
        rows = get_expenses(search="POLISH", category="Tools & Equipment",
                            start_date="2026-09-15", end_date="2026-09-15")
        assert [row["id"] for row in rows] == [history[1]]
        assert get_expenses(category="' OR 1=1 --") == []


def test_leap_day_and_year_boundary(client, app):
    leap = save_expense(app, date="2024-02-29")
    save_expense(app, date="2025-01-01")
    response = client.get("/expenses?start_date=2024-02-29&end_date=2024-12-31")
    assert response.status_code == 200
    assert response.text.count('class="expense-history-card"') == 1
    assert f'href="/expenses/{leap}/edit"' in response.text


def test_edit_and_delete_from_filtered_history(client, app, history):
    html = client.get("/expenses?search=polish&category=Nail+Supplies").text
    assert '<dialog id="expense-delete-dialog"' in html
    expense_id = history[0]
    values = FormParser(client.get(f"/expenses/{expense_id}/edit").text).values
    values["description"] = "Updated stock"
    assert client.post(f"/expenses/{expense_id}/edit", data=values).status_code == 303
    assert 'class="expense-history-card"' not in client.get("/expenses?search=restock").text
    html = client.get("/expenses?search=Updated").text
    assert f'method="post" action="/expenses/{expense_id}/delete"' in html
    assert client.post(f"/expenses/{expense_id}/delete", data={
        "csrf_token": FormParser(html).values["csrf_token"]}).status_code == 303
    assert len(expense_rows(app)) == 3
