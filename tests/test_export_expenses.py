from datetime import date
from html import unescape
import re
from urllib.parse import parse_qs, urlsplit

import pypdfium2 as pdfium
import pytest

from test_add_expense import expense_rows
from test_filter_expenses import history
from test_view_expenses import save_expense


HEADERS = ('Date', 'Vendor', 'Amount', 'Category', 'Payment Method', 'Description', 'Receipt')


def pdf_pages(response):
    assert response.status_code == 200
    assert response.mimetype == 'application/pdf'
    assert response.data.startswith(b'%PDF-')
    with pdfium.PdfDocument(response.data) as document:
        result = []
        for page in document:
            assert page.get_size() == (792, 612)
            text = page.get_textpage()
            result.append(text.get_text_range().replace('\r\n', '\n'))
            text.close()
            page.close()
        return result


def pdf_text(response):
    return '\n'.join(pdf_pages(response))


def test_all_headers_order_download_and_read_only(client, app, history, monkeypatch):
    class ExportDate(date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 2)
    monkeypatch.setattr('app.date', ExportDate)
    before = [dict(row) for row in expense_rows(app)]
    response = client.get('/expenses/export')
    text = pdf_text(response)
    assert 'Spendly' in text and 'Expense Report' in text
    assert 'Generated: 01-02-2027' in text
    assert 'Expenses included: 4' in text
    assert 'Total amount spent: $297.52' in text
    assert 'Scope: All expenses' in text
    header_text = ' '.join(text.split())
    positions = [header_text.index(label, header_text.index('Scope:')) for label in HEADERS]
    assert positions == sorted(positions)
    assert text.index('09-30-2026') < text.index('Local Supply') < text.index('Tool Shop') < text.index('09-01-2026')
    assert response.headers['Content-Disposition'] == 'attachment; filename=spendly-expense-report-2027-01-02.pdf'
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert [dict(row) for row in expense_rows(app)] == before
    assert client.get('/').status_code == 200
    assert client.get('/expenses').status_code == 200


@pytest.mark.parametrize('filters,expected', [
    ({'search': ' POLISH '}, ['Tool Shop', 'Sally Beauty']),
    ({'category': 'Nail Supplies'}, ['Local Supply', 'Sally Beauty']),
    ({'start_date': '2026-09-15'}, ['Sally Beauty', 'Local Supply', 'Tool Shop']),
    ({'end_date': '2026-09-15'}, ['Local Supply', 'Tool Shop', 'Sally Beauty']),
    ({'start_date': '2026-09-15', 'end_date': '2026-09-15'}, ['Local Supply', 'Tool Shop']),
    ({'search': 'polish', 'category': 'Tools & Equipment',
      'start_date': '2026-09-15', 'end_date': '2026-09-15'}, ['Tool Shop']),
])
def test_filters(client, history, filters, expected):
    text = pdf_text(client.get('/expenses/export', query_string=filters))
    assert f'Expenses included: {len(expected)}' in text
    totals = {1: '$74.38', 2: '$148.76', 3: '$223.14'}
    assert f'Total amount spent: {totals[len(expected)]}' in text
    table = text[text.index('Receipt'):].split('Expense notes')[0]
    positions = [table.index(vendor) for vendor in expected]
    assert positions == sorted(positions)
    for vendor in {'Sally Beauty', 'Local Supply', 'Tool Shop'} - set(expected):
        assert vendor not in table
    for field, label in [('search', 'Search'), ('category', 'Category')]:
        if field in filters:
            assert f'{label}: {filters[field].strip()}' in text
    for field in ('start_date', 'end_date'):
        if field in filters:
            year, month, day = filters[field].split('-')
            assert f'{month}-{day}-{year}' in text.split('Receipt')[0]
    html = client.get('/expenses', query_string=filters).text
    assert html.count('class="expense-history-card"') == len(expected)
    link = unescape(re.search(r'href="([^"]+)"\s+aria-describedby="expense-export-scope"', html)[1])
    assert parse_qs(urlsplit(link).query) == {key: [value] for key, value in filters.items()}
    assert 'Export PDF' in html
    assert 'Exports expenses matching the current filters.' in html
    assert pdf_text(client.get(link)) == text


@pytest.mark.parametrize('cents,expected', [
    (0, '$0.00'), (1, '$0.01'), (29, '$0.29'), (1250, '$12.50'),
    (7438, '$74.38'), (125000, '$1,250.00'), (9223372036854775807, '$92,233,720,368,547,758.07'),
])
def test_exact_integer_amounts(client, app, cents, expected):
    save_expense(app, amount=cents, date='2024-02-29')
    text = pdf_text(client.get('/expenses/export'))
    assert text.count(expected) == 2
    assert '02-29-2024' in text


def test_total_can_exceed_sqlite_integer_limit(client, app):
    for _ in range(2):
        save_expense(app, amount=9223372036854775807)
    assert 'Total amount spent: $184,467,440,737,095,516.14' in pdf_text(client.get('/expenses/export'))


