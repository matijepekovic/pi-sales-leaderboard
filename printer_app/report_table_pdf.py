"""Native text/grid adapter for rendered reports. No OCR and no source rewriting.

Read the same cells and vector borders that will be printed. This deliberately
uses the rendered page, not a second report download or guessed Excel page breaks.
The rest of printing receives only the normalized report-notes contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re

import pdfplumber

from .report_notes_contract import PageTable, ReportNotesError, ReportTables, heading

# Small tolerances retain short rows/columns in wide, fit-to-page reports.
_GRID = dict(snap_tolerance=.6, join_tolerance=1, intersection_tolerance=1,
             edge_min_length=1)
_SUMMARY = re.compile(r'^(?:subtotal|grand total|total)(?:\s+(?:sum|count|average|avg|min|max)\b.*)?$', re.I)
_AGGREGATE = re.compile(r'^(?:sum|count|average|avg|min|max)(?:\s+[\d,. ()$%+-]+)?$', re.I)
_MAX_PAGES = 200
_MAX_CELLS = 200000


@dataclass(frozen=True)
class _Column:
    label: str
    left: float
    right: float

    @property
    def key(self):
        return self.label.casefold()


def _row_bounds(table, index):
    top = table.rows[index].bbox[1]
    following = table.rows[index + 1].bbox[1] if index + 1 < len(table.rows) else table.bbox[3]
    return top, following


def _header(table, raw, selected):
    """Titles and filter blocks are merged cells, not column headers."""
    candidates = []
    for index, row in enumerate(raw):
        values = [(i, heading(value)) for i, value in enumerate(row) if value and heading(value)]
        if len(values) < 2 or _SUMMARY.fullmatch(values[0][1]):
            continue
        if selected and not selected <= {label.casefold() for _, label in values}:
            continue
        cells = table.rows[index].cells
        columns = tuple(_Column(label, cells[i][0], cells[i][2]) for i, label in values if cells[i])
        if len(columns) != len(values):
            continue
        # A header must have its own horizontal row, not vertically merged data.
        _, end = _row_bounds(table, index)
        if any(cells[i][3] > end + 1 for i, _ in values):
            continue
        candidates.append((index, columns))
        if selected:
            break
    if not candidates:
        return None
    # Without saved selections, take the first full-width field row, not a
    # two-cell caption above a much wider table. Ties retain the first row.
    return max(candidates, key=lambda item: len(item[1])) if not selected else candidates[0]


def _same_grid(table, previous):
    if not previous:
        return False
    edges = sorted({x for cell in table.cells for x in (cell[0], cell[2])})
    return all(any(abs(edge - x) <= 1 for edge in edges)
               for column in previous for x in (column.left, column.right))


def _new_header_signal(page, table, candidate, previous):
    if candidate is None:
        return False
    index, columns = candidate
    if len({c.key for c in columns} & {c.key for c in previous}) >= min(2, len(previous)):
        return True
    # A new sheet's merged title/filter preamble is not a continued detail row.
    if index > 0:
        return True
    top, end = _row_bounds(table, index)
    chars = [c for c in page.chars if top <= (c['top'] + c['bottom']) / 2 < end
             and table.bbox[0] <= c['x0'] <= table.bbox[2] and not c['text'].isspace()]
    # Formatted report headings are typographically distinct. A numeric detail
    # row is not a new header, even if its first row happens to be bold.
    numeric = any(re.fullmatch(r'[\d,. ()$%+-]+', c.label) for c in columns)
    return bool(chars) and not numeric and sum('bold' in c['fontname'].lower() for c in chars) / len(chars) > .7


def _visible_objects(page):
    yield from page.chars
    yield from page.images
    for obj in (*page.lines, *page.rects, *page.curves):
        # Ignore white page backgrounds; honor real rules and filled table cells.
        def white(color):
            return color == 1 or isinstance(color, (tuple, list)) and all(v == 1 for v in color)
        if obj.get('stroke') and not white(obj.get('stroking_color')) or \
                obj.get('fill') and not white(obj.get('non_stroking_color')):
            yield obj


def _page_edges(page, tables):
    left = min(t.bbox[0] for t in tables)
    bottom = max(t.bbox[3] for t in tables)
    objects = list(_visible_objects(page))
    # Include overflowing glyphs/images and the outer half of the bottom rule.
    # The overlay must clear ink, not merely a nominal cell height.
    for obj in objects:
        if obj['top'] <= bottom and obj['bottom'] >= bottom:
            if obj['bottom'] - obj['top'] < page.height * .9:
                bottom = max(bottom, obj['bottom'] + max(0, obj.get('linewidth', 0) or 0) / 2)
    bottom += .75
    below = [obj['top'] for obj in objects if obj['top'] > bottom]
    # A footer or caption remains in place and is never covered by the overlay.
    footer = min([page.height - 18, *[top - 3 for top in below]])
    return max(18, left), bottom, footer


def read_tables(data: bytes, selected_columns: tuple[str, ...] = ()) -> ReportTables:
    """Extract fields, detail rows, and actual page edges from a normalized PDF.

    Saved selections match headings, not column positions. Reordered columns
    therefore keep their meaning. Missing/ambiguous headings fail visibly rather
    than silently printing a different field. Repeated names remain separate rows.
    """
    selected = {heading(c).casefold() for c in selected_columns}
    found_columns = {}
    pages = []
    previous = None
    cell_count = 0
    with pdfplumber.open(BytesIO(data)) as document:
        if len(document.pages) > _MAX_PAGES:
            raise ReportNotesError('Notes overlay supports reports up to 200 pages.')
        for page in document.pages:
            grids = [t for t in page.find_tables(_GRID) if len(t.columns) >= 2 and len(t.rows) >= 1]
            records, used_tables = [], []
            for table in sorted(grids, key=lambda t: (t.bbox[1], t.bbox[0])):
                cell_count += len(table.cells)
                if cell_count > _MAX_CELLS:
                    raise ReportNotesError('Report has too many table cells for a notes overlay.')
                raw = table.extract(x_tolerance=1, y_tolerance=1)
                found = _header(table, raw, selected)
                if _same_grid(table, previous):
                    repeated = _header(table, raw, {c.key for c in previous})
                    if repeated:
                        found = repeated
                    else:
                        candidate = _header(table, raw, set())
                        if _new_header_signal(page, table, candidate, previous):
                            if selected and not selected <= {c.key for c in candidate[1]}:
                                raise ReportNotesError(f'A selected notes column is missing on page {page.page_number}.')
                            found = candidate
                        else:
                            # In a continuation, ordinary customer values must
                            # never become catalog headings or be dropped.
                            found = None
                if found:
                    start, columns = found
                    keys = [column.key for column in columns]
                    if len(keys) != len(set(keys)):
                        raise ReportNotesError(f'Duplicate column headings on page {page.page_number}; rename them in the report.')
                    previous = columns
                elif _same_grid(table, previous):
                    start, columns = -1, previous
                else:
                    raise ReportNotesError(f'Cannot identify the selected table columns on page {page.page_number}. Load columns and check the preview.')
                used_tables.append(table)
                found_columns.update((column.key, column.label) for column in columns)
                if selected and not selected <= {c.key for c in columns}:
                    raise ReportNotesError(f'A selected notes column is missing on page {page.page_number}.')
                # Index rendered cells once. A merge may carry a grouping value
                # down; an ordinary empty cell must never inherit a prior name.
                text_by_cell = {}
                for row, extracted in zip(table.rows, raw):
                    for cell, text in zip(row.cells, extracted):
                        if cell is not None:
                            text_by_cell[cell] = ' '.join((text or '').split())
                relevant_cells = {
                    c.key: sorted((cell for cell in table.cells
                                   if cell[0] <= (c.left + c.right) / 2 <= cell[2]), key=lambda cell: cell[1])
                    for c in columns
                }
                summary_until = -1
                for index in range(start + 1, len(raw)):
                    top, end = _row_bounds(table, index)
                    row = raw[index]
                    nonempty = [heading(v) for v in row if v and heading(v)]
                    if not nonempty:
                        continue
                    if _SUMMARY.fullmatch(nonempty[0]) or _AGGREGATE.fullmatch(nonempty[0]):
                        label_cells = [cell for cell, text in zip(table.rows[index].cells, row)
                                       if cell and text and (_SUMMARY.fullmatch(heading(text)) or _AGGREGATE.fullmatch(heading(text)))]
                        summary_until = max([summary_until, end, *[cell[3] for cell in label_cells]])
                        continue
                    if top < summary_until - .5:
                        continue
                    # Repeated headers on a continued page are not job records.
                    if {heading(v).casefold() for v in nonempty} >= {c.key for c in columns}:
                        continue
                    values = {}
                    y = (top + end) / 2
                    for column in columns:
                        matches = [cell for cell in relevant_cells[column.key] if cell[1] <= y < cell[3]]
                        cell = min(matches, key=lambda box: box[2] - box[0]) if matches else None
                        # A horizontal merge spanning fields is a heading/summary,
                        # not multiple copies of the same customer value.
                        if cell and cell[2] - cell[0] <= column.right - column.left + 1:
                            values[column.key] = text_by_cell.get(cell, '')
                        else:
                            values[column.key] = ''
                    order = [heading(c).casefold() for c in selected_columns] if selected_columns else [c.key for c in columns]
                    chosen = tuple(values.get(key, '') for key in order)
                    if any(values.values()):
                        records.append(chosen)
            if used_tables:
                left, bottom, footer = _page_edges(page, used_tables)
                pages.append(PageTable(float(page.width), float(page.height), left, bottom, footer, tuple(records)))
            elif page.chars:
                # No guessing at scanned pages, borderless layouts, or pages with
                # unknown columns. Disabled notes still use the original path.
                raise ReportNotesError(f'No readable table grid found on page {page.page_number}. Check the report preview.')
            else:
                pages.append(None)
            page.close()
    if not found_columns:
        raise ReportNotesError('No readable report table found. Notes require a text report with table borders.')
    return ReportTables(tuple(found_columns.values()), tuple(pages))
