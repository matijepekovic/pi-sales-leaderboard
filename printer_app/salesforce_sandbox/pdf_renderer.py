"""PDF renderer for normalized MOD records.

This module owns MOD-sheet presentation only. It knows nothing about Salesforce,
Gallery, OCR, repositories, or printer queues.
"""
from __future__ import annotations

from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


PAGE_MARGIN_X = 0.5 * cm
PAGE_MARGIN_Y = 0.55 * cm
PRODUCT_COLORS = (
    ('roofing', 'Roofing', '#00B0F0'),
    ('siding', 'Siding', '#92D050'),
    ('bath', 'Bath', '#FF69B4'),
    ('gutters', 'Gutters', '#00B0F0'),
    ('windows', 'Windows', '#FFA500'),
    ('doors', 'Doors', '#FFA500'),
    ('other', 'Other', '#D9D9D9'),
    ('walk-in tubs', 'Walk-In Tubs', '#FF69B4'),
    ('solar', 'Solar', '#FFF200'),
)


def _p(style, label, value=''):
    return Paragraph(f'<b>{escape(label)}</b>{escape(str(value or ""))}', style)


def _product(style, value, color_code):
    value = str(value or '')
    if not color_code:
        return _p(style, 'Product Interest: ', value)
    lower = value.casefold()
    chunks = ['<b>Product Interest: </b>']
    for needle, label, color in PRODUCT_COLORS:
        if needle in lower:
            chunks.append(
                f'<font backColor="{color}">{escape(label)}</font>&nbsp;'
            )
    if len(chunks) == 1 and value:
        chunks.append(escape(value))
    return Paragraph(''.join(chunks), style)


def _canvass(style, value, color_code):
    value = escape(str(value or ''))
    if color_code and value:
        value = f'<font backColor="#FFF200">{value}</font>'
    return Paragraph('<b>Canvass Set By: </b>' + value, style)


def _mod_table(record, color_code, available_width):
    style = ParagraphStyle(
        'mod-cell',
        fontName='Helvetica',
        fontSize=8.5,
        leading=9.4,
        textColor=colors.black,
        spaceAfter=0,
        spaceBefore=0,
    )
    rows = 13
    data = [['' for _ in range(12)] for _ in range(rows)]

    data[0][0] = _p(style, 'Work Order Number: ', record.work_order_number)
    data[0][4] = _p(style, 'Local Scheduled Start Time: ', record.local_scheduled_start_time)
    data[0][8] = _canvass(style, record.canvass_set_by, color_code)

    data[1][0] = _p(style, 'Lead Name: ', record.lead_name)
    data[1][4] = _p(style, 'Address: ', record.address)
    data[1][8] = _p(style, 'Phone: ', record.phone)
    data[1][10] = _p(style, 'Power Questions ', '[ ]')

    data[2][0] = _p(style, 'Scheduled Start: ', record.scheduled_start)
    data[2][3] = _p(
        style,
        'Assigned Service Resource: ',
        ', '.join(record.assigned_service_resources),
    )
    data[2][8] = _p(style, 'Set By: ', record.set_by)
    data[2][10] = _p(style, 'T Close:')

    data[3][0] = _p(style, 'Work Type: ', record.work_type)
    data[3][3] = _product(style, record.product_interest, color_code)
    data[3][6] = _p(style, 'Source: ', record.source)
    data[3][8] = _p(style, 'Sub Source: ', record.sub_source)
    data[3][10] = _p(style, 'Hover / Flir:')

    data[4][0] = _p(style, 'Lead Description: ', record.lead_description)
    data[4][5] = _p(style, 'Start Price:')
    data[4][7] = _p(style, 'Final Price:')
    data[4][9] = _p(style, 'Deposit/Payment:')

    data[5][5] = _p(style, 'MOD Notes:')
    data[7][0] = _p(style, 'Fin Checklist')
    data[7][2] = _p(style, 'Bid Sheets')
    data[7][4] = _p(style, 'Pictures')
    data[8][0] = _p(style, 'Dispo:')
    data[9][0] = _p(style, 'Call 1:')
    data[9][2] = _p(style, 'Need:')
    data[10][0] = _p(style, 'Call 2:')
    data[11][0] = _p(style, '90 Min:')
    data[11][2] = _p(style, 'Want:')

    col_widths = [available_width / 12.0] * 12
    row_heights = [
        12, 25, 25, 25, 12, 18, 10, 25, 12, 12, 12, 12, 12,
    ]
    table = Table(data, colWidths=col_widths, rowHeights=row_heights)
    spans = [
        ((0, 0), (3, 0)), ((4, 0), (7, 0)), ((8, 0), (11, 0)),
        ((0, 1), (3, 1)), ((4, 1), (7, 1)), ((8, 1), (9, 1)), ((10, 1), (11, 1)),
        ((0, 2), (2, 2)), ((3, 2), (7, 2)), ((8, 2), (9, 2)), ((10, 2), (11, 2)),
        ((0, 3), (2, 3)), ((3, 3), (5, 3)), ((6, 3), (7, 3)), ((8, 3), (9, 3)), ((10, 3), (11, 3)),
        ((0, 4), (4, 6)),
        ((5, 4), (6, 4)), ((7, 4), (8, 4)), ((9, 4), (11, 4)),
        ((5, 5), (11, 12)),
        ((0, 7), (1, 7)), ((2, 7), (3, 7)),
        ((0, 8), (4, 8)),
        ((0, 9), (1, 9)), ((2, 9), (4, 10)),
        ((0, 10), (1, 10)),
        ((0, 11), (1, 11)), ((2, 11), (4, 12)),
        ((0, 12), (1, 12)),
    ]
    commands = [
        ('GRID', (0, 0), (-1, -1), 1.34, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 1.0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1.0),
        ('TOPPADDING', (0, 0), (-1, -1), 1.0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.0),
    ]
    commands.extend(('SPAN', start, end) for start, end in spans)
    table.setStyle(TableStyle(commands))
    return table


def render_mod_pdf(records, *, color_code=False):
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=letter,
        leftMargin=PAGE_MARGIN_X,
        rightMargin=PAGE_MARGIN_X,
        topMargin=PAGE_MARGIN_Y,
        bottomMargin=PAGE_MARGIN_Y,
        title='MOD Sheet',
        author='Stats Salesforce Sandbox',
    )
    available_width = letter[0] - PAGE_MARGIN_X * 2
    story = []
    records = tuple(records)
    if not records:
        style = ParagraphStyle('empty', fontName='Helvetica', fontSize=11, leading=14)
        story.append(Paragraph('No appointments matched the selected MOD Sheet filters.', style))
    else:
        for index, record in enumerate(records):
            block = [_mod_table(record, color_code, available_width)]
            if index + 1 < len(records):
                block.append(Spacer(1, 18))
            story.append(KeepTogether(block))
    doc.build(story)
    return stream.getvalue()
