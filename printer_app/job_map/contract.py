"""Platform-neutral contracts for the local job map and its source sync."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MapQuery:
    """Local map filters. Phone location is deliberately not part of source sync."""

    market: str = ''
    product_type: str = ''
    rep: str = ''


@dataclass(frozen=True)
class MapRecord:
    """One normalized source appointment stored locally before map grouping."""

    source_record_id: str
    work_order_id: str
    work_order_number: str
    scheduled_at: float
    scheduled_day: str
    created_at: float
    canceled: bool
    lead_name: str
    lead_status: str
    latitude: float | None
    longitude: float | None
    source_record_url: str
    market: str = ''
    product_type: str = ''
    assigned_rep: str = ''


@dataclass(frozen=True)
class MapJob:
    """One grouped work order ready for display and exact distance filtering."""

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
class MapCandidateDiagnostic:
    """Why one locally grouped job is or is not visible from the phone."""

    work_order_number: str
    lead_name: str
    lead_status: str
    distance_miles: float
    latitude: float
    longitude: float
    outcome: str


@dataclass(frozen=True)
class MapDiagnostics:
    """Evidence from local storage through the one phone-distance calculation."""

    local_records: int = 0
    grouped_jobs: int = 0
    rep_matched_jobs: int = 0
    jobs_with_location: int = 0
    jobs_missing_location: int = 0
    excluded_status: int = 0
    outside_radius: int = 0
    visible_jobs: int = 0
    candidates: tuple[MapCandidateDiagnostic, ...] = ()


@dataclass(frozen=True)
class MapFilters:
    """Normalized filter choices available before phone location is requested."""

    markets: tuple[str, ...] = ()
    product_types: tuple[str, ...] = ()
    reps: tuple[str, ...] = ()


@dataclass(frozen=True)
class MapFilterView:
    """Filter choices plus optional lightweight metadata refresh state."""

    filters: MapFilters
    refreshing: bool = False
    captured_at: float = 0.0
    error: str = ''


@dataclass(frozen=True)
class MapView:
    """One entirely-local map result."""

    jobs: tuple[MapJob, ...]
    captured_at: float = 0.0
    error: str = ''
    diagnostics: MapDiagnostics = MapDiagnostics()


@dataclass(frozen=True)
class MapSyncRequest:
    """One bounded historical backfill requested by the map UI."""

    since_date: str
    through_date: str
    market: str


@dataclass(frozen=True)
class MapSyncView:
    """Durable worker progress for the current or most recent map history sync."""

    status: str = ''
    since_date: str = ''
    through_date: str = ''
    market: str = ''
    chunk_start: str = ''
    chunk_end: str = ''
    completed_chunks: int = 0
    total_chunks: int = 0
    records_written: int = 0
    updated: float = 0.0
    error: str = ''


class JobMapSourceError(RuntimeError):
    """Normalized external-source failure for map synchronization."""
