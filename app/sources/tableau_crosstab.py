"""Read a chosen Tableau worksheet through its Crosstab Excel export.

This is intentionally separate from the shipped rep connector and from the
v81 generic CSV mapper.  A custom report selected in the settings page can
therefore use the same summary table Tableau exports from Download > Crosstab
without changing the working default source.

The rule here is deliberately strict: Tableau has already calculated the
worksheet.  The Pi maps one finished Crosstab cell to one board stat.  It does
not sum duplicate rep rows and it does not derive missing KPIs.  If the
selected worksheet is not already one row per rep, the pull fails and asks the
user to choose the summarized worksheet instead.
"""
import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

from . import tableau_v36_base as _base
from .tableau_custom import CustomTableauSource
from .tableau_mapped import STAT_TO_CAMEL, suggest_mapping, unmapped_columns

_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS = {"m": _NS_MAIN, "r": _NS_DOC_REL, "pr": _NS_PKG_REL}

# Excel built-in percentage formats. Tableau's Crosstab exports also use
# custom formats such as 0.0%; those are detected from styles.xml below.
_BUILTIN_PERCENT_FORMATS = {9, 10}
_SAMPLE_ROWS = 40


def _column_index(cell_ref):
    match = re.match(r"([A-Z]+)", str(cell_ref or "").upper())
    if not match:
        return 0
    value = 0
    for char in match.group(1):
        value = value * 26 + (ord(char) - 64)
    return max(0, value - 1)


def _shared_strings(book):
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    values = []
    for item in root.findall("m:si", _NS):
        values.append("".join(
            node.text or "" for node in item.iter(f"{{{_NS_MAIN}}}t")
        ))
    return values


def _is_percent_format(format_code):
    # Quoted/escaped percent signs are literals, not number-format operators.
    code = re.sub(r'"[^"]*"', "", str(format_code or ""))
    code = code.replace(r"\%", "")
    return "%" in code


def _style_percent_flags(book):
    if "xl/styles.xml" not in book.namelist():
        return []
    root = ET.fromstring(book.read("xl/styles.xml"))
    custom = {}
    formats = root.find("m:numFmts", _NS)
    if formats is not None:
        for item in formats.findall("m:numFmt", _NS):
            try:
                num_id = int(item.attrib.get("numFmtId", "0"))
            except ValueError:
                continue
            custom[num_id] = item.attrib.get("formatCode", "")

    flags = []
    cell_xfs = root.find("m:cellXfs", _NS)
    if cell_xfs is None:
        return flags
    for xf in cell_xfs.findall("m:xf", _NS):
        try:
            num_id = int(xf.attrib.get("numFmtId", "0"))
        except ValueError:
            num_id = 0
        flags.append(
            num_id in _BUILTIN_PERCENT_FORMATS
            or _is_percent_format(custom.get(num_id, ""))
        )
    return flags


def _first_sheet_path(book):
    """Resolve the first worksheet path instead of assuming sheet1.xml."""
    try:
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        sheet = workbook.find("m:sheets/m:sheet", _NS)
        if sheet is None:
            return "xl/worksheets/sheet1.xml"
        rel_id = sheet.attrib.get(f"{{{_NS_DOC_REL}}}id", "")
        rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        for rel in rels.findall(f"{{{_NS_PKG_REL}}}Relationship"):
            if rel.attrib.get("Id") != rel_id:
                continue
            target = str(rel.attrib.get("Target") or "").strip()
            if target.startswith("/"):
                return target.lstrip("/")
            return posixpath.normpath(posixpath.join("xl", target))
    except Exception:
        pass
    return "xl/worksheets/sheet1.xml"


def _cell_value(cell, strings, percent_flags):
    cell_type = cell.attrib.get("t", "")
    try:
        style_id = int(cell.attrib.get("s", "0") or 0)
    except ValueError:
        style_id = 0
    value_node = cell.find("m:v", _NS)

    if cell_type == "s":
        if value_node is None or value_node.text is None:
            return ""
        try:
            index = int(value_node.text)
        except ValueError:
            return ""
        return strings[index] if 0 <= index < len(strings) else ""

    if cell_type == "inlineStr":
        inline = cell.find("m:is", _NS)
        if inline is None:
            return ""
        return "".join(
            node.text or "" for node in inline.iter(f"{{{_NS_MAIN}}}t")
        )

    if cell_type in {"str", "e"}:
        return value_node.text if value_node is not None and value_node.text else ""
    if cell_type == "b":
        return bool(value_node is not None and value_node.text == "1")

    if value_node is None or value_node.text in (None, ""):
        return None
    try:
        number = float(value_node.text)
    except ValueError:
        return value_node.text

    # An Excel percent cell stores 40% as 0.40. Honor the Crosstab's own
    # number format so the value handed to the board is the visible 40, not
    # 0.40. This is unit/display normalization, not a KPI calculation.
    if 0 <= style_id < len(percent_flags) and percent_flags[style_id]:
        return number * 100.0
    return int(number) if number.is_integer() else number


