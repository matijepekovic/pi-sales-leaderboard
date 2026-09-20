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
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


PAGE_MARGIN_X = 0.5 * cm
PAGE_MARGIN_Y = 0.55 * cm

# Measured from the reference Salesforce Visualforce PDF supplied for parity.
# The Visualforce renderer does not end up using twelve equal visible columns;
# its resolved grid is ten equal columns across a 571.65pt table.
VISUALFORCE_TABLE_WIDTH = 571.65
VISUALFORCE_COLUMNS = 10
VISUALFORCE_ROW_HEIGHTS = (
    13.5,   # one-row-height
    25.5,   # two-row-height
    25.5,
    25.5,
    13.5,   # Start / Final / Deposit row
    33.75,  # Lead Description continuation + MOD Notes start
    25.5,   # Fin Checklist / Bid Sheets / Pictures
    13.5,   # Dispo
    13.5,   # Call 1
    16.5,   # Call 2
    30.0,   # 90 Min / Want
)

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


CELL_VERTICAL_PADDING = 1.68
FIT_VALUE_SIZES = (9, 8.5, 8, 7.5, 7)


def _content_height(*rows):
    return sum(VISUALFORCE_ROW_HEIGHTS[row] for row in rows) - CELL_VERTICAL_PADDING


class _FitClipParagraph(Flowable):
    """Shrink only the value text to fit a fixed Visualforce cell, then clip."""

    def __init__(self, label, value, *, max_height, value_background=''):
        super().__init__()
        self.label = str(label or '')
        self.value = str(value or '')
        self.max_height = float(max_height)
        self.value_background = str(value_background or '')
        self.value_font_size = FIT_VALUE_SIZES[0]
        self.clipped = False
        self._paragraph = None
        self._paragraph_height = 0

    def _paragraph_for(self, value_size):
        style = ParagraphStyle(
            'mod-fit-cell',
            fontName='Times-Roman',
            fontSize=9,
            leading=10,
            textColor=colors.black,
            spaceAfter=0,
            spaceBefore=0,
        )
        escaped_value = escape(self.value)
        if self.value_background and escaped_value:
            value_markup = (
                f'<font size="{value_size}" backColor="{self.value_background}">'
                f'{escaped_value}</font>'
            )
        else:
            value_markup = f'<font size="{value_size}">{escaped_value}</font>'
        return Paragraph(
            f'<b>{escape(self.label)}</b>{value_markup}',
            style,
        )

    def wrap(self, availWidth, availHeight):
        self.width = max(0, availWidth)
        chosen = None
        chosen_height = 0
        for value_size in FIT_VALUE_SIZES:
            paragraph = self._paragraph_for(value_size)
            _, paragraph_height = paragraph.wrap(self.width, 10000)
            chosen = paragraph
            chosen_height = paragraph_height
            self.value_font_size = value_size
            if paragraph_height <= self.max_height:
                self.clipped = False
                break
        else:
            self.clipped = True

        self._paragraph = chosen
        self._paragraph_height = chosen_height
        self.height = min(chosen_height, self.max_height)
        return self.width, self.height

    def draw(self):
        if self._paragraph is None:
            self.wrap(self.width, self.max_height)

        canv = self.canv
        canv.saveState()
        path = canv.beginPath()
        path.rect(0, 0, self.width, self.height)
        canv.clipPath(path, stroke=0, fill=0)
        self._paragraph.drawOn(
            canv,
            0,
            self.height - self._paragraph_height,
        )
        canv.restoreState()


def _fit(label, value, *rows, value_background=''):
    return _FitClipParagraph(
        label,
        value,
        max_height=_content_height(*rows),
        value_background=value_background,
    )


class _PowerQuestions(Flowable):
    """Match the narrow two-line Visualforce label plus unchecked box."""

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        self.height = 20
        return availWidth, self.height

    def draw(self):
        canv = self.canv
        canv.setFillColor(colors.black)
        canv.setStrokeColor(colors.HexColor('#d9d9d9'))
        canv.setLineWidth(0.5)
        canv.setFont('Times-Bold', 9)
        canv.drawString(0, 11, 'Power')
        canv.drawString(0, 1, 'Questions')
        label_width = stringWidth('Questions', 'Times-Bold', 9)
        box_x = min(label_width + 3, max(0, self.width - 6))
        canv.rect(box_x, 2, 5, 5, stroke=1, fill=0)


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
    return _fit(
        'Canvass Set By: ',
        value,
        0,
        value_background='#FFF200' if color_code else '',
    )


