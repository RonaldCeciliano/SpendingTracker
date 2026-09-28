"""In-memory, printable expense reports. Database access stays in database/db.py."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle


# Reuse the licensed fonts already distributed with ExpenseHQ's receipt viewer.
FONT_DIR = Path(__file__).parent / 'static/vendor/pdfjs/standard_fonts'
for name, filename in [('ExpenseHQ', 'LiberationSans-Regular.ttf'),
                       ('ExpenseHQBold', 'LiberationSans-Bold.ttf')]:
    pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / filename)))

HEADERS = ('Date', 'Vendor', 'Amount', 'Category', 'Payment Method', 'Description', 'Receipt')


def build_expense_report(records, filters, generated_date, format_date, format_amount):
    """Return a PDF buffer; all money arithmetic uses integer cents."""
    output = BytesIO()
    ink = colors.HexColor('#25352f')
    body = ParagraphStyle('body', fontName='ExpenseHQ', fontSize=9, leading=12,
                          textColor=ink, splitLongWords=True)
    bold = ParagraphStyle('bold', parent=body, fontName='ExpenseHQBold')
    amount_style = ParagraphStyle('amount', parent=body, alignment=TA_RIGHT)
    amount_heading = ParagraphStyle('amount-heading', parent=bold, alignment=TA_RIGHT)
    receipt_style = ParagraphStyle('receipt', parent=body, alignment=TA_CENTER)
    receipt_heading = ParagraphStyle('receipt-heading', parent=bold, alignment=TA_CENTER)
    heading = ParagraphStyle('heading', parent=bold, fontSize=18, leading=23, spaceAfter=4)
    section = ParagraphStyle('section', parent=bold, fontSize=12, leading=16,
                             spaceBefore=14, spaceAfter=8, keepWithNext=True)
    note_heading = ParagraphStyle('note-heading', parent=bold, spaceBefore=10,
                                  spaceAfter=4, keepWithNext=True)
    unsupported = set()
    supported = pdfmetrics.getFont('ExpenseHQ').face.charToGlyph

    def paragraph(value, style=body):
        text = str(value or '').replace('\r\n', '\n').replace('\r', '\n').replace('\t', '    ')
        # Preserve unsupported characters explicitly instead of printing missing-glyph boxes.
        parts = []
        for char in text:
            if char == '\n' or ord(char) in supported:
                parts.append(char)
            else:
                unsupported.add(char)
                parts.append(f'[U+{ord(char):04X}]')
        return Paragraph(escape(''.join(parts)).replace('\n', '<br/>'), style)

    story = [paragraph('ExpenseHQ', bold), paragraph('Expense Report', heading),
             paragraph(f'Generated: {format_date(generated_date.isoformat())}'), Spacer(1, 10)]
    summary = [paragraph(f'Expenses included: {len(records)}', bold),
               paragraph(f'Total amount spent: {format_amount(sum(row["amount"] for row in records))}', bold)]
    if filters['start_date'] or filters['end_date']:
        start = format_date(filters['start_date']) if filters['start_date'] else 'Any start date'
        end = format_date(filters['end_date']) if filters['end_date'] else 'Any end date'
        summary.append(paragraph(f'Date range: {start} to {end} (inclusive)'))
    if filters['category']:
        summary.append(paragraph(f'Category: {filters["category"]}'))
    if filters['search']:
        summary.append(paragraph(f'Search: {filters["search"]}'))
    if not any(filters.values()):
        summary.append(paragraph('Scope: All expenses'))
    summary_table = LongTable([[summary]], colWidths=[720], hAlign='LEFT')
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f5f7f5')),
        ('LINEBEFORE', (0, 0), (0, -1), 2, colors.HexColor('#9baaa0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.extend([summary_table, Spacer(1, 10)])

    rows = [[paragraph(label, amount_heading if label == 'Amount' else
                       receipt_heading if label == 'Receipt' else bold) for label in HEADERS]]
    for row in records:
        rows.append([
            paragraph(format_date(row['date'])), paragraph(row['vendor']),
            paragraph(format_amount(row['amount']), amount_style), paragraph(row['category']),
            paragraph(row['payment_method']), paragraph(row['description']),
            paragraph('Yes' if row['receipt_path'] else 'No', receipt_style),
        ])
    table = LongTable(rows, colWidths=[64, 110, 128, 88, 72, 210, 48],
                      repeatRows=1, splitByRow=1, splitInRow=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e4ebe6')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f7f5')]),
        ('LINEBELOW', (0, 0), (-1, 0), 0.7, colors.HexColor('#9baaa0')),
        ('LINEBELOW', (0, 1), (-1, -1), 0.3, colors.HexColor('#dce3de')),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.append(table)
    notes = [row for row in records if row['notes'] and row['notes'].strip()]
    if notes:
        story.append(paragraph('Expense notes', section))
        for row in notes:
            story.append(paragraph(
                f'{format_date(row["date"])} · {row["vendor"]} · {format_amount(row["amount"])}', note_heading))
            story.append(paragraph(row['notes']))
    if unsupported:
        story.append(Spacer(1, 12))
        story.append(paragraph('Characters unavailable in the report font are shown as Unicode codes [U+…].'))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#dce3de'))
        canvas.line(36, 31, 756, 31)
        canvas.setFont('ExpenseHQ', 8)
        canvas.setFillColor(ink)
        canvas.drawString(36, 19, 'ExpenseHQ · Expense Report')
        canvas.drawRightString(756, 19, f'Page {document.page}')
        canvas.restoreState()

    document = SimpleDocTemplate(output, pagesize=landscape(letter),
                                 leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=42,
                                 title='ExpenseHQ Expense Report', author='ExpenseHQ')
    # Frame padding is included inside the margins; reserve it in the table width.
    document.leftMargin = 30
    document.rightMargin = 30
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    output.seek(0)
    return output
