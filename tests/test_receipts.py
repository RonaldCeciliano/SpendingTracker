import io
import re
import sqlite3
from pathlib import Path

import pytest

from database.db import get_db
from test_add_expense import expense_form, expense_rows


CONTENTS = {"jpg": b"\xff\xd8\xff\xe0receipt", "jpeg": b"\xff\xd8\xff\xe0receipt",
            "png": b"\x89PNG\r\n\x1a\nreceipt", "pdf": b"%PDF-1.4\n%%EOF"}


def post(client, form, url="/expenses/add", filename="receipt.png", content=None, **fields):
    data = dict(form, **fields)
    if filename is not None:
        data["receipt"] = (io.BytesIO(CONTENTS["png"] if content is None else content), filename)
    return client.post(url, data=data)


def files(app):
    return list(Path(app.config["RECEIPT_UPLOAD_DIR"]).glob("*"))


@pytest.mark.parametrize("extension", CONTENTS)
def test_upload_and_view(client, app, expense_form, extension):
    assert post(client, expense_form, filename="../../unsafe." + extension.upper(),
                content=CONTENTS[extension]).status_code == 303
    row = expense_rows(app)[0]
    assert re.fullmatch(r"[0-9a-f]{32}\." + extension, row["receipt_path"])
    assert files(app)[0].name == row["receipt_path"]
    response = client.get(f'/expenses/{row["id"]}/receipt')
    assert response.data == CONTENTS[extension]
    assert response.mimetype == ("application/pdf" if extension == "pdf" else
                                 "image/png" if extension == "png" else "image/jpeg")
    assert response.headers["Content-Disposition"].startswith("inline")
    assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("filename,content", [("receipt.exe", b"bad"), ("receipt.png", b"<script>"),
    ("receipt.pdf", b""), ("receipt.png", CONTENTS["png"] + b"x" * (5 * 1024 * 1024))])
def test_invalid_upload(client, app, expense_form, filename, content):
    response = post(client, expense_form, filename=filename, content=content)
    assert response.status_code == 400
    assert 'id="receipt-error"' in response.text
    assert not files(app)
    assert not expense_rows(app)


def test_request_size_limit(client, app, expense_form):
    response = post(client, expense_form, content=b"x" * (6 * 1024 * 1024))
    assert response.status_code == 413
    assert "5 MiB or smaller" in response.text
    assert not files(app)
    assert not expense_rows(app)


def test_validation_and_csrf_do_not_store_files(client, app, expense_form):
    for fields in ({"vendor": ""}, {"csrf_token": "wrong"}):
        assert post(client, expense_form, **fields).status_code == 400
        assert not files(app)
    assert not expense_rows(app)


def test_receipt_lifecycle_and_filters(client, app, expense_form):
    assert post(client, expense_form).status_code == 303
    row = expense_rows(app)[0]
    url = f'/expenses/{row["id"]}/edit'
    original = files(app)[0]
    assert "View current receipt" in client.get(url).text
    assert post(client, expense_form, url, filename=None, vendor="Updated").status_code == 303
    assert expense_rows(app)[0]["receipt_path"] == original.name
    assert original.exists()
    assert "View Receipt" in client.get('/expenses?search=Updated&category=Nail+Supplies&start_date=2026-09-01').text
    assert "View Receipt" not in client.get('/expenses?search=absent').text
    assert post(client, expense_form, url, filename="new.pdf", content=CONTENTS["pdf"]).status_code == 303
    assert not original.exists()
    replacement = files(app)[0]
    assert expense_rows(app)[0]["receipt_path"] == replacement.name
    assert post(client, expense_form, url, filename=None, remove_receipt="1").status_code == 303
    assert not files(app)
    assert expense_rows(app)[0]["receipt_path"] is None
    assert "View Receipt" not in client.get('/expenses').text
    assert client.get(f'/expenses/{row["id"]}/receipt').status_code == 404


@pytest.mark.parametrize("failure", ["validation", "database", "missing", "conflict"])
def test_failed_replacement_preserves_original(client, app, expense_form, monkeypatch, failure):
    post(client, expense_form)
    original = files(app)[0]
    before = dict(expense_rows(app)[0])
    fields = {}
    if failure == "validation":
        fields["vendor"] = ""
    elif failure == "conflict":
        fields["remove_receipt"] = "1"
    elif failure == "missing":
        monkeypatch.setattr("app.update_expense", lambda *a, **k: False)
    else:
        def fail(*args, **kwargs):
            raise sqlite3.OperationalError("locked")
        monkeypatch.setattr("app.update_expense", fail)
    response = post(client, expense_form, f'/expenses/{before["id"]}/edit', **fields)
    assert response.status_code == {"database": 503, "missing": 404}.get(failure, 400)
    assert files(app) == [original]
    assert dict(expense_rows(app)[0]) == before


