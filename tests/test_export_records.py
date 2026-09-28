from datetime import date
from html import unescape
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

import pypdfium2 as pdfium
import pytest

from database.db import get_db
from expense_records import ROOT, receipt_export_stem
from test_add_expense import expense_rows
from test_export_expenses import pdf_text
from test_filter_expenses import history
from test_receipts import CONTENTS
from test_view_expenses import save_expense


ROUTE = '/expenses/export-records'
REPORT = f'{ROOT}/Spendly Expense Report.pdf'
ISSUES = f'{ROOT}/Receipt Export Issues.txt'


def package(client, filters=None):
    response = client.get(ROUTE, query_string=filters or {})
    assert response.status_code == 200
    assert response.mimetype == 'application/zip'
    archive = ZipFile(BytesIO(response.data))
    assert archive.testzip() is None
    assert archive.namelist().count(REPORT) == 1
    assert len(archive.namelist()) == len(set(archive.namelist()))
    for name in archive.namelist():
        path = PurePosixPath(name)
        assert not path.is_absolute() and '..' not in path.parts
        assert path.parts[0] == ROOT and '\\' not in name
    return response, archive


def report_text(archive):
    with pdfium.PdfDocument(archive.read(REPORT)) as document:
        texts = []
        for page in document:
            text = page.get_textpage()
            texts.append(text.get_text_range().replace('\r\n', '\n'))
            text.close()
            page.close()
        return '\n'.join(texts)


def store_receipt(app, number, extension='png', **values):
    identifier = f'{number:032x}.{extension}'
    path = Path(app.config['RECEIPT_UPLOAD_DIR']) / identifier
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(CONTENTS[extension] + str(number).encode())
    expense_id = save_expense(app, receipt_path=identifier, **values)
    return expense_id, path


def test_response_formats_bytes_and_read_only(client, app, monkeypatch):
    class ExportDate(date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 2)
    monkeypatch.setattr('app.date', ExportDate)
    originals = [store_receipt(app, index, extension, vendor='Supplier ' + extension)
                 for index, extension in enumerate(CONTENTS, 1)]
    save_expense(app, vendor='No receipt', notes='Keep this note in the report')
    before = [dict(row) for row in expense_rows(app)]
    response, archive = package(client)
    assert response.headers['Content-Disposition'] == 'attachment; filename=spendly-expense-records-2027-01-02.zip'
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert len(archive.namelist()) == 5
    assert ISSUES not in archive.namelist()
    for expense_id, path in originals:
        name = f'{ROOT}/Receipts/2026-09-22_Supplier-{path.suffix[1:]}_74.38{path.suffix}'
        assert archive.read(name) == path.read_bytes()
        assert client.get(f'/expenses/{expense_id}/receipt').data == path.read_bytes()
        assert path.name.encode() not in response.data
    assert app.config['RECEIPT_UPLOAD_DIR'].encode() not in response.data
    text = report_text(archive)
    assert text == pdf_text(client.get('/expenses/export'))
    assert 'No receipt' in text and 'Keep this note in the report' in text
    assert 'Expenses included: 5' in text
    assert 'Total amount spent: $371.90' in text
    assert [dict(row) for row in expense_rows(app)] == before
    assert client.get('/').status_code == 200


@pytest.mark.parametrize('filters,expected', [
    ({}, [2, 3, 1, 0]),
    ({'search': ' POLISH '}, [1, 0]),
    ({'category': 'Nail Supplies'}, [3, 0]),
    ({'start_date': '2026-09-15'}, [2, 3, 1]),
    ({'end_date': '2026-09-15'}, [3, 1, 0]),
    ({'start_date': '2026-09-15', 'end_date': '2026-09-15'}, [3, 1]),
    ({'search': 'polish', 'category': 'Tools & Equipment',
      'start_date': '2026-09-15', 'end_date': '2026-09-15'}, [1]),
])
def test_shared_filters_pdf_totals_order_and_links(client, app, history, filters, expected):
    paths = []
    for index, expense_id in enumerate(history):
        path = Path(app.config['RECEIPT_UPLOAD_DIR']) / f'{index:032x}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(CONTENTS['png'] + bytes([index]))
        paths.append(path)
        with app.app_context():
            db = get_db()
            db.execute('UPDATE expenses SET receipt_path = ? WHERE id = ?', (path.name, expense_id))
            db.commit()
    _, archive = package(client, filters)
    assert report_text(archive) == pdf_text(client.get('/expenses/export', query_string=filters))
    assert f'Expenses included: {len(expected)}' in report_text(archive)
    assert f'Total amount spent: ${len(expected) * 7438 // 100}.{len(expected) * 7438 % 100:02d}' in report_text(archive)
    names = [name for name in archive.namelist() if '/Receipts/' in name]
    assert [archive.read(name) for name in names] == [paths[index].read_bytes() for index in expected]
    html = client.get('/expenses', query_string=filters).text
    assert html.count('class="expense-history-card"') == len(expected)
    link = unescape(re.search(r'href="([^"]+)"\s+aria-describedby="expense-export-scope expense-package-scope"', html)[1])
    assert urlsplit(link).path == ROUTE
    assert parse_qs(urlsplit(link).query) == {key: [value] for key, value in filters.items()}
    assert 'Export PDF' in html and 'Export Records Package' in html


