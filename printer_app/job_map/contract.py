"""Platform-neutral job-map contracts."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MapQuery:
    """Geographic scope for one nearby-job lookup."""

    latitude: float
    longitude: float
    radius_miles: float


@dataclass(frozen=True)
class MapJob:
    """One mapped work order with a link back to its source record."""

    source_id: str
    work_order_number: str
    lead_name: str
    lead_status: str
    latitude: float
    longitude: float
    source_record_url: str
    market: str = ''
    product_type: str = ''
    assigned_reps: tuple[str, ...] = ()


@dataclass(frozen=True)
class MapView:
    """One local map response plus background-refresh state."""

    jobs: tuple[MapJob, ...]
    refreshing: bool = False
    stale: bool = False
    captured_at: float = 0.0
    error: str = ''


class JobMapSourceError(RuntimeError):
    """Normalized source failure for the job map."""