@pytest.mark.parametrize("with_receipt", [True, False])
def test_delete_cleanup(client, app, expense_form, with_receipt):
    post(client, expense_form, filename="receipt.png" if with_receipt else None)
    row = expense_rows(app)[0]
    assert ("View Receipt" in client.get('/expenses').text) == with_receipt
    assert client.post(f'/expenses/{row["id"]}/delete', data=expense_form).status_code == 303
    assert not expense_rows(app)
    assert not files(app)


def test_missing_and_unsafe_files(client, app, expense_form, tmp_path):
    post(client, expense_form)
    row = expense_rows(app)[0]
    path = files(app)[0]
    path.unlink()
    url = f'/expenses/{row["id"]}/receipt'
    assert client.get(url).status_code == 404
    assert client.get('/expenses/999/receipt').status_code == 404
    outside = tmp_path / "private.png"
    outside.write_bytes(CONTENTS["png"])
    path.symlink_to(outside)
    assert client.get(url).status_code == 404
    for unsafe in (str(outside), "../private.png"):
        with app.app_context():
            db = get_db()
            db.execute('UPDATE expenses SET receipt_path = ? WHERE id = ?', (unsafe, row['id']))
            db.commit()
        assert client.get(url).status_code == 404
    assert client.post(f'/expenses/{row["id"]}/delete', data=expense_form).status_code == 303
    assert outside.exists()


def test_failed_create_cleans_file(client, app, expense_form, monkeypatch):
    def fail(**kwargs):
        raise sqlite3.OperationalError("locked")
    monkeypatch.setattr("app.create_expense", fail)
    assert post(client, expense_form).status_code == 503
    assert not files(app)
    assert not expense_rows(app)


@pytest.mark.parametrize("action", ["remove", "delete"])
def test_failed_removal_or_delete_keeps_receipt(client, app, expense_form, monkeypatch, action):
    post(client, expense_form)
    before = dict(expense_rows(app)[0])
    original = files(app)[0]
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("locked")
    target = "update_expense" if action == "remove" else "delete_expense_record"
    monkeypatch.setattr("app." + target, fail)
    url = f'/expenses/{before["id"]}/' + ("edit" if action == "remove" else "delete")
    response = post(client, expense_form, url, filename=None, remove_receipt="1")
    assert response.status_code == 503
    assert dict(expense_rows(app)[0]) == before
    assert files(app) == [original]


def test_partial_file_save_failure_is_cleaned(client, app, expense_form, monkeypatch):
    def fail(upload, destination):
        destination.write(b"partial")
        raise OSError("disk full")
    monkeypatch.setattr("werkzeug.datastructures.FileStorage.save", fail)
    response = post(client, expense_form)
    assert response.status_code == 503
    assert not files(app)
    assert not expense_rows(app)


def test_oversized_edit_preserves_receipt(client, app, expense_form):
    post(client, expense_form)
    before = dict(expense_rows(app)[0])
    original = files(app)[0]
    url = f'/expenses/{before["id"]}/edit'
    response = post(client, expense_form, url, content=b"x" * (6 * 1024 * 1024))
    assert response.status_code == 413
    assert f'href="{url}"' in response.text
    assert dict(expense_rows(app)[0]) == before
    assert files(app) == [original]


def test_receipts_associated_only_with_selected_expense(client, app, expense_form):
    post(client, expense_form, filename=None, vendor="No receipt")
    post(client, expense_form, vendor="Has receipt")
    rows = expense_rows(app)
    assert rows[0]["receipt_path"] is None
    assert rows[1]["receipt_path"] == files(app)[0].name
    html = client.get('/expenses').text
    assert f'/expenses/{rows[1]["id"]}/receipt' in html
    assert f'/expenses/{rows[0]["id"]}/receipt' not in html


@pytest.mark.parametrize("extension", CONTENTS)
def test_history_receipt_modal_markup(client, app, expense_form, extension):
    from html.parser import HTMLParser

    class Buttons(HTMLParser):
        def __init__(self, html):
            super().__init__()
            self.triggers = []
            self.feed(html)

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if 'expense-receipt-open' in attrs.get('class', '').split():
                assert tag == 'button'
                self.triggers.append(attrs)

    post(client, expense_form, filename='receipt.' + extension, content=CONTENTS[extension])
    html = client.get('/expenses?search=Nail').text
    trigger, = Buttons(html).triggers
    assert trigger['type'] == 'button'
    assert trigger['data-receipt-url'] == f'/expenses/{expense_rows(app)[0]["id"]}/receipt'
    assert trigger['data-receipt-type'] == ('pdf' if extension == 'pdf' else 'image')
    assert trigger['aria-controls'] == 'expense-receipt-dialog'
    assert trigger['aria-haspopup'] == 'dialog'
    assert 'target' not in trigger
    assert 'href' not in trigger
    assert 'receipt_path' not in html
    assert '<dialog id="expense-receipt-dialog"' in html
    assert 'aria-labelledby="expense-receipt-title"' in html
    assert '>Close</button>' in html
    assert 'expense-delete-dialog' in html
