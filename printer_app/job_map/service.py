"""Business workflow for local mapped jobs, background refresh, and MOD sheets."""
from __future__ import annotations

from math import asin, cos, isfinite, radians, sin, sqrt
import time
from uuid import uuid4

from ..mod_sheet_contract import ModSheetSourceError
from .contract import JobMapSourceError, MapQuery, MapView


EXCLUDED_LEAD_STATUSES = frozenset({'new', 'scheduled', 'do not call'})
MAX_RADIUS_MILES = 5.0
SNAPSHOT_TTL_SECONDS = 300
SNAPSHOT_CENTER_TOLERANCE_MILES = 0.25
FAILED_RETRY_SECONDS = 60
_EARTH_RADIUS_MILES = 3958.7613


def _distance_miles(latitude_a, longitude_a, latitude_b, longitude_b):
    lat1 = radians(latitude_a)
    lat2 = radians(latitude_b)
    delta_lat = lat2 - lat1
    delta_lon = radians(longitude_b - longitude_a)
    value = (
        sin(delta_lat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_MILES * asin(sqrt(min(1.0, max(0.0, value))))


def _validated_query(latitude, longitude):
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError) as exc:
        raise ValueError('A valid current location is required.') from exc
    if (not isfinite(latitude) or not isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ValueError('A valid current location is required.')
    return MapQuery(latitude=latitude, longitude=longitude, radius_miles=MAX_RADIUS_MILES)


def _eligible_jobs(query, jobs):
    return tuple(sorted(
        (
            job for job in jobs
            if str(job.lead_status or '').strip().casefold() not in EXCLUDED_LEAD_STATUSES
            and _distance_miles(
                query.latitude, query.longitude, job.latitude, job.longitude
            ) <= MAX_RADIUS_MILES
        ),
        key=lambda job: (str(job.lead_name or '').casefold(), job.work_order_number),
    ))


class JobMapService:
    """Serve only local map data; source calls are owned by JobMapRefreshService."""

    def __init__(self, repository, mod_sheet_source, render_pdf, clock=None):
        self.repository = repository
        self.mod_sheet_source = mod_sheet_source
        self.render_pdf = render_pdf
        self.clock = clock or time.time

    @staticmethod
    def _compatible(query, snapshot):
        if not snapshot:
            return False
        saved = snapshot.get('query')
        return (
            isinstance(saved, MapQuery)
            and abs(saved.radius_miles - query.radius_miles) < 1e-9
            and _distance_miles(
                query.latitude, query.longitude, saved.latitude, saved.longitude
            ) <= SNAPSHOT_CENTER_TOLERANCE_MILES
        )

    def view(self, latitude, longitude, *, force_refresh=False):
        query = _validated_query(latitude, longitude)
        now = self.clock()
        snapshot = self.repository.snapshot()
        compatible = self._compatible(query, snapshot)
        captured = float(snapshot.get('captured_at', 0)) if compatible else 0.0
        fresh = bool(compatible and captured and now - captured <= SNAPSHOT_TTL_SECONDS)

        state = self.repository.refresh_state()
        status = str(state.get('status') or '')
        running = status in ('queued', 'running')
        state_query = state.get('query')
        same_request = (
            isinstance(state_query, MapQuery)
            and _distance_miles(
                query.latitude, query.longitude, state_query.latitude, state_query.longitude
            ) <= SNAPSHOT_CENTER_TOLERANCE_MILES
        )
        recent_failure = (
            status == 'failed'
            and same_request
            and now - float(state.get('updated', 0) or 0) < FAILED_RETRY_SECONDS
        )

        if (force_refresh or not fresh) and not running and (force_refresh or not recent_failure):
            state = self.repository.request_refresh(str(uuid4()), query, now)
            status = str(state.get('status') or '')
            running = status in ('queued', 'running')

        jobs = _eligible_jobs(query, snapshot.get('jobs', ())) if compatible else ()
        error = ''
        if not running and str(state.get('status') or '') == 'failed' and same_request:
            error = str(state.get('error') or 'Nearby map refresh failed.')

        return MapView(
            jobs=jobs,
            refreshing=running,
            stale=bool(compatible and not fresh),
            captured_at=captured,
            error=error,
        )

    def mod_sheet(self, work_order_number):
        """Render the current normalized MOD sheet for exactly one work order."""
        number = str(work_order_number or '').strip()
        if not number or len(number) > 255 or any(ord(char) < 32 for char in number):
            raise ValueError('A work-order number is required.')
        try:
            records = tuple(self.mod_sheet_source.work_orders((number,)))
        except ModSheetSourceError as exc:
            raise JobMapSourceError(str(exc)) from exc
        matches = [record for record in records
                   if str(record.work_order_number or '').strip().casefold() == number.casefold()]
        if len(matches) != 1:
            raise LookupError('Work order was not found.')
        return self.render_pdf(matches)


class JobMapRefreshService:
    """Worker-owned external refresh for the durable local map snapshot."""

    def __init__(self, repository, source, clock=None):
        self.repository = repository
        self.source = source
        self.clock = clock or time.time

    def requested_due(self):
        return self.repository.refresh_state().get('status') in ('queued', 'running')

    def run_requested(self):
        state = self.repository.refresh_state()
        if state.get('status') not in ('queued', 'running'):
            return state
        query = state.get('query')
        if not isinstance(query, MapQuery):
            failed = dict(state, status='failed', updated=self.clock(), error='Map refresh request is invalid.')
            return self.repository.save_refresh_state(failed)

        running = dict(state, status='running', updated=self.clock(), error='')
        self.repository.save_refresh_state(running)
        try:
            jobs = tuple(self.source.map_jobs(query))
            captured = self.clock()
            self.repository.replace_snapshot(query, jobs, captured)
            return self.repository.save_refresh_state(dict(
                running,
                status='complete',
                updated=captured,
                count=len(jobs),
                error='',
            ))
        except Exception as exc:
            detail = str(exc).strip()[:500] or type(exc).__name__
            return self.repository.save_refresh_state(dict(
                running,
                status='failed',
                updated=self.clock(),
                error=detail,
            ))
