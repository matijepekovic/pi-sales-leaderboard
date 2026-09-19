"""Platform-neutral MOD sheet data shared with replaceable source adapters."""
from __future__ import annotations

from dataclasses import dataclass, field


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


@dataclass(frozen=True)
class SourceStatus:
    connected: bool
    username: str = ''
    alias: str = ''
    instance_url: str = ''
    detail: str = ''
