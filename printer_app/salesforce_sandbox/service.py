"""Workflow for the read-only Salesforce MOD portal sandbox."""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from datetime import date

from ..mod_sheet_contract import ModSheetSourceError, NO_MOD_SHEET_RECORDS, SourceStatus
from .adapter import SalesforceAdapterError


@dataclass(frozen=True)
class PortalSnapshot:
    status: SourceStatus
    today: str = ''
    fields: dict = dataclass_field(default_factory=dict)
    error: str = ''


@dataclass(frozen=True)
class ConnectionSnapshot:
    status: SourceStatus
    trace: tuple = dataclass_field(default_factory=tuple)
    error: str = ''


@dataclass(frozen=True)
class FieldSnapshot:
    key: str
    field: object | None = None
    trace: tuple = dataclass_field(default_factory=tuple)
    error: str = ''


@dataclass(frozen=True)
class ExplorerSnapshot:
    data: dict = dataclass_field(default_factory=dict)
    error: str = ''
    invalid: bool = False


@dataclass(frozen=True)
class GeneratedSnapshot:
    records: tuple = dataclass_field(default_factory=tuple)
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

    def connection(self):
        """Check only the saved Salesforce login; do not load filter metadata."""
        trace = []
        try:
            status = self.adapter.status(trace=trace)
            return ConnectionSnapshot(status=status, trace=tuple(trace))
        except SalesforceAdapterError as exc:
            return ConnectionSnapshot(
                status=SourceStatus(connected=False, detail=str(exc)),
                trace=tuple(trace),
                error=str(exc),
            )

    def field(self, key):
        """Resolve one portal filter independently after connection succeeds."""
        trace = []
        try:
            resolved = self.adapter.portal_field(key, trace=trace)
            return FieldSnapshot(key=key, field=resolved, trace=tuple(trace))
        except SalesforceAdapterError as exc:
            return FieldSnapshot(
                key=key,
                trace=tuple(trace),
                error=str(exc),
            )

    def explore(self, action, **parameters):
        """Run one explicitly requested, read-only exploration step."""
        if action not in ('objects', 'object', 'search', 'record', 'related'):
            return ExplorerSnapshot(error='Unknown explorer action.', invalid=True)
        try:
            data = getattr(self.adapter, 'explorer_' + action)(**parameters)
            return ExplorerSnapshot(data=data)
        except ValueError as exc:
            return ExplorerSnapshot(error=str(exc), invalid=True)
        except SalesforceAdapterError as exc:
            return ExplorerSnapshot(error=str(exc))

    def records(self, **filters):
        """Return normalized MOD records without leaking Salesforce exceptions."""
        try:
            return tuple(self.adapter.mod_sheets(**filters))
        except SalesforceAdapterError as exc:
            if str(exc) == NO_MOD_SHEET_RECORDS:
                return ()
            raise ModSheetSourceError(str(exc)) from exc

    def generate(self, **filters):
        color_code = bool(filters.pop('color_code', False))
        try:
            records = self.records(**filters)
            if not records:
                raise ModSheetSourceError(NO_MOD_SHEET_RECORDS)
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
        except ModSheetSourceError as exc:
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
