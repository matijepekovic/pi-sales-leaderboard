"""Platform-neutral job-map contracts."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MapJob:
    """One mapped work order with a link back to its source record."""

    source_id: str
    work_order_number: str
    lead_name: str
    lead_status: str
    market_segment: str
    assigned_service_resources: tuple[str, ...]
    latitude: float
    longitude: float
    source_record_url: str


class JobMapSourceError(RuntimeError):
    """Normalized source failure for the job map."""
