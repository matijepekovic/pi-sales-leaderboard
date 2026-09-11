"""Normalized per-job print contract; no CUPS or Office implementation details."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Mapping

# Environment key: (attribute, label, choices). The Settings form and validation
# share this allowlist; arbitrary printer/renderer options never enter commands.
CHOICES = {
    'PRINT_PAPER': ('paper', 'Paper size', (
        ('source', 'Document / printer default'), ('tabloid', 'Tabloid — 11 × 17 in'),
        ('letter', 'Letter — 8.5 × 11 in'), ('legal', 'Legal — 8.5 × 14 in'),
        ('a4', 'A4'), ('a3', 'A3'))),
    'PRINT_ORIENTATION': ('orientation', 'Orientation', (
        ('source', 'Keep document orientation'), ('landscape', 'Landscape'), ('portrait', 'Portrait'))),
    'PRINT_COLOR': ('color', 'Color', (
        ('default', 'Printer default'), ('color', 'Color'), ('monochrome', 'Black and white'))),
    'PRINT_SIDES': ('sides', 'Sides', (
        ('default', 'Printer default'), ('one-sided', 'Single-sided'),
        ('two-sided-long-edge', 'Double-sided — long edge'),
        ('two-sided-short-edge', 'Double-sided — short edge'))),
    'EXCEL_SCALE': ('excel_scale', 'Excel scaling', (
        ('source', 'Keep workbook scaling'), ('fit-width', 'Fit all columns on one page wide'),
        ('fit-page', 'Fit each sheet on one page'), ('percent', 'Custom percentage'))),
    'EXCEL_MARGINS': ('margins', 'Excel margins', (
        ('source', 'Keep workbook margins'), ('narrow', 'Narrow — 0.25 in'),
        ('normal', 'Normal — 0.5 in'), ('none', 'None — printer may clip edges'))),
    'EXCEL_SHEETS': ('sheets', 'Excel sheets', (
        ('all', 'All visible sheets, in original order'), ('active', 'Saved active sheet only'))),
    'EXCEL_PAGE_POLICY': ('page_policy', 'Excel multi-page output', (
        ('one-page', 'Print an error sheet when the report exceeds one page'),
        ('all', 'Print the entire report, even when it has multiple pages'))),
    'PDF_SCALING': ('pdf_scaling', 'Received PDF scaling', (
        ('default', 'Printer default — send original PDF unchanged'),
        ('fit', 'Fit to selected paper'), ('actual', 'Actual size — may clip on smaller paper'))),
}
NUMBERS = {
    'PRINT_COPIES': ('copies', 'Copies', 1, 20),
    'EXCEL_SCALE_PERCENT': ('scale_percent', 'Excel custom scale (%)', 10, 400),
}
FIELDS = set(CHOICES) | set(NUMBERS)


@dataclass(frozen=True)
class PrintOptions:
    paper: str = 'source'
    orientation: str = 'source'
    color: str = 'default'
    sides: str = 'default'
    copies: int = 1
    excel_scale: str = 'source'
    scale_percent: int = 100
    margins: str = 'source'
    sheets: str = 'all'
    page_policy: str = 'one-page'
    pdf_scaling: str = 'default'

    def __post_init__(self):
        for attr, label, choices in CHOICES.values():
            if getattr(self, attr) not in {key for key, _ in choices}:
                raise ValueError('Invalid ' + label.lower())
        for attr, label, low, high in NUMBERS.values():
            value = getattr(self, attr)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{label} must be a whole number between {low} and {high}.')

    def apply(self, patch: Mapping[str, str]) -> 'PrintOptions':
        values = {}
        for key, value in patch.items():
            if key in CHOICES:
                values[CHOICES[key][0]] = value
            elif key in NUMBERS:
                if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
                    raise ValueError('Invalid ' + NUMBERS[key][1].lower())
                values[NUMBERS[key][0]] = int(value)
            else:
                raise ValueError('Unsupported print setting')
        return replace(self, **values)

    def environment(self) -> dict[str, str]:
        return {key: str(getattr(self, spec[0])) for key, spec in {**CHOICES, **NUMBERS}.items()}

    def snapshot(self) -> dict:
        return asdict(self)

    def error_sheet(self) -> 'PrintOptions':
        # Never multiply an error, duplex it, or crop it using report settings.
        return replace(self, paper='letter', orientation='portrait', copies=1,
                       sides='one-sided', pdf_scaling='fit')
