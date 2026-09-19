"""Workflow for the read-only Salesforce MOD portal sandbox."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..mod_sheet_contract import SourceStatus
from .adapter import SalesforceAdapterError


@dataclass(frozen=True)
class PortalSnapshot:
    status: SourceStatus
    orgs: tuple = field(default_factory=tuple)
    selected_org: str = ''
    today: str = ''
    fields: dict = field(default_factory=dict)
    error: str = ''


@dataclass(frozen=True)
class GeneratedSnapshot:
    records: tuple = field(default_factory=tuple)
    selected_org: str = ''
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

    @staticmethod
    def _selected_org(orgs, target_org):
        selected = str(target_org or '').strip()
        if selected:
            return selected
        default = next((org for org in orgs if org.get('default')), None)
        return str(default.get('value') or '') if default else ''

    def portal(self, target_org=''):
        """Return the MOD portal shell without blocking on Salesforce CLI."""
        orgs = tuple(self.adapter.orgs())
        selected = self._selected_org(orgs, target_org)
        return PortalSnapshot(
            status=SourceStatus(connected=False, detail='Checking Salesforce…'),
            orgs=orgs,
            selected_org=selected,
            today=date.today().strftime('%-m/%-d/%Y'),
            fields={},
        )

    def metadata(self, target_org=''):
        """Load connection state and filter options separately from page rendering."""
        orgs = tuple(self.adapter.orgs())
        selected = self._selected_org(orgs, target_org)
        try:
            status = self.adapter.status(selected)
            fields = self.adapter.portal_fields(selected)
            return PortalSnapshot(
                status=status,
                orgs=orgs,
                selected_org=selected,
                today=date.today().strftime('%-m/%-d/%Y'),
                fields=fields,
            )
        except SalesforceAdapterError as exc:
            return PortalSnapshot(
                status=SourceStatus(connected=False, detail=str(exc)),
                orgs=orgs,
                selected_org=selected,
                today=date.today().strftime('%-m/%-d/%Y'),
                error=str(exc),
            )

    def generate(self, target_org='', **filters):
        color_code = bool(filters.pop('color_code', False))
        try:
            records = tuple(self.adapter.mod_sheets(target_org, **filters))
            return GeneratedSnapshot(
                records=records,
                selected_org=target_org,
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
                selected_org=target_org,
                start_date=filters.get('start_date', ''),
                end_date=filters.get('end_date', ''),
                market_segment=filters.get('market_segment', ''),
                product_category=filters.get('product_category', ''),
                source_type=filters.get('source_type', ''),
                remove_canceled=bool(filters.get('remove_canceled', True)),
                remove_unconfirmed=bool(filters.get('remove_unconfirmed', True)),
                color_code=bool(filters.get('color_code', False)),
                error=str(exc),
            )
