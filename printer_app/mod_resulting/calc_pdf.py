"""Approved compact OLY Calc PDF and original Olympia artwork.

A pure presentation adapter: receives normalized report values, never queries
Salesforce, reads SQLite, or changes resulting/submission state.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from .calc_report import INPUT_FIELDS, OUTPUT_FIELDS

PAGE_W, PAGE_H = 720, 650
TABLE_X = 30
TABLE_W = 254
LABEL_W = 143.5
VALUE_W = TABLE_W - LABEL_W
ART_X, ART_Y, ART_W, ART_H = 305, 48, 390, 585
GREEN = HexColor("#50A32E")
MINT = HexColor("#BCEDC7")
WHITE = HexColor("#FFFFFF")
BLACK = HexColor("#121212")
BORDER = HexColor("#202820")
GRAY = HexColor("#47564A")

ORIGINAL_ART = (
    Path(__file__).resolve().parents[1]
    / "static" / "mod_resulting" / "oly_calc_art.webp"
)


def render_calc_pdf(report, *, artwork_path=None):
    """Render exact approved narrow table plus unmodified Olympia artwork."""
    target = Path(artwork_path) if artwork_path is not None else ORIGINAL_ART
    buffer = BytesIO()
    c = Canvas(buffer, pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    c.setTitle("OLY Calc - " + str(report["day"]))

    def rect(x, top, width, height, fill, stroke=True):
        c.setFillColor(fill)
        c.setStrokeColor(BORDER)
        c.setLineWidth(.65)
        c.rect(x, top-height, width, height, fill=1, stroke=int(stroke))

    def label(value, x, top, width, height, *, size=14, bold=False,
              color=BLACK, align="left"):
        value = str(value if value is not None else "").replace("\n", " ")
        font = "Helvetica-Bold" if bold else "Helvetica"
        while size > 9 and c.stringWidth(value, font, size) > width - 11:
            size -= .4
        c.setFillColor(color)
        c.setFont(font, size)
        y = top - height / 2 - size * .34
        if align == "center":
            c.drawCentredString(x + width / 2, y, value)
        elif align == "right":
            c.drawRightString(x + width - 6, y, value)
        else:
            c.drawString(x + 5, y, value)

    def band(y, height, title, fill, color=BLACK, *, size=15.5, bold=True):
        rect(TABLE_X, y, TABLE_W, height, fill)
        label(title, TABLE_X, y, TABLE_W, height, size=size, color=color,
              bold=bold, align="center")
        return y - height

    def entry(y, title, value):
        height = 29.25
        rect(TABLE_X, y, LABEL_W, height, WHITE)
        rect(TABLE_X + LABEL_W, y, VALUE_W, height, GREEN)
        label(title, TABLE_X, y, LABEL_W, height)
        label(value, TABLE_X + LABEL_W, y, VALUE_W, height,
              size=13.2, bold=True, color=WHITE, align="center")
        return y - height

    def calculation(y, title, value):
        height = 29
        rect(TABLE_X, y, TABLE_W, height, WHITE, stroke=False)
        label(title, TABLE_X, y, LABEL_W, height, size=14.2, bold=True)
        label(value, TABLE_X + LABEL_W, y, VALUE_W, height,
              size=13, align="right")
        return y - height

    top = PAGE_H - 19
    top = band(top, 30, "Olympia, WA", GREEN, WHITE, size=16)
    top = band(top, 30, "#1 in Puget Sound", MINT, BLACK, size=16)
    for key, display in INPUT_FIELDS:
        top = entry(top, display, report["inputs"].get(key, ""))
    top = band(top, 29.5, "At EVERYTHING", MINT)
    top = band(top, 29.5, "Results > Excuses", GREEN, WHITE)
    top = band(top, 29.5, "MOD Results", MINT, bold=False, size=16)
    for key, display in OUTPUT_FIELDS:
        top = calculation(top, display, report["outputs"].get(key, ""))

    # Exact source image exported from the user's OLY Calc Excel drawing.
    artwork = ImageReader(str(target))
    c.drawImage(artwork, ART_X, ART_Y, width=ART_W, height=ART_H,
                preserveAspectRatio=True, mask="auto")
    c.setStrokeColor(HexColor("#385443"))
    c.setLineWidth(.6)
    c.rect(ART_X, ART_Y, ART_W, ART_H, fill=0, stroke=1)
    c.setFillColor(GRAY)
    c.setFont("Helvetica", 8)
    nice_day = date.fromisoformat(report["day"]).strftime("%B %d, %Y")
    c.drawCentredString(PAGE_W / 2, 12, nice_day +
                        "  -  CXL and OOS excluded from Leads")
    c.showPage()
    c.save()
    return buffer.getvalue()