def _mod_table(record, color_code):
    style = ParagraphStyle(
        'mod-cell',
        fontName='Times-Roman',
        fontSize=9,
        leading=10,
        textColor=colors.black,
        spaceAfter=0,
        spaceBefore=0,
    )

    rows = len(VISUALFORCE_ROW_HEIGHTS)
    data = [['' for _ in range(VISUALFORCE_COLUMNS)] for _ in range(rows)]

    # Row 1: resolved by Salesforce's PDF renderer as 3 / 4 / 3 columns.
    data[0][0] = _fit('Work Order Number: ', record.work_order_number, 0)
    data[0][3] = _fit('Local Scheduled Start Time: ', record.local_scheduled_start_time, 0)
    data[0][7] = _canvass(style, record.canvass_set_by, color_code)

    # Row 2: 3 / 4 / 2 / 1.
    data[1][0] = _fit('Lead Name: ', record.lead_name, 1)
    data[1][3] = _fit('Address: ', record.address, 1)
    data[1][7] = _fit('Phone: ', record.phone, 1)
    data[1][9] = _PowerQuestions()

    # Row 3: 2 / 5 / 2 / 1.
    data[2][0] = _fit('Scheduled Start: ', record.scheduled_start, 2)
    data[2][2] = _fit(
        'Assigned Service Resource: ',
        ', '.join(record.assigned_service_resources),
        2,
    )
    data[2][7] = _fit('Set By: ', record.set_by, 2)
    data[2][9] = _p(style, 'T Close:')

    # Row 4: 2 / 3 / 2 / 2 / 1.
    data[3][0] = _fit('Work Type: ', record.work_type, 3)
    data[3][2] = _product(style, record.product_interest, color_code)
    data[3][5] = _fit('Source: ', record.source, 3)
    data[3][7] = _fit('Sub Source: ', record.sub_source, 3)
    data[3][9] = _p(style, 'Hover / Flir:')

    # Lower worksheet.
    data[4][0] = _fit('Lead Description: ', record.lead_description, 4, 5)
    data[4][4] = _p(style, 'Start Price:')
    data[4][6] = _p(style, 'Final Price:')
    data[4][8] = _p(style, 'Deposit/Payment:')
    data[5][4] = _p(style, 'MOD Notes:')

    data[6][0] = _p(style, 'Fin Checklist')
    data[6][1] = _p(style, 'Bid Sheets')
    data[6][3] = _p(style, 'Pictures')
    data[7][0] = _p(style, 'Dispo:')
    data[8][0] = _p(style, 'Call 1:')
    data[8][1] = _p(style, 'Need:')
    data[9][0] = _p(style, 'Call 2:')
    data[10][0] = _p(style, '90 Min:')
    data[10][1] = _p(style, 'Want:')

    col_widths = [VISUALFORCE_TABLE_WIDTH / VISUALFORCE_COLUMNS] * VISUALFORCE_COLUMNS
    table = Table(
        data,
        colWidths=col_widths,
        rowHeights=list(VISUALFORCE_ROW_HEIGHTS),
        hAlign='CENTER',
    )

    spans = [
        ((0, 0), (2, 0)), ((3, 0), (6, 0)), ((7, 0), (9, 0)),
        ((0, 1), (2, 1)), ((3, 1), (6, 1)), ((7, 1), (8, 1)),
        ((0, 2), (1, 2)), ((2, 2), (6, 2)), ((7, 2), (8, 2)),
        ((0, 3), (1, 3)), ((2, 3), (4, 3)), ((5, 3), (6, 3)), ((7, 3), (8, 3)),
        ((0, 4), (3, 5)),
        ((4, 4), (5, 4)), ((6, 4), (7, 4)), ((8, 4), (9, 4)),
        ((4, 5), (9, 10)),
        ((1, 6), (2, 6)),
        ((0, 7), (3, 7)),
        ((1, 8), (3, 9)),
        ((1, 10), (3, 10)),
    ]

    commands = [
        ('GRID', (0, 0), (-1, -1), 1.34, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0.84),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0.84),
        ('TOPPADDING', (0, 0), (-1, -1), 0.84),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0.84),
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
    story = []
    records = tuple(records)
    if not records:
        style = ParagraphStyle(
            'empty',
            fontName='Times-Roman',
            fontSize=11,
            leading=14,
        )
        story.append(Paragraph('No appointments matched the selected MOD Sheet filters.', style))
    else:
        for index, record in enumerate(records):
            story.append(KeepTogether([_mod_table(record, color_code)]))
            if index + 1 < len(records):
                if (index + 1) % 3 == 0:
                    story.append(PageBreak())
                else:
                    story.append(Spacer(1, 18))
    doc.build(story)
    return stream.getvalue()
