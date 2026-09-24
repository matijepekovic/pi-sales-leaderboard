"""Workflow for the read-only Salesforce MOD portal sandbox."""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from datetime import date
from threading import Lock

from ..mod_sheet_contract import ModSheetSourceError, NO_MOD_SHEET_RECORDS, SourceStatus
from .adapter import PortalField, SalesforceAdapterError


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
    saved: bool = False


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
    assigned_service_resource: str = ''
    remove_canceled: bool = True
    remove_unconfirmed: bool = True
    color_code: bool = False
    error: str = ''


class SalesforceSandboxService:
    def __init__(self, adapter, *, rep_repository=None):
        self.adapter = adapter
        # The worker only consumes records; the web composition supplies rep storage.
        self.rep_repository = rep_repository
        self._rep_refresh_lock = Lock()

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
        """Read saved rep options locally; only explicit refresh may query their source."""
        if key == 'assigned_service_resource':
            names = self.rep_repository.names() if self.rep_repository is not None else None
            return FieldSnapshot(
                key=key, saved=names is not None,
                field=PortalField('Assigned Service Resource', 'assigned_service_resources', names or ()),
            )
        trace = []
        try:
            resolved = self.adapter.portal_field(key, trace=trace)
            return FieldSnapshot(key=key, field=resolved, trace=tuple(trace))
        except SalesforceAdapterError as exc:
            return FieldSnapshot(key=key, trace=tuple(trace), error=str(exc))

    def refresh_reps(self, *, start_date='', end_date='', market_segment='',
                     product_category='', source_type=''):
        """Replace saved names after a complete lightweight lookup; reports are separate."""
        key, trace = 'assigned_service_resource', []
        try:
            if self.rep_repository is None:
                raise ModSheetSourceError('Rep-list storage is not configured.')
            if (not isinstance(market_segment, str) or len(market_segment) > 128
                    or any(not char.isprintable() for char in market_segment)):
                raise ModSheetSourceError('Market Segment must be a short single-line value.')
            with self._rep_refresh_lock:
                names = tuple(self.adapter.assigned_resource_names(
                    start_date=start_date, end_date=end_date,
                    market_segment=market_segment.strip(), product_category=product_category,
                    source_type=source_type, trace=trace,
                ))
                if any(not isinstance(name, str) for name in names):
                    raise ModSheetSourceError('Rep lookup returned invalid names.')
                names = tuple(sorted({name.strip() for name in names if name.strip()}, key=str.casefold))
                self.rep_repository.replace(names)
            return FieldSnapshot(
                key=key, saved=True, trace=tuple(trace),
                field=PortalField('Assigned Service Resource', 'assigned_service_resources', names),
            )
        except (SalesforceAdapterError, ModSheetSourceError) as exc:
            return FieldSnapshot(key=key, trace=tuple(trace), error=str(exc))

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
        """Filter complete normalized sheets, retaining every co-assigned rep."""
        selected = str(filters.pop('assigned_service_resource', '') or '').strip().casefold()
        limit = filters.get('limit', 1000)
        if selected:
            # Filtering before grouping would lose co-reps and could revive a
            # canceled assignment. Read all pages before selecting whole sheets.
            filters['limit'] = None
        try:
            records = tuple(self.adapter.mod_sheets(**filters))
        except SalesforceAdapterError as exc:
            if str(exc) == NO_MOD_SHEET_RECORDS:
                return ()
            raise ModSheetSourceError(str(exc)) from exc
        if selected:
            records = tuple(record for record in records
                            if any(name.casefold() == selected
                                   for name in record.assigned_service_resources))
            if limit is not None:
                records = records[:max(1, min(int(limit), 1000))]
        return records

    def lead_statuses(self, work_order_numbers):
        """Resolve current lead statuses without any appointment or date filter."""
        try:
            return tuple(self.adapter.lead_statuses(work_order_numbers))
        except SalesforceAdapterError as exc:
            raise ModSheetSourceError(str(exc)) from exc

    def work_orders(self, work_order_numbers):
        """Resolve complete normalized appointment data directly by work-order number."""
        try:
            return tuple(self.adapter.work_orders(work_order_numbers))
        except SalesforceAdapterError as exc:
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
                assigned_service_resource=filters.get('assigned_service_resource', ''),
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
                assigned_service_resource=filters.get('assigned_service_resource', ''),
                remove_canceled=bool(filters.get('remove_canceled', True)),
                remove_unconfirmed=bool(filters.get('remove_unconfirmed', True)),
                color_code=color_code,
                error=str(exc),
            )