def read_crosstab(xlsx_bytes):
    """Return (headers, row dictionaries, samples) from Tableau's .xlsx."""
    if not isinstance(xlsx_bytes, (bytes, bytearray)) or not xlsx_bytes:
        raise _base.TableauError("Tableau returned an empty Crosstab file.")
    try:
        with zipfile.ZipFile(io.BytesIO(bytes(xlsx_bytes))) as book:
            strings = _shared_strings(book)
            percent_flags = _style_percent_flags(book)
            sheet_path = _first_sheet_path(book)
            if sheet_path not in book.namelist():
                raise _base.TableauError("The Crosstab workbook had no readable worksheet.")
            root = ET.fromstring(book.read(sheet_path))

            matrix = []
            for row in root.findall(".//m:sheetData/m:row", _NS):
                cells = {}
                for cell in row.findall("m:c", _NS):
                    index = _column_index(cell.attrib.get("r", ""))
                    cells[index] = _cell_value(cell, strings, percent_flags)
                width = max(cells.keys(), default=-1) + 1
                values = [None] * width
                for index, value in cells.items():
                    values[index] = value
                matrix.append(values)
    except _base.TableauError:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as exc:
        raise _base.TableauError(
            "Tableau returned a Crosstab file the Pi could not read."
        ) from exc

    if not matrix:
        raise _base.TableauError("The Tableau Crosstab contained no rows.")

    # Tableau normally writes the field names on row 1. Allow a title row by
    # selecting the first row with at least two nonblank cells.
    header_at = 0
    for index, row in enumerate(matrix):
        nonblank = sum(1 for value in row if str(value or "").strip())
        if nonblank >= 2:
            header_at = index
            break

    raw_headers = matrix[header_at]
    keep = [
        index for index, value in enumerate(raw_headers)
        if str(value or "").strip()
    ]
    headers = [str(raw_headers[index]).strip() for index in keep]
    if not headers:
        raise _base.TableauError("The Tableau Crosstab had no column headers.")

    duplicates = sorted({name for name in headers if headers.count(name) > 1})
    if duplicates:
        raise _base.TableauError(
            "The Crosstab has duplicate column names: " + ", ".join(duplicates[:5])
            + ". Choose a worksheet with unique finished columns."
        )

    rows = []
    for raw_row in matrix[header_at + 1:]:
        record = {}
        any_value = False
        for header, index in zip(headers, keep):
            value = raw_row[index] if index < len(raw_row) else None
            record[header] = value
            if value not in (None, ""):
                any_value = True
        if any_value:
            rows.append(record)

    if not rows:
        raise _base.TableauError("The Tableau Crosstab contained headers but no data rows.")

    samples = {}
    for header in headers:
        for row in rows[:_SAMPLE_ROWS]:
            value = row.get(header)
            if value not in (None, ""):
                samples[header] = str(value)[:40]
                break
    return headers, rows, samples


def describe_crosstab(xlsx_bytes):
    headers, rows, samples = read_crosstab(xlsx_bytes)
    return {
        "shape": "crosstab",
        "headers": headers,
        "choices": list(headers),
        "samples": samples,
        "rows": rows,
    }


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return _base.clean_number(value)


def map_crosstab(xlsx_bytes, mapping):
    """Map finished Crosstab cells directly onto app stats; never aggregate."""
    described = describe_crosstab(xlsx_bytes)
    headers = described["headers"]
    rows = described["rows"]

    rep_col = str((mapping or {}).get("rep_name") or "").strip()
    if not rep_col or rep_col not in headers:
        raise _base.TableauError(
            "No Crosstab column is mapped to the rep name. Columns available: "
            + ", ".join(headers)
        )

    branch_col = str((mapping or {}).get("home_branch") or "").strip()
    team_col = str((mapping or {}).get("team") or "").strip()
    metrics = {
        key: str(value or "").strip()
        for key, value in ((mapping or {}).get("metrics") or {}).items()
        if str(value or "").strip()
    }
    selected = [value for value in [branch_col, team_col, *metrics.values()] if value]
    missing = sorted({value for value in selected if value not in headers})
    if missing:
        raise _base.TableauError(
            "The saved mapping names Crosstab columns that are not in this pull: "
            + ", ".join(missing[:8])
        )

    reps = []
    seen = set()
    last_branch = ""
    for row in rows:
        name = str(row.get(rep_col) or "").strip()
        if not name or name.lower() in {"grand total", "total", "all"}:
            continue
        key = name.casefold()
        if key in seen:
            raise _base.TableauError(
                f"The Crosstab contains more than one row for '{name}'. "
                "The Pi will not add or choose between duplicate Tableau rows. "
                "Pick the summarized worksheet that already has one row per rep."
            )
        seen.add(key)

        branch = str(row.get(branch_col) or "").strip() if branch_col else ""
        if branch:
            last_branch = branch
        elif branch_col:
            branch = last_branch

        rep = {
            "name": name,
            "home_branch": branch,
            "team": str(row.get(team_col) or "").strip() if team_col else "",
        }
        for stat, column in metrics.items():
            camel = STAT_TO_CAMEL.get(stat)
            if not camel:
                continue
            value = _number(row.get(column))
            if value is not None:
                rep[camel] = value
        reps.append(rep)

    if not reps:
        raise _base.TableauError(
            f"No Crosstab rows had a value in '{rep_col}'. Is that the right column?"
        )
    return reps, {"shape": "crosstab", "source": "crosstab_excel", "scaled": []}


