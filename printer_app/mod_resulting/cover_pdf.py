"""Approved one-page Olympia cover layout, with overflow pages if required.

Pure PDF rendering: accepts a normalized editable cover document; no database,
Salesforce, filesystem or web dependencies.
"""
from __future__ import annotations

from io import BytesIO
from math import ceil

from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .cover_report import COLUMN_FIELDS, DIVISIONS, SUMMARY_FIELDS

WIDTH, HEIGHT = 1008, 612
LEFT, RIGHT = 22, 986
BORDER = colors.HexColor("#617069")
PALE = colors.HexColor("#e4e9e4")
GREEN = colors.HexColor("#589b36")
WHITE = colors.white
TEXT = colors.HexColor("#202922")
COL_WIDTHS = (52, 53, 132, 158, 60, 60, 33, 63, 130, 53, 50, 57, 63)
SLOTS = {"roof": 6, "bath": 4, "siding": 4, "windows": 4, "gutters": 4}
assert sum(COL_WIDTHS) == RIGHT - LEFT


def _rect(c, x, top, width, height, *, fill=WHITE, stroke=True):
    c.setFillColor(fill)
    c.setStrokeColor(BORDER)
    c.setLineWidth(.4)
    c.rect(x, HEIGHT - top - height, width, height, stroke=int(stroke), fill=1)


def _fit_text(c, text, x, top, width, height, *, size=7.5, bold=False,
              align="center"):
    text = str(text if text is not None else "").replace("\n", " ").strip()
    if not text:
        return
    font = "Helvetica-Bold" if bold else "Helvetica"
    size = min(size, max(6, height - 4))
    usable = max(1, width - 6)
    while size > 5.4 and stringWidth(text, font, size) > usable:
        size -= .25
    if stringWidth(text, font, size) > usable:
        while text and stringWidth(text + "…", font, size) > usable:
            text = text[:-1]
        text += "…" if text else ""
    c.setFillColor(TEXT)
    c.setFont(font, size)
    y = HEIGHT - top - (height + size) / 2 + 1.6
    if align == "left":
        c.drawString(x + 4, y, text)
    elif align == "right":
        c.drawRightString(x + width - 4, y, text)
    else:
        c.drawCentredString(x + width / 2, y, text)


def _row(c, values, top, height, widths, *, fill=WHITE, bold=False,
         alignments=None):
    x = LEFT
    for i, (value, width) in enumerate(zip(values, widths)):
        _rect(c, x, top, width, height, fill=fill)
        alignment = (alignments[i] if alignments else "center")
        _fit_text(c, value, x, top, width, height, bold=bold, align=alignment)
        x += width


def _band(c, title, top):
    _rect(c, LEFT, top, RIGHT - LEFT, 14.5, fill=GREEN)
    _fit_text(c, title, LEFT, top, RIGHT - LEFT, 14.5, size=9, bold=True)
    return top + 14.5


def _section(c, section, rows, top):
    top = _band(c, section["title"], top)
    if section["key"] == "roof":
        _row(c, [label for _, label in COLUMN_FIELDS], top, 18, COL_WIDTHS,
             fill=PALE, bold=True)
        top += 18
    for i in range(SLOTS[section["key"]]):
        entry = rows[i] if i < len(rows) else {}
        _row(c, [entry.get(key, "") for key, _ in COLUMN_FIELDS], top, 13,
             COL_WIDTHS)
        top += 13
    return top


SUMMARY_WIDTHS = (55, 70, 80, 74, 80, 100, 135)
SIDE_WIDTHS = (158, 212)
assert sum(SUMMARY_WIDTHS) + sum(SIDE_WIDTHS) == RIGHT - LEFT