@pytest.mark.parametrize('optional', [None, ''])
def test_optional_fields_and_receipts(client, app, optional):
    save_expense(app, vendor='Without receipt', payment_method=optional, description=optional, notes=optional)
    receipt = 'a' * 32 + '.png'
    save_expense(app, vendor='With receipt', receipt_path=receipt)
    response = client.get('/expenses/export')
    text = pdf_text(response)
    assert 'Yes' in text.split('Without receipt')[0]
    assert 'No' in text.split('Without receipt')[1]
    assert 'None' not in text
    assert 'Expense notes' not in text
    assert receipt not in text and receipt.encode() not in response.data
    assert app.config['RECEIPT_UPLOAD_DIR'] not in text
    assert 'ID' not in text


def test_literal_text_unicode_and_notes(client, app):
    save_expense(app, vendor='Café & École', payment_method='Card, cash',
                 description='<b>Literal</b> "quotes" +SUM(1,2)',
                 notes='Résumé — paid €5\nSecond line: naïve, Ω, Ж')
    text = pdf_text(client.get('/expenses/export'))
    for value in ['Café & École', '<b>Literal</b>', '"quotes"', '+SUM(1,2)',
                  'Résumé — paid €5', 'Second line: naïve, Ω, Ж']:
        assert value in text
    assert text.index('Expense notes') < text.index('Résumé')


def test_unsupported_glyphs_are_explicit(client, app):
    save_expense(app, vendor='東京 🧾')
    text = pdf_text(client.get('/expenses/export'))
    assert '[U+6771][U+4EAC] [U+1F9FE]' in ' '.join(text.split())
    assert 'Characters unavailable in the report font' in text


@pytest.mark.parametrize('search', ['%', '_', "' OR 1=1 --", 'ÉCOLE'])
def test_export_literal_unicode_search(client, app, search):
    save_expense(app, vendor='Prefix ' + search.lower())
    save_expense(app, vendor='Unrelated')
    text = pdf_text(client.get('/expenses/export', query_string={'search': search}))
    assert 'Expenses included: 1' in text
    assert 'Prefix ' + search.lower() in text
    assert 'Unrelated' not in text


def test_long_report_repeats_headers_and_paginates(client, app):
    for index in range(45):
        save_expense(app, vendor=f'Supplier {index:02d} ' + 'Long vendor ' * 12,
                     description='Detailed purchase, supplies & equipment. ' * 20,
                     notes='Notes for this expense. ' * 200 if index == 0 else None)
    pages = pdf_pages(client.get('/expenses/export'))
    assert len(pages) > 2
    assert 'Expenses included: 45' in pages[0]
    for number, text in enumerate(pages, 1):
        assert f'Page {number}' in text
        if 'Supplier' in text and 'Expense notes' not in text and 'Notes for this expense' not in text:
            assert all(label in text for label in HEADERS if label != 'Payment Method')
            assert 'Payment' in text and 'Method' in text
    combined = '\n'.join(pages)
    for index in range(45):
        assert f'Supplier {index:02d}' in combined
    assert ' '.join(combined.split()).count('Notes for this expense.') == 200


def test_single_tall_row_can_split(client, app):
    save_expense(app, description='x\n' * 499, notes='n' * 5000)
    pages = pdf_pages(client.get('/expenses/export'))
    assert len(pages) > 2
    assert sum(text.count('x') for text in pages) >= 499


@pytest.mark.parametrize('filters', [{}, {'search': 'absent', 'category': 'Other'}])
def test_empty_export(client, filters):
    response = client.get('/expenses/export', query_string=filters)
    assert response.status_code == 303
    assert 'Content-Disposition' not in response.headers
    assert urlsplit(response.location).path == '/expenses'
    assert parse_qs(urlsplit(response.location).query) == {key: [value] for key, value in filters.items()}
    page = client.get(response.location)
    assert 'No expenses to export.' in page.text
    assert ('No expenses match your filters' if filters else 'No expenses yet') in page.text


@pytest.mark.parametrize('filters', [
    {'category': 'invalid'}, {'start_date': '2026-02-29'}, {'end_date': 'bad'},
    {'start_date': '2026-09-30', 'end_date': '2026-09-01'},
])
def test_invalid_filters_match_history(client, monkeypatch, filters):
    def no_query(**kwargs):
        pytest.fail('Invalid filters must not query expenses')
    monkeypatch.setattr('app.get_expenses', no_query)
    page = client.get('/expenses', query_string=filters)
    export = client.get('/expenses/export', query_string=filters)
    assert page.status_code == export.status_code == 400
    assert page.data == export.data
    assert 'Content-Disposition' not in export.headers


def test_no_matches_does_not_export_unfiltered_records(client, app):
    save_expense(app, vendor='Existing record')
    response = client.get('/expenses/export?search=absent', follow_redirects=True)
    assert response.status_code == 200
    assert response.mimetype == 'text/html'
    assert 'No expenses to export.' in response.text
    assert 'No expenses match your filters' in response.text
    assert 'Existing record' not in response.text
