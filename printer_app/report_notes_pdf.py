"""Vector PDF notes renderer. Consumes normalized page rows/bounds, not table APIs."""
from __future__ import annotations

from copy import copy
from io import BytesIO
from pathlib import Path
import threading
from xml.sax.saxutils import escape

from pypdf import PageObject, PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject
import reportlab
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from .report_notes_contract import NotesPlacement, ReportNotesError, ReportNotesOptions, ReportTables

_MM = 72 / 25.4
_MARGIN = 18.0
_FONT_LOCK = threading.Lock()
_FONT = 'StatsReportNotes'
_BOLD = 'StatsReportNotesBold'


def normalize_pdf(data: bytes) -> bytes:
    """Make visible crop and rotation explicit for both the reader and renderer.

    A fresh writer keeps this a printable document, not an active PDF attachment.
    Source bytes are never changed. Text and drawing paths remain vector content.
    """
    reader = PdfReader(BytesIO(data), strict=False)
    if reader.is_encrypted or not reader.pages or len(reader.pages) > 200:
        raise ReportNotesError('Notes require an unencrypted report of 1 to 200 pages.')
    writer = PdfWriter()
    for original in reader.pages:
        original.transfer_rotation_to_content()
        crop = original.cropbox
        page = PageObject.create_blank_page(width=float(crop.width), height=float(crop.height))
        original.pop('/Annots', None)  # Printed text is retained; active link actions are not needed.
        page.merge_transformed_page(original, Transformation().translate(-float(crop.left), -float(crop.bottom)))
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _fonts():
    with _FONT_LOCK:
        if _FONT not in pdfmetrics.getRegisteredFontNames():
            # ReportLab distributes these fonts on every supported platform.
            # No OS-specific font paths or user-installed fonts are required.
            directory = Path(reportlab.__file__).parent / 'fonts'
            pdfmetrics.registerFont(TTFont(_FONT, str(directory / 'Vera.ttf')))
            pdfmetrics.registerFont(TTFont(_BOLD, str(directory / 'VeraBd.ttf')))


def _paragraph(text, size, bold=False):
    name = _BOLD if bold else _FONT
    if any(ord(c) not in pdfmetrics.getFont(name).face.charToGlyph for c in text if not c.isspace()):
        raise ReportNotesError('A selected field contains characters unavailable in the notes print font.')
    return Paragraph(escape(text or '—'), ParagraphStyle('report-note', fontName=name,
        fontSize=size, leading=size * 1.3, splitLongWords=True, spaceBefore=0, spaceAfter=0))


def _notes_block(rows, columns, width, options):
    """Wrap all field values; reserve at least 35% of the width for handwriting."""
    gap = 10.0
    count = len(columns)
    natural = [max(30, min(width * .45, max(
        pdfmetrics.stringWidth(columns[i], _BOLD, options.font_size),
        max((pdfmetrics.stringWidth(row[i], _FONT, options.font_size) for row in rows), default=0)) + 4))
        for i in range(count)]
    budget = max(1, width * .65 - gap * count)
    ratio = min(1, budget / sum(natural))
    widths = [value * ratio for value in natural]
    notes_x = sum(widths) + gap * count
    headers = [_paragraph(label, options.font_size, True) for label in (*columns, 'Updates')]
    header_widths = [*widths, max(1, width - notes_x)]
    header_height = max(p.wrap(w, 1000000)[1] for p, w in zip(headers, header_widths)) + options.font_size * .6
    entries = []
    for row in rows:
        paragraphs = [_paragraph(value, options.font_size) for value in row]
        heights = [p.wrap(w, 1000000)[1] for p, w in zip(paragraphs, widths)]
        height = max(heights) + options.row_spacing_mm * _MM
        entries.append((paragraphs, heights, height))
    return widths, notes_x, headers, header_height, entries, header_height + sum(e[2] for e in entries)