@pytest.mark.parametrize('filters', [
    {'category': 'invalid'}, {'start_date': '2026-02-29'}, {'end_date': 'bad'},
    {'start_date': '2026-09-30', 'end_date': '2026-09-01'},
])
def test_invalid_filters(client, monkeypatch, filters):
    def no_query(**kwargs):
        pytest.fail('Invalid filters must not query expenses')
    monkeypatch.setattr('app.get_expenses', no_query)
    response = client.get(ROUTE, query_string=filters)
    assert response.status_code == 400
    assert response.data == client.get('/expenses', query_string=filters).data
    assert 'Content-Disposition' not in response.headers


@pytest.mark.parametrize('filters', [{}, {'search': 'absent', 'category': 'Other',
                                         'start_date': '2026-01-01', 'end_date': '2026-12-31'}])
def test_empty_result_preserves_filters(client, app, filters):
    if filters:
        store_receipt(app, 1)
    response = client.get(ROUTE, query_string=filters)
    assert response.status_code == 303
    assert urlsplit(response.location).path == '/expenses'
    assert parse_qs(urlsplit(response.location).query) == {key: [value] for key, value in filters.items()}
    assert 'No expenses to export.' in client.get(response.location).text
    assert 'Content-Disposition' not in response.headers


@pytest.mark.parametrize('vendor,expected', [
    ('  Sally Beauty  ', 'Sally-Beauty'),
    ('../../Walmart\\:<>"|?*', 'Walmart'),
    ('/absolute/path', 'absolute-path'),
    ('C:\\receipts\\Vendor', 'C-receipts-Vendor'),
    ('Café 東京', 'Café-東京'),
    ('Cafe\u0301', 'Café'),
    (' . / \\ : " ? * ', 'Vendor'),
    ('A' * 500, 'A' * 100),
    ('東' * 200, '東' * 33),
    ('safe\x00\n\u202eevil', 'safe-evil'),
])
def test_safe_names(vendor, expected):
    assert receipt_export_stem({'date': '2026-09-24', 'vendor': vendor, 'amount': 6164}) == f'2026-09-24_{expected}_61.64'


@pytest.mark.parametrize('cents,amount', [(0, '0.00'), (1, '0.01'), (29, '0.29'),
                                         (125000, '1250.00'), (9223372036854775807, '92233720368547758.07')])
def test_integer_cent_names(client, app, cents, amount):
    store_receipt(app, 1, vendor='Vendor', amount=cents)
    _, archive = package(client)
    assert f'{ROOT}/Receipts/2026-09-22_Vendor_{amount}.png' in archive.namelist()


def test_duplicates_sanitization_and_case_collisions(client, app):
    originals = [store_receipt(app, index, vendor=vendor)[1] for index, vendor in enumerate(
        ['Vendor', 'Vendor', '../Vendor', 'vendor'], 1)]
    _, archive = package(client)
    names = [name for name in archive.namelist() if '/Receipts/' in name]
    assert [PurePosixPath(name).name for name in names] == [
        '2026-09-22_vendor_74.38.png', '2026-09-22_Vendor_74.38_2.png',
        '2026-09-22_Vendor_74.38_3.png', '2026-09-22_Vendor_74.38_4.png']
    assert [archive.read(name) for name in names] == [path.read_bytes() for path in reversed(originals)]
    assert package(client)[1].namelist() == archive.namelist()


@pytest.mark.parametrize('failure', ['missing', 'permission', 'directory', 'symlink', 'traversal', 'absolute', 'invalid'])
def test_unavailable_receipts(client, app, tmp_path, monkeypatch, failure):
    _, valid = store_receipt(app, 1, vendor='Available')
    expense_id, bad = store_receipt(app, 2, vendor='Unavailable')
    if failure == 'permission':
        original = Path.read_bytes
        def read(path):
            if path == bad:
                raise PermissionError('private internal path')
            return original(path)
        monkeypatch.setattr(Path, 'read_bytes', read)
    else:
        bad.unlink()
        if failure == 'directory':
            bad.mkdir()
        elif failure == 'symlink':
            bad.symlink_to(valid)
        elif failure in ('traversal', 'absolute', 'invalid'):
            reference = {'traversal': '../private.png', 'absolute': str(tmp_path / 'private.png'),
                         'invalid': 'not-generated.png'}[failure]
            with app.app_context():
                db = get_db()
                db.execute('UPDATE expenses SET receipt_path = ? WHERE id = ?', (reference, expense_id))
                db.commit()
    response, archive = package(client)
    assert len(archive.namelist()) == 3
    assert archive.read(f'{ROOT}/Receipts/2026-09-22_Available_74.38.png') == valid.read_bytes()
    issues = archive.read(ISSUES).decode()
    assert '2026-09-22_Unavailable_74.38' in issues
    assert 'Unavailable' in report_text(archive)
    for value in (bad.name, str(bad), str(tmp_path), 'private.png', 'not-generated.png', 'Traceback'):
        assert value not in issues
        assert value.encode() not in response.data


def test_no_receipts(client, app):
    save_expense(app, vendor='No receipt')
    _, archive = package(client)
    assert archive.namelist() == [REPORT]
    assert 'No receipt' in report_text(archive)
