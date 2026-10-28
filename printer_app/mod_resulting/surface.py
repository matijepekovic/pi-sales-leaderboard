"""The digital editor's background is Printer's rendered PDF, not another form.

Only this presentation boundary knows PDF crop/overlay coordinates. It accepts
normalized records, never reads a repository, and never talks to Salesforce.
The original MOD renderer and the application's CSP are not changed.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter

from ..mod_sheet_contract import ModSheetRecord
from ..mod_sheets.pdf_renderer import MOD_COLUMNS, MOD_ROW_HEIGHTS, MOD_TABLE_WIDTH, PAGE_MARGIN_Y


PAD = 1.0  # Include the entire outside border, not just its centre line.
WIDTH = MOD_TABLE_WIDTH + 2 * PAD
HEIGHT = sum(MOD_ROW_HEIGHTS) + 2 * PAD
LEFT = (letter[0] - MOD_TABLE_WIDTH) / 2 - PAD
TOP = PAGE_MARGIN_Y + 6 - PAD  # SimpleDocTemplate's frame top padding is 6pt.
DPI = 180


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    def inset(self, value=0.8):
        """Put an editable control inside the original border, never over it."""
        return Box(self.x + value, self.y + value,
                   self.width - 2 * value, self.height - 2 * value)


def cell(column, row, columns=1, rows=1):
    """Zero-based coordinates in the existing renderer's fixed grid."""
    return Box(PAD + column * MOD_TABLE_WIDTH / MOD_COLUMNS,
               PAD + sum(MOD_ROW_HEIGHTS[:row]),
               columns * MOD_TABLE_WIDTH / MOD_COLUMNS,
               sum(MOD_ROW_HEIGHTS[row:row + rows]))


# These locate interactive overlays; they do not draw the form or its grid.
BOXES = {
    'power': cell(9, 1), 'tclose': cell(9, 2),
    'product': cell(2, 3, 3), 'detail': cell(9, 3),
    # These are click-through price override controls on the original PDF row.
    'startprice': cell(4, 4, 2), 'finalprice': cell(6, 4, 2),
    'depositpayment': cell(8, 4, 2),
    'notes': cell(4, 5, 6, 6),
    'docs': cell(0, 6), 'bids': cell(1, 6, 2), 'pictures': cell(3, 6),
    'dispo': cell(0, 7, 2), 'extras': cell(2, 7, 2),
    'call1': cell(0, 8), 'call2': cell(0, 9),
    'need': cell(1, 8, 3, 2), 'ninety': cell(0, 10),
    'want': cell(1, 10, 3),
}


def overlay_css():
    """A same-origin stylesheet: no inline styles or relaxed CSP required."""
    rules = [f'.mod-sheet{{aspect-ratio:{WIDTH:.6f}/{HEIGHT:.6f}}}']
    for name, original in BOXES.items():
        box = original.inset()
        rules.append(
            f'.mod-sheet .field-{name}' + '{'
            f'left:{box.x / WIDTH * 100:.8f}%;'
            f'top:{box.y / HEIGHT * 100:.8f}%;'
            f'width:{box.width / WIDTH * 100:.8f}%;'
            f'height:{box.height / HEIGHT * 100:.8f}%;' + '}'
        )
    return '\n'.join(rules) + '\n'


class SheetSurfaceError(RuntimeError):
    """A local rendering failure; never a reason to substitute a different form."""


class ModSheetSurface:
    def __init__(self, renderer, *, rasterizer='pdftoppm'):
        self.renderer = renderer
        self.rasterizer = rasterizer
        self._slots = BoundedSemaphore(2)

    @lru_cache(maxsize=16)
    def image(self, record: ModSheetRecord) -> bytes:
        """Render one original sheet, crop it losslessly, and return its PNG.

        Small bounded in-memory cache; no customer image files are persisted.
        Lazy browser loading limits work for a day containing many leads.
        """
        with self._slots:
            original = PdfReader(BytesIO(self.renderer([record])))
            if len(original.pages) != 1:
                raise SheetSurfaceError('The MOD renderer did not produce one sheet page.')
            writer = PdfWriter()
            page = writer.add_page(original.pages[0])
            page.cropbox.lower_left = (LEFT, letter[1] - TOP - HEIGHT)
            page.cropbox.upper_right = (LEFT + WIDTH, letter[1] - TOP)
            with TemporaryDirectory(prefix='stats-mod-surface-') as folder:
                source = Path(folder) / 'sheet.pdf'
                target = Path(folder) / 'sheet'
                with source.open('wb') as stream:
                    writer.write(stream)
                try:
                    result = subprocess.run(
                        [self.rasterizer, '-f', '1', '-singlefile', '-cropbox',
                         '-r', str(DPI), '-png', str(source), str(target)],
                        check=False, capture_output=True, timeout=30,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise SheetSurfaceError('Printer could not render the MOD sheet image.') from exc
                output = target.with_suffix('.png')
                if result.returncode or not output.is_file():
                    raise SheetSurfaceError('Printer could not render the MOD sheet image.')
                payload = output.read_bytes()
                if not payload.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise SheetSurfaceError('Printer returned an invalid MOD sheet image.')
                return payload
