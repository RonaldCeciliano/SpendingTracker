import os
import re
import secrets
import sqlite3
from datetime import date
from decimal import Decimal

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

from database.db import (
    create_expense, delete_expense as delete_expense_record, get_expense,
    get_expenses, init_app, update_expense,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
init_app(app)

EXPENSE_CATEGORIES = (
    "Nail Supplies",
    "Tools & Equipment",
    "Sanitation & PPE",
    "Salon Expenses",
    "Business Fees",
    "Office & Shipping Supplies",
    "Other",
)
EXPENSE_TEXT_LIMITS = {
    "vendor": 200,
    "payment_method": 100,
    "description": 1000,
    "notes": 5000,
}
EXPENSE_FIELDS = ("date", "vendor", "amount", "category", "payment_method", "description", "notes")


def validate_expense(values):
    """Return field errors and normalized data; amount is converted to cents."""
    data = {field: value.strip() for field, value in values.items()}
    errors = {}
    for field in ("date", "vendor", "amount", "category"):
        if not data[field]:
            errors[field] = f"{field.title()} is required."

    if data["date"]:
        try:
            if not re.fullmatch(r"[0-9]{2}-[0-9]{2}-[0-9]{4}", data["date"]):
                raise ValueError
            month, day, year = map(int, data["date"].split("-"))
            data["date"] = date(year, month, day).isoformat()
        except ValueError:
            errors["date"] = "Enter a valid date in MM-DD-YYYY format."

    if data["amount"]:
        # Bound input before Decimal conversion and reject rounding/exponents.
        if len(data["amount"]) > 20 or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", data["amount"]):
            errors["amount"] = "Enter a dollar amount with no more than two decimal places (for example, 12.34)."
        else:
            cents = int(Decimal(data["amount"]) * 100)
            if cents <= 0:
                errors["amount"] = "Amount must be greater than zero."
            elif cents > 9223372036854775807:
                errors["amount"] = "Amount is too large."
            else:
                data["amount"] = cents

    if data["category"] and data["category"] not in EXPENSE_CATEGORIES:
        errors["category"] = "Choose one of the supported business categories."

    for field, limit in EXPENSE_TEXT_LIMITS.items():
        if len(values[field]) > limit:
            errors[field] = f"{field.replace('_', ' ').capitalize()} must be {limit} characters or fewer."
        elif "\x00" in values[field]:
            errors[field] = "Remove null characters from this field."

    for field in ("payment_method", "description", "notes"):
        data[field] = data[field] or None
    return errors, data


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/register")
def register():
    return render_template("register.html")


@app.route("/login")
def login():
    return render_template("login.html")


# ------------------------------------------------------------------ #
# Add expense                                                         #
# ------------------------------------------------------------------ #

@app.template_filter("expense_date")
def format_expense_date(value):
    """Display an ISO date without changing its stored representation."""
    year, month, day = value.split("-")
    return f"{month}-{day}-{year}"


@app.template_filter("expense_amount")
def format_expense_amount(cents):
    """Format integer cents exactly, including amounts beyond float precision."""
    dollars, remainder = divmod(cents, 100)
    return f"${dollars:,}.{remainder:02d}"


@app.route("/expenses")
def expenses():
    session.setdefault("expense_csrf_token", secrets.token_hex(32))
    return render_template("expenses.html", expenses=get_expenses())


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    return expense_form()


def valid_expense_csrf():
    token = request.form.get("csrf_token", "")
    expected = session.get("expense_csrf_token", "")
    return bool(expected) and secrets.compare_digest(token.encode(), expected.encode())


def expense_form(expense=None):
    """Share validation, error handling, and rendering for adding and editing."""
    session.setdefault("expense_csrf_token", secrets.token_hex(32))
    values = {field: "" for field in EXPENSE_FIELDS}
    if expense is not None:
        values = {field: expense[field] or "" for field in EXPENSE_FIELDS}
        values["date"] = format_expense_date(expense["date"])
        dollars, cents = divmod(expense["amount"], 100)
        values["amount"] = f"{dollars}.{cents:02d}"
    errors = {}
    status = 200
    if request.method == "POST":
        values = {field: request.form.get(field, "") for field in EXPENSE_FIELDS}
        errors, data = validate_expense(values)
        if not valid_expense_csrf():
            errors["form"] = "Your form session expired. Please submit the form again."
        if errors:
            status = 400
        else:
            try:
                if expense is None:
                    create_expense(**data)
                elif not update_expense(expense["id"], **data):
                    abort(404)
            except sqlite3.Error:
                app.logger.exception("Could not save expense")
                errors["form"] = "Your expense could not be saved. Please try again shortly."
                status = 503
            else:
                if expense is not None:
                    flash("Expense updated successfully.", "success")
                    return redirect(url_for("expenses"), code=303)
                flash("Expense saved successfully.", "success")
                return redirect(url_for("add_expense"), code=303)
    return render_template(
        "add_expense.html", values=values, errors=errors, expense=expense,
        categories=EXPENSE_CATEGORIES, text_limits=EXPENSE_TEXT_LIMITS,
    ), status


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    expense = get_expense(id)
    if expense is None:
        abort(404)
    return expense_form(expense)


@app.route("/expenses/<int:id>/delete", methods=["POST"])
def delete_expense(id):
    if get_expense(id) is None:
        abort(404)
    if not valid_expense_csrf():
        abort(400, description="Your form session expired. Return to Expenses and try again.")
    try:
        if not delete_expense_record(id):
            abort(404)
    except sqlite3.Error:
        app.logger.exception("Could not delete expense")
        return render_template(
            "expenses.html", expenses=get_expenses(),
            error="Your expense could not be deleted. Please try again shortly.",
        ), 503
    flash("Expense deleted successfully.", "success")
    return redirect(url_for("expenses"), code=303)


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    return "Logout — coming in Step 3"


@app.route("/profile")
def profile():
    return "Profile page — coming in Step 4"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