def render_notes(data: bytes, tables: ReportTables, options: ReportNotesOptions):
    """Place notes beneath actual bottom edges; uniformly shrink only as needed.

    The original top-of-page report block and the new notes share a single scale,
    preserving proportions, requested spacing ratios, every row, and page count.
    Footers stay at their original positions. No row or long name is truncated.
    """
    if not options.enabled:
        return data, ()
    _fonts()
    reader = PdfReader(BytesIO(data))
    if len(reader.pages) != len(tables.pages):
        raise ReportNotesError('Report layout does not match its PDF pages.')
    writer, placements = PdfWriter(), []
    for number, (source, table) in enumerate(zip(reader.pages, tables.pages), 1):
        if table is None or not table.rows:
            writer.add_page(source)
            continue
        if any(len(row) != len(options.columns) for row in table.rows):
            raise ReportNotesError('Report rows do not match the selected notes columns.')
        width, height = float(source.mediabox.width), float(source.mediabox.height)
        if abs(table.width - width) > .01 or abs(table.height - height) > .01:
            raise ReportNotesError('Report page dimensions changed during layout.')
        left = max(_MARGIN, table.left)
        available_width = width - left - _MARGIN
        if available_width <= 1 or table.footer_top <= _MARGIN:
            raise ReportNotesError(f'Page {number} has no printable area for notes.')
        widths, notes_x, headers, header_height, entries, notes_height = _notes_block(
            table.rows, options.columns, available_width, options)
        gap = options.table_gap_mm * _MM
        scale = min(1.0, (table.footer_top - _MARGIN) /
                    (table.bottom - _MARGIN + gap + notes_height))
        table_bottom = _MARGIN + scale * (table.bottom - _MARGIN)
        notes_top = table_bottom + scale * gap
        notes_bottom = notes_top + scale * notes_height
        target = PageObject.create_blank_page(width=width, height=height)
        cut = min(height, table.bottom)
        if scale == 1:
            target.merge_page(source)
        else:
            body = copy(source)
            body.cropbox = RectangleObject((0, height - cut, width, height))
            transform = Transformation((scale, 0, 0, scale,
                _MARGIN * (1 - scale), (height - _MARGIN) * (1 - scale)))
            target.merge_transformed_page(body, transform)
            if cut < height:
                footer = copy(source)
                footer.cropbox = RectangleObject((0, 0, width, height - cut))
                target.merge_page(footer)
        stream = BytesIO()
        canvas = Canvas(stream, pagesize=(width, height), pageCompression=1)
        canvas.translate(_MARGIN + scale * (left - _MARGIN), height - notes_top)
        canvas.scale(scale, scale)
        # Keep the handwriting rules page-wide even when text/spacing shrink.
        writing_right = (width - _MARGIN - (_MARGIN + scale * (left - _MARGIN))) / scale
        x = 0
        for p, w in zip(headers, [*widths, available_width - notes_x]):
            h = p.wrap(w, 1000000)[1]
            p.drawOn(canvas, x, -h)
            x += w + 10
        y = header_height
        canvas.setStrokeGray(.65)
        canvas.setLineWidth(.4)
        for paragraphs, heights, row_height in entries:
            x = 0
            for p, w, h in zip(paragraphs, widths, heights):
                p.drawOn(canvas, x, -y - h)
                x += w + 10
            # The line is inside the allocated row, leaving the chosen blank
            # spacing for handwriting beside even multi-line field values.
            canvas.line(notes_x, -y - row_height + 1, writing_right, -y - row_height + 1)
            y += row_height
        canvas.save()
        target.merge_page(PdfReader(BytesIO(stream.getvalue())).pages[0])
        writer.add_page(target)
        placements.append(NotesPlacement(number, len(table.rows), scale, table_bottom,
                                          notes_top, notes_bottom, table.footer_top))
    result = BytesIO()
    writer.write(result)
    return result.getvalue(), tuple(placements)