def _branch_profile(xlsx_bytes):
    described = describe_crosstab(xlsx_bytes)
    headers = described["headers"]
    branch_col = _base.find_column(headers, _base.BRANCH_ALIASES)
    values = set()
    if branch_col:
        for row in described["rows"]:
            value = str(row.get(branch_col) or "").strip()
            if value and value.lower() != "all":
                values.add(value)
    return branch_col, values


class CrosstabMappedTableauSource(CustomTableauSource):
    """A chosen worksheet whose Tableau Crosstab cells are mapped directly."""

    def __init__(self, config=None, workbook="", sheet="", mapping=None):
        super().__init__(config, workbook, sheet)
        self.mapping = mapping or {}
        self.last_notes = {}

    def _query_crosstab(self, base, token, site_id, view_id, start, end, branch_field):
        params = {
            "maxAge": "1",
            f"vf_{_base.TABLEAU_START_FIELD}": start,
            f"vf_{_base.TABLEAU_END_FIELD}": end,
            f"vf_{branch_field}": _base.TABLEAU_HOME_BRANCH,
        }
        query = _base.urllib.parse.urlencode(
            params, quote_via=_base.urllib.parse.quote
        )
        status, raw = self._request(
            f"{base}/sites/{site_id}/views/{view_id}/crosstab/excel?{query}",
            token=token,
        )
        if status != 200:
            # Crosstab is a worksheet export. Pointing it at a dashboard is
            # the easy mistake to make, because dashboards are listed in the
            # sheet picker alongside worksheets and look identical there.
            raise _base.TableauError(
                f"Tableau Crosstab download failed (HTTP {status}) for "
                f"{self.VIEW_PATH}. Crosstab comes from a worksheet — if this "
                "is a dashboard, pick the worksheet inside it instead."
            )
        return raw

    def fetch_crosstab(self, base, token, site_id, start, end):
        """Download the selected view's Crosstab with the existing board filters."""
        view_id = self._view_id(base, token, site_id)
        candidates = [_base.TABLEAU_HOME_BRANCH_FIELD, "Home Branch"]
        tried = set()
        last_book = b""

        for candidate in candidates:
            field = str(candidate or "").strip()
            if not field or field.lower() in tried:
                continue
            tried.add(field.lower())
            book = self._query_crosstab(
                base, token, site_id, view_id, start, end, field
            )
            last_book = book
            branch_col, branch_values = _branch_profile(book)
            office = _base.TABLEAU_HOME_BRANCH.lower()
            if branch_col and branch_values and all(
                    value.lower() == office for value in branch_values):
                self.last_branch_filter_field = field
                return book
            if branch_col and branch_col.lower() not in tried:
                candidates.append(branch_col)

        self.last_branch_filter_field = candidates[-1] if candidates else ""
        return last_book

    def _pull_rows(self):
        start, end = _base.resolve_dates(self.config)
        base, token, site_id = self.signin()
        try:
            book = self.fetch_crosstab(base, token, site_id, start, end)
        finally:
            self.signout(base, token)

        reps, notes = map_crosstab(book, self.mapping)
        self.last_notes = notes
        rows = _base.to_app_rows(reps)
        self.last_remote_rows = len(rows)

        # Keep the custom mapper's existing safety behavior: when Home Branch
        # is explicitly mapped, never silently put another office on Olympia's
        # board. This is filtering/guarding only; no sales metric is changed.
        if self.mapping.get("home_branch"):
            office = _base.TABLEAU_HOME_BRANCH.lower()
            values = {
                str(row.get("home_branch") or "").strip()
                for row in rows if str(row.get("home_branch") or "").strip()
            }
            unexpected = {value for value in values if value.lower() != office}
            if unexpected:
                filtered = [
                    row for row in rows
                    if str(row.get("home_branch") or "").strip().lower() == office
                ]
                if not filtered:
                    raise _base.TableauError(
                        "That Crosstab returned no Olympia rows — it came back with "
                        + ", ".join(sorted(unexpected)[:5])
                    )
                self.branch_filter_guard_used = True
                rows = filtered
        return start, end, rows


def mapping_description(xlsx_bytes):
    """Describe the Crosstab for the existing phone mapping UI."""
    described = describe_crosstab(xlsx_bytes)
    guess = suggest_mapping(described["headers"], described["choices"])
    return {
        "shape": described["shape"],
        "headers": described["headers"],
        "choices": described["choices"],
        "samples": described["samples"],
        "suggested": guess,
        "unmapped": unmapped_columns(described["choices"], guess),
    }
