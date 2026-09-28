import calendar
import os
import re
import secrets
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for

from database.db import (
    create_expense, delete_expense as delete_expense_record, get_expense,
    get_expenses, get_spending_summary, init_app, update_expense,
)

from expense_report import build_expense_report
from expense_records import build_records_package

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    RECEIPT_UPLOAD_DIR=os.path.join(app.instance_path, "receipts"),
    MAX_RECEIPT_SIZE=5 * 1024 * 1024,
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
)
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


def parse_expense_date(value):
    """Validate the ISO calendar date submitted by a native date input."""
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError
    return date.fromisoformat(value).isoformat()


def validate_expense(values):
    """Return field errors and normalized data; amount is converted to cents."""
    data = {field: value.strip() for field, value in values.items()}
    errors = {}
    for field in ("date", "vendor", "amount", "category"):
        if not data[field]:
            errors[field] = f"{field.title()} is required."

    if data["date"]:
        try:
            data["date"] = parse_expense_date(data["date"])
        except ValueError:
            errors["date"] = "Select a valid date."

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



RECEIPT_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "pdf": "application/pdf"}


def receipt_file(identifier):
    """Accept only generated identifiers, never paths or symlinks."""
    if not identifier or not re.fullmatch(r"[0-9a-f]{32}\.(jpg|jpeg|png|pdf)", identifier):
        return None
    path = Path(app.config["RECEIPT_UPLOAD_DIR"]) / identifier
    return None if path.is_symlink() else path


def remove_receipt(identifier):
    path = receipt_file(identifier)
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            app.logger.exception("Could not remove stored receipt")


def validate_receipt(upload):
    if upload is None or not upload.filename:
        return None, None
    extension = upload.filename.rsplit(".", 1)[-1].lower()
    if extension not in RECEIPT_TYPES:
        return "Choose a JPG, JPEG, PNG, or PDF receipt.", None
    upload.stream.seek(0, 2)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > app.config["MAX_RECEIPT_SIZE"]:
        return "Receipt must be 5 MiB or smaller.", None
    header = upload.stream.read(8)
    upload.stream.seek(0)
    matches = (header.startswith(b"\xff\xd8\xff") if extension in ("jpg", "jpeg") else
               header == b"\x89PNG\r\n\x1a\n" if extension == "png" else header.startswith(b"%PDF-"))
    if not matches:
        return "The receipt contents do not match its JPG, PNG, or PDF file type.", None
    return None, extension


@app.errorhandler(413)
def upload_too_large(error):
    return render_template("receipt_error.html"), 413


@app.route("/expenses/<int:id>/receipt")
def view_receipt(id):
    expense = get_expense(id)
    path = receipt_file(expense["receipt_path"]) if expense else None
    if path is None or not path.is_file():
        abort(404)
    response = send_file(path, mimetype=RECEIPT_TYPES[path.suffix[1:]],
                         as_attachment=False, download_name="receipt" + path.suffix, max_age=0)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "sandbox"
    response.headers["Cache-Control"] = "private, no-store"
    return response

# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    reference_date = date.today()
    return render_template(
        "dashboard.html", reference_date=reference_date,
        month_names=tuple(calendar.month_name)[1:],
        summary=get_spending_summary(reference_date, EXPENSE_CATEGORIES),
    )


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


def expense_export(records, filters, *, package=False):
    """Build the shared report and optionally bundle its available receipts."""
    generated_date = date.today()
    output = build_expense_report(records, filters, generated_date,
                                  format_expense_date, format_expense_amount)
    if package:
        output = build_records_package(records, output, receipt_file)
    name = "records" if package else "report"
    extension = "zip" if package else "pdf"
    response = send_file(
        output, mimetype="application/zip" if package else "application/pdf", as_attachment=True,
        download_name=f"spendly-expense-{name}-{generated_date.isoformat()}.{extension}",
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.route("/expenses")
def expenses():
    return expense_history()


@app.route("/expenses/export")
def export_expenses():
    return expense_history(export="pdf")


@app.route("/expenses/export-records")
def export_records():
    return expense_history(export="records")


def expense_history(*, export=None):
    """Share filter validation and the database query for history and exports."""
    session.setdefault("expense_csrf_token", secrets.token_hex(32))
    filters = {field: request.args.get(field, "")
               for field in ("search", "category", "start_date", "end_date")}
    data = {field: value.strip() for field, value in filters.items()}
    errors = {}
    if data["category"] and data["category"] not in EXPENSE_CATEGORIES:
        errors["category"] = "Choose one of the supported business categories."
    for field in ("start_date", "end_date"):
        if data[field]:
            try:
                data[field] = parse_expense_date(data[field])
            except ValueError:
                errors[field] = "Select a valid date."
    if not errors and data["start_date"] and data["end_date"] and data["start_date"] > data["end_date"]:
        errors["end_date"] = "End Date must be on or after Start Date."
    records = [] if errors else get_expenses(**data)
    if export and not errors:
        if records:
            return expense_export(records, data, package=export == "records")
        flash("No expenses to export. Add an expense or adjust your filters.", "info")
        return redirect(url_for("expenses", **filters), code=303)
    return render_template(
        "expenses.html", expenses=records,
        filters=filters, filter_errors=errors, active_filters=any(data.values()),
        categories=EXPENSE_CATEGORIES,
    ), 400 if errors else 200


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
        dollars, cents = divmod(expense["amount"], 100)
        values["amount"] = f"{dollars}.{cents:02d}"
    errors = {}
    status = 200
    if request.method == "POST":
        values = {field: request.form.get(field, "") for field in EXPENSE_FIELDS}
        errors, data = validate_expense(values)
        if not valid_expense_csrf():
            errors["form"] = "Your form session expired. Please submit the form again."
        upload = request.files.get("receipt")
        receipt_error, extension = validate_receipt(upload)
        remove = request.form.get("remove_receipt") == "1"
        if receipt_error:
            errors["receipt"] = receipt_error
        if remove and extension:
            errors["receipt"] = "Choose either a replacement receipt or Remove receipt, then save again."
        if errors:
            status = 400
        else:
            old_receipt = expense["receipt_path"] if expense else None
            new_receipt = None
            saved = False
            try:
                if extension:
                    new_receipt = secrets.token_hex(16) + "." + extension
                    path = receipt_file(new_receipt)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("xb") as destination:
                        upload.save(destination)
                data["receipt_path"] = new_receipt or (None if remove else old_receipt)
                if expense is None:
                    create_expense(**data)
                elif not update_expense(expense["id"], **data):
                    abort(404)
                saved = True
            except (sqlite3.Error, OSError):
                app.logger.exception("Could not save expense")
                errors["form"] = "Your expense could not be saved. Please try again shortly."
                status = 503
            else:
                if old_receipt and old_receipt != data["receipt_path"]:
                    remove_receipt(old_receipt)
                if expense is not None:
                    flash("Expense updated successfully.", "success")
                    return redirect(url_for("expenses"), code=303)
                flash("Expense saved successfully.", "success")
                return redirect(url_for("add_expense"), code=303)
            finally:
                if new_receipt and not saved:
                    remove_receipt(new_receipt)
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
    expense = get_expense(id)
    if expense is None:
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
            categories=EXPENSE_CATEGORIES,
            error="Your expense could not be deleted. Please try again shortly.",
        ), 503
    remove_receipt(expense["receipt_path"])
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
