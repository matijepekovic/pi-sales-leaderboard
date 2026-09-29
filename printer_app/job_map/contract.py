"""Platform-neutral job-map contracts."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MapQuery:
    """Business filters for one normalized source snapshot."""

    market: str = ''
    product_type: str = ''
    rep: str = ''


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
class MapSourceDiagnostics:
    """Normalized counts produced while the external source builds a job snapshot."""

    appointment_rows: int = 0
    grouped_jobs: int = 0
    jobs_with_location: int = 0
    jobs_missing_location: int = 0


@dataclass(frozen=True)
class MapSourceSnapshot:
    """One complete source refresh: normalized jobs plus source-stage evidence."""

    jobs: tuple[MapJob, ...] = ()
    diagnostics: MapSourceDiagnostics = MapSourceDiagnostics()


@dataclass(frozen=True)
class MapCandidateDiagnostic:
    """Why one sourced job is or is not visible from the current phone location."""

    work_order_number: str
    lead_name: str
    lead_status: str
    distance_miles: float
    latitude: float
    longitude: float
    outcome: str


@dataclass(frozen=True)
class MapDiagnostics:
    """End-to-end evidence for the currently displayed map result."""

    appointment_rows: int = 0
    grouped_jobs: int = 0
    jobs_with_location: int = 0
    jobs_missing_location: int = 0
    snapshot_jobs: int = 0
    excluded_status: int = 0
    outside_radius: int = 0
    visible_jobs: int = 0
    candidates: tuple[MapCandidateDiagnostic, ...] = ()


@dataclass(frozen=True)
class MapFilters:
    """Normalized filter choices available before location is requested."""

    markets: tuple[str, ...] = ()
    product_types: tuple[str, ...] = ()
    reps: tuple[str, ...] = ()


@dataclass(frozen=True)
class MapFilterView:
    """Local filter choices plus background-refresh state."""

    filters: MapFilters
    refreshing: bool = False
    captured_at: float = 0.0
    error: str = ''


@dataclass(frozen=True)
class MapView:
    """One local map response plus background-refresh state and evidence."""

    jobs: tuple[MapJob, ...]
    refreshing: bool = False
    stale: bool = False
    captured_at: float = 0.0
    error: str = ''
    diagnostics: MapDiagnostics = MapDiagnostics()


class JobMapSourceError(RuntimeError):
    """Normalized source failure for the job map."""
