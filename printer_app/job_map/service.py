"""Business workflow for filters-first local map views and worker-owned refresh."""
from __future__ import annotations

from math import asin, cos, isfinite, radians, sin, sqrt
import time
from uuid import uuid4

from ..mod_sheet_contract import ModSheetSourceError
from .contract import JobMapSourceError, MapFilterView, MapFilters, MapQuery, MapView


EXCLUDED_LEAD_STATUSES = frozenset({'new', 'scheduled', 'do not call'})
MAX_RADIUS_MILES = 5.0
SNAPSHOT_TTL_SECONDS = 300
FILTER_TTL_SECONDS = 3600
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


def _clean_filter(value, label):
    value = str(value or '').strip()
    if len(value) > 128 or any(not char.isprintable() for char in value):
        raise ValueError(f'{label} must be a short single-line value.')
    return value


def _validated_query(latitude, longitude, market='', product_type='', rep=''):
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError) as exc:
        raise ValueError('A valid current location is required.') from exc
    if (not isfinite(latitude) or not isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ValueError('A valid current location is required.')
    return MapQuery(
        latitude=latitude,
        longitude=longitude,
        radius_miles=MAX_RADIUS_MILES,
        market=_clean_filter(market, 'Market'),
        product_type=_clean_filter(product_type, 'Product'),
        rep=_clean_filter(rep, 'Rep'),
    )


def _same_filters(left, right):
    return (
        str(left.market or '').casefold() == str(right.market or '').casefold()
        and str(left.product_type or '').casefold() == str(right.product_type or '').casefold()
        and str(left.rep or '').casefold() == str(right.rep or '').casefold()
    )


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
    """Serve local filter/job snapshots; external calls belong to the worker."""

    def __init__(self, repository, mod_sheet_source, render_pdf, clock=None):
        self.repository = repository
        self.mod_sheet_source = mod_sheet_source
        self.render_pdf = render_pdf
        self.clock = clock or time.time

    def filters(self, *, force_refresh=False):
        now = self.clock()
        snapshot = self.repository.filter_snapshot()
        captured = float(snapshot.get('captured_at', 0)) if snapshot else 0.0
        fresh = bool(snapshot and captured and now - captured <= FILTER_TTL_SECONDS)
        state = self.repository.filter_refresh_state()
        status = str(state.get('status') or '')
        running = status in ('queued', 'running')
        recent_failure = (
            status == 'failed'
            and now - float(state.get('updated', 0) or 0) < FAILED_RETRY_SECONDS
        )
        if (force_refresh or not fresh) and not running and (force_refresh or not recent_failure):
            state = self.repository.request_filter_refresh(str(uuid4()), now)
            running = str(state.get('status') or '') in ('queued', 'running')
        error = ''
        if not running and str(state.get('status') or '') == 'failed':
            error = str(state.get('error') or 'Map filter refresh failed.')
        return MapFilterView(
            filters=snapshot.get('filters') if snapshot else MapFilters(),
            refreshing=running,
            captured_at=captured,
            error=error,
        )

    @staticmethod
    def _compatible(query, snapshot):
        if not snapshot:
            return False
        saved = snapshot.get('query')
        return (
            isinstance(saved, MapQuery)
            and _same_filters(query, saved)
            and abs(saved.radius_miles - query.radius_miles) < 1e-9
            and _distance_miles(
                query.latitude, query.longitude, saved.latitude, saved.longitude
            ) <= SNAPSHOT_CENTER_TOLERANCE_MILES
        )

    def view(self, latitude, longitude, *, market='', product_type='', rep='', force_refresh=False):
        query = _validated_query(latitude, longitude, market, product_type, rep)
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
            and _same_filters(query, state_query)
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
            running = str(state.get('status') or '') in ('queued', 'running')

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
    """Worker-owned external refresh for filter choices and filtered map snapshots."""

    def __init__(self, repository, source, clock=None):
        self.repository = repository
        self.source = source
        self.clock = clock or time.time

    def requested_due(self):
        return (
            self.repository.filter_refresh_state().get('status') in ('queued', 'running')
            or self.repository.refresh_state().get('status') in ('queued', 'running')
        )

    def run_requested(self):
        if self.repository.filter_refresh_state().get('status') in ('queued', 'running'):
            self._run_filter_refresh()
        if self.repository.refresh_state().get('status') in ('queued', 'running'):
            return self._run_job_refresh()
        return self.repository.refresh_state()

    def _run_filter_refresh(self):
        state = self.repository.filter_refresh_state()
        running = dict(state, status='running', updated=self.clock(), error='')
        self.repository.save_filter_refresh_state(running)
        try:
            filters = self.source.map_filters()
            if not isinstance(filters, MapFilters):
                raise ValueError('Map filter source returned invalid data.')
            captured = self.clock()
            self.repository.replace_filter_snapshot(filters, captured)
            return self.repository.save_filter_refresh_state(dict(
                running,
                status='complete',
                updated=captured,
                error='',
            ))
        except Exception as exc:
            detail = str(exc).strip()[:500] or type(exc).__name__
            return self.repository.save_filter_refresh_state(dict(
                running,
                status='failed',
                updated=self.clock(),
                error=detail,
            ))

    def _run_job_refresh(self):
        state = self.repository.refresh_state()
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
