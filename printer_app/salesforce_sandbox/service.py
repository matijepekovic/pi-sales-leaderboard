"""Workflow for the read-only Salesforce MOD portal sandbox."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..mod_sheet_contract import SourceStatus
from .adapter import SalesforceAdapterError


@dataclass(frozen=True)
class PortalSnapshot:
    status: SourceStatus
    today: str = ''
    fields: dict = field(default_factory=dict)
    error: str = ''


@dataclass(frozen=True)
class GeneratedSnapshot:
    records: tuple = field(default_factory=tuple)
    start_date: str = ''
    end_date: str = ''
    market_segment: str = ''
    product_category: str = ''
    source_type: str = ''
    remove_canceled: bool = True
    remove_unconfirmed: bool = True
    color_code: bool = False
    error: str = ''


class SalesforceSandboxService:
    def __init__(self, adapter):
        self.adapter = adapter

    def portal(self):
        """Return the MOD portal shell without blocking on Salesforce CLI."""
        return PortalSnapshot(
            status=SourceStatus(connected=False, detail='Checking Salesforce…'),
            today=date.today().strftime('%-m/%-d/%Y'),
            fields={},
        )

    def metadata(self):
        """Load the CLI-selected org and filter options after the page renders."""
        try:
            status = self.adapter.status()
            fields = self.adapter.portal_fields()
            return PortalSnapshot(
                status=status,
                today=date.today().strftime('%-m/%-d/%Y'),
                fields=fields,
            )
        except SalesforceAdapterError as exc:
            return PortalSnapshot(
                status=SourceStatus(connected=False, detail=str(exc)),
                today=date.today().strftime('%-m/%-d/%Y'),
                error=str(exc),
            )

    def generate(self, **filters):
        color_code = bool(filters.pop('color_code', False))
        try:
            records = tuple(self.adapter.mod_sheets(**filters))
            return GeneratedSnapshot(
                records=records,
                start_date=filters.get('start_date', ''),
                end_date=filters.get('end_date', ''),
                market_segment=filters.get('market_segment', ''),
                product_category=filters.get('product_category', ''),
                source_type=filters.get('source_type', ''),
                remove_canceled=bool(filters.get('remove_canceled', True)),
                remove_unconfirmed=bool(filters.get('remove_unconfirmed', True)),
                color_code=color_code,
            )
        except SalesforceAdapterError as exc:
            return GeneratedSnapshot(
                start_date=filters.get('start_date', ''),
                end_date=filters.get('end_date', ''),
                market_segment=filters.get('market_segment', ''),
                product_category=filters.get('product_category', ''),
                source_type=filters.get('source_type', ''),
                remove_canceled=bool(filters.get('remove_canceled', True)),
                remove_unconfirmed=bool(filters.get('remove_unconfirmed', True)),
                color_code=color_code,
                error=str(exc),
            )
