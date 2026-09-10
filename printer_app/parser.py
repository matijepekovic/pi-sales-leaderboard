"""Read cached cell values; do not evaluate formulas, execute VBA or open external links."""
import hashlib
import logging
from pathlib import Path
import re
import zipfile
from .contracts import Cell, ReportGroup

log = logging.getLogger(__name__)
MAX_CELLS = 250_000
MAX_UNPACKED = 256 * 1024 * 1024


class ParserError(ValueError):
    pass


def label(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').casefold())


def read_sheets(path: Path):
    if path.suffix.lower() == '.xls':
        import xlrd
        book = xlrd.open_workbook(path, on_demand=True, formatting_info=True)
        try:
            count = 0
            for sheet in book.sheets():
                count += sheet.nrows * sheet.ncols
                if count > MAX_CELLS:
                    raise ParserError('WORKBOOK EXCEEDS SAFE CELL PROCESSING LIMIT')
                rows = []
                for row_index in range(sheet.nrows):
                    row = []
                    for column in range(sheet.ncols):
                        cell = sheet.cell(row_index, column)
                        value = cell.value
                        if cell.ctype == xlrd.XL_CELL_DATE:
                            value = xlrd.xldate_as_datetime(value, book.datemode)
                        elif cell.ctype == xlrd.XL_CELL_ERROR:
                            raise ParserError('EXCEL CELL ERROR FOUND')
                        elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                            value = bool(value)
                        fmt = book.format_map[book.xf_list[cell.xf_index].format_key].format_str
                        row.append(Cell(value, fmt))
                    rows.append(tuple(row))
                yield sheet.name, rows
        finally:
            book.release_resources()
        return
    from openpyxl import load_workbook
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_UNPACKED or len(archive.infolist()) > 20_000:
            raise ParserError('WORKBOOK EXPANSION EXCEEDS SAFE PROCESSING LIMIT')
    values = load_workbook(path, read_only=True, data_only=True, keep_links=False, keep_vba=False)
    formulas = load_workbook(path, read_only=True, data_only=False, keep_links=False, keep_vba=False)
    try:
        count = 0
        for sheet in values.worksheets:
            formula_sheet = formulas[sheet.title]
            # Ignore inflated worksheet dimension metadata, but enforce a real cell budget.
            sheet.reset_dimensions()
            formula_sheet.reset_dimensions()
            rows = []
            for row, formula_row in zip(sheet.iter_rows(), formula_sheet.iter_rows()):
                count += len(row)
                if count > MAX_CELLS:
                    raise ParserError('WORKBOOK EXCEEDS SAFE CELL PROCESSING LIMIT')
                normalized = []
                for value_cell, formula_cell in zip(row, formula_row):
                    if formula_cell.data_type == 'f' and value_cell.value is None:
                        raise ParserError('FORMULA HAS NO CACHED VALUE; SAVE THE WORKBOOK AFTER RECALCULATION')
                    if value_cell.data_type == 'e':
                        raise ParserError('EXCEL CELL ERROR FOUND')
                    normalized.append(Cell(value_cell.value, value_cell.number_format))
                rows.append(tuple(normalized))
            yield sheet.title, rows
    finally:
        values.close()
        formulas.close()


def parse(path: Path) -> list[ReportGroup]:
    candidates = []
    try:
        for sheet_name, rows in read_sheets(path):
            for header_index, header in enumerate(rows):
                positions = [i for i, cell in enumerate(header) if label(cell.value) == 'substatus']
                if not positions:
                    continue
                if len(positions) != 1:
                    raise ParserError('MULTIPLE SUB STATUS COLUMNS FOUND')
                body = []
                for row in rows[header_index + 1:]:
                    if not any(cell.value is not None and str(cell.value).strip() for cell in row):
                        continue
                    # A repeated page/table header is not a data row.
                    if tuple(label(c.value) for c in row) == tuple(label(c.value) for c in header):
                        continue
                    body.append(row)
                candidates.append((len(body), sheet_name, header_index, positions[0], header, body))
                break
        if not candidates:
            raise ParserError('SUB STATUS COLUMN NOT FOUND')
        candidates.sort(key=lambda item: item[0], reverse=True)
        if not candidates[0][0]:
            raise ParserError('NO PRINTABLE ROWS FOUND')
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            raise ParserError('MAIN TABLE IS AMBIGUOUS: MULTIPLE EQUALLY SIZED TABLES')
        _, sheet, header_index, status_index, header, body = candidates[0]
        used = [i for row in [header, *body] for i, cell in enumerate(row) if cell.value is not None and str(cell.value).strip()]
        left, right = min(used), max(used)
        def normalized(row):
            return tuple(row[i] if i < len(row) else Cell(None) for i in range(left, right + 1))
        headers = tuple(str(c.value) if c.value is not None else '' for c in normalized(header))
        groups = {}
        for row in body:
            value = row[status_index].value if status_index < len(row) else None
            status = str(value).strip() if value is not None and str(value).strip() else '(blank)'
            groups.setdefault(status, []).append(normalized(row))
        log.info('Main table sheet=%r header_row=%d rows=%d groups=%d', sheet, header_index + 1, len(body), len(groups))
        return [ReportGroup(hashlib.sha256((sheet + '\0' + status).encode()).hexdigest(), status, headers, tuple(rows), sheet)
                for status, rows in groups.items()]
    except ParserError:
        raise
    except Exception as exc:
        raise ParserError('EXCEL PARSER FAILED: ' + type(exc).__name__) from exc