def _summary(c, report, top):
    headers = ("", "Leads", "Pitched", "Pitch %", "Closing %",
               "Day Total", "$ Per Lead")
    values = [report["totals"].get("avg_job_pct", "")]
    x = LEFT
    for text, width in zip(headers, SUMMARY_WIDTHS):
        _rect(c, x, top, width, 19, fill=PALE)
        _fit_text(c, text, x, top, width, 19, bold=True)
        x += width
    _rect(c, x, top, SIDE_WIDTHS[0], 19, fill=PALE)
    _fit_text(c, "Avg Job %", x, top, SIDE_WIDTHS[0], 19, bold=True)
    x += SIDE_WIDTHS[0]
    _rect(c, x, top, SIDE_WIDTHS[1], 19, fill=PALE)
    _fit_text(c, values[0], x, top, SIDE_WIDTHS[1], 19, bold=True)
    top += 19

    keys = [key for key, _ in DIVISIONS] + ["grand"]
    labels = ["Roof", "Bath", "Siding", "Windows", "Gutters", "Grand Total"]
    right_keys = ["average_sale", "average_deposit", "sales", "reps_paid", None, "date"]
    right_labels = ["Average Sale", "Average Deposit", "Sales",
                    "Reps Paid", "", ""]
    for index, (key, label) in enumerate(zip(keys, labels)):
        values = report["grand"] if key == "grand" else next(
            s["summary"] for s in report["sections"] if s["key"] == key)
        fill = PALE if key == "grand" else WHITE
        row_values = [label] + [values.get(f, "") for f in SUMMARY_FIELDS]
        x = LEFT
        for j, (value, width) in enumerate(zip(row_values, SUMMARY_WIDTHS)):
            _rect(c, x, top, width, 17, fill=fill)
            _fit_text(c, value, x, top, width, 17,
                      bold=key == "grand" or (j in (5, 6) and bool(value)),
                      align="left" if j == 0 else "right")
            x += width
        _rect(c, x, top, SIDE_WIDTHS[0], 17, fill=PALE)
        _fit_text(c, right_labels[index], x, top, SIDE_WIDTHS[0], 17,
                  bold=bool(right_labels[index]), align="left")
        x += SIDE_WIDTHS[0]
        _rect(c, x, top, SIDE_WIDTHS[1], 17, fill=fill)
        value = report["totals"].get(right_keys[index], "") if right_keys[index] else ""
        _fit_text(c, value, x, top, SIDE_WIDTHS[1], 17,
                  bold=index in (0, 1, 2, 3))
        top += 17
    return top


def _footer(c, report, top, page_no, page_count):
    _rect(c, LEFT, top, 415, 20, fill=PALE)
    _fit_text(c, "MOD - " + str(report["totals"].get("mod") or "") +
              " (OLY)", LEFT, top, 415, 20, size=9, bold=True, align="left")
    _rect(c, LEFT + 415, top, 100, 20, fill=PALE)
    _fit_text(c, "NRA", LEFT + 415, top, 100, 20, bold=True)
    _rect(c, LEFT + 515, top, 78, 20)
    _fit_text(c, report["totals"].get("nra", ""), LEFT + 515, top, 78, 20, bold=True)
    _rect(c, LEFT + 593, top, RIGHT - LEFT - 593, 20, fill=PALE)
    if page_count > 1:
        _fit_text(c, f"Cover page {page_no} of {page_count}",
                  LEFT + 593, top, RIGHT - LEFT - 593, 20)
    return top + 20


def render_cover_pdf(report):
    """Render the cover first, retaining every sold row on overflow pages."""
    sections = report["sections"]
    page_count = max([1] + [
        ceil(len(section["rows"]) / SLOTS[section["key"]])
        for section in sections
    ])
    stream = BytesIO()
    c = canvas.Canvas(stream, pagesize=(WIDTH, HEIGHT), pageCompression=1)
    c.setTitle("OLY MOD Cover - " + str(report["day"]))
    for page in range(page_count):
        _rect(c, LEFT, 18, RIGHT - LEFT, 24, fill=PALE)
        _fit_text(c, "OLYMPIA", LEFT, 18, RIGHT - LEFT, 24, size=14, bold=True)
        top = 42
        for section in sections:
            capacity = SLOTS[section["key"]]
            rows = section["rows"][page * capacity:(page + 1) * capacity]
            top = _section(c, section, rows, top)
        top = _summary(c, report, top)
        _footer(c, report, top, page + 1, page_count)
        c.showPage()
    c.save()
    return stream.getvalue()
