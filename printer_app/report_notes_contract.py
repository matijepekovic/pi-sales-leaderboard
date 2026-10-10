"""Report-notes settings and normalized rendered-table data; no vendor or PDF APIs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import unicodedata


class ReportNotesError(ValueError):
    """Safe, actionable report-notes error (never contains customer cell contents)."""


def heading(value: str) -> str:
    """Keep human labels, ignoring line wrapping and displayed sort arrows."""
    return ' '.join(unicodedata.normalize('NFKC', value).replace('↑', '').replace('↓', '').split())


@dataclass(frozen=True)
class ReportNotesOptions:
    enabled: bool = False
    columns: tuple[str, ...] = ()
    font_size: float = 12
    row_spacing_mm: float = 8
    table_gap_mm: float = 5

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ReportNotesError('Notes enabled must be true or false.')
        if not isinstance(self.columns, tuple) or len(self.columns) > 30:
            raise ReportNotesError('Choose at most 30 notes columns.')
        if any(not isinstance(c, str) or not c.strip() or len(c) > 200 or
               not c.isprintable() for c in self.columns):
            raise ReportNotesError('Invalid notes column.')
        keys = [heading(c).casefold() for c in self.columns]
        if len(keys) != len(set(keys)):
            raise ReportNotesError('Choose each notes column only once.')
        if self.enabled and not self.columns:
            raise ReportNotesError('Choose at least one column for the notes overlay.')
        for name, low, high in (('font_size', 6, 36), ('row_spacing_mm', 0, 100), ('table_gap_mm', 0, 50)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ReportNotesError(f'{name.replace("_", " ")} must be between {low} and {high}.')

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or not set(value) <= set(cls.__dataclass_fields__):
            raise ReportNotesError('Invalid notes settings.')
        fields = dict(value)
        if 'columns' in fields:
            if not isinstance(fields['columns'], (list, tuple)):
                raise ReportNotesError('Notes columns must be a list.')
            fields['columns'] = tuple(fields['columns'])
        return cls(**fields)

    def snapshot(self) -> dict:
        result = asdict(self)
        result['columns'] = list(self.columns)
        return result


@dataclass(frozen=True)
class PageTable:
    """Physical points in visible-page coordinates, origin at the top left.

    Rows contain only this page's detail records, in printed order. No PDF,
    workbook, Salesforce, or Gallery objects cross this boundary.
    """
    width: float
    height: float
    left: float
    bottom: float
    footer_top: float
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class ReportTables:
    columns: tuple[str, ...]
    pages: tuple[PageTable | None, ...]


@dataclass(frozen=True)
class NotesPlacement:
    page: int
    rows: int
    scale: float
    table_bottom: float
    notes_top: float
    notes_bottom: float
    footer_top: float
