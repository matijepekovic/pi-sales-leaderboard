"""Platform-neutral MOD sheet data shared with replaceable source adapters."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorkOrderLeadStatus:
    """Current lead status resolved by work-order number, independently of dates."""

    work_order_number: str
    lead_source_id: str = ''
    sales_lead_status: str = ''


@dataclass(frozen=True)
class ModSheetRecord:
    source_id: str
    work_order_number: str = ''
    local_scheduled_start_time: str = ''
    canvass_set_by: str = ''
    lead_name: str = ''
    address: str = ''
    phone: str = ''
    scheduled_start: str = ''
    assigned_service_resources: tuple[str, ...] = field(default_factory=tuple)
    set_by: str = ''
    work_type: str = ''
    product_interest: str = ''
    source: str = ''
    sub_source: str = ''
    lead_description: str = ''
    sales_lead_status: str = ''
    lead_source_id: str = ''
    appointment_date: str = ''


@dataclass(frozen=True)
class SourceStatus:
    connected: bool
    username: str = ''
    alias: str = ''
    instance_url: str = ''
    detail: str = ''


class ModSheetSourceError(RuntimeError):
    """Normalized failure from the replaceable MOD-sheet source boundary."""


NO_MOD_SHEET_RECORDS = 'No Records Found for Selected Criteria'
