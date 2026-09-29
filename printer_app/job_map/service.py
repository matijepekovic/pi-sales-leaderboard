"""Business workflow for local job-map views and worker-owned history sync."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from math import asin, cos, isfinite, radians, sin, sqrt
import time
from uuid import uuid4

from ..mod_sheet_contract import ModSheetSourceError
from .contract import (
    JobMapSourceError, MapCandidateDiagnostic, MapDiagnostics, MapFilterView,
    MapFilters, MapJob, MapQuery, MapRecord, MapSyncRequest, MapSyncView, MapView,
)


EXCLUDED_LEAD_STATUSES = frozenset({'new', 'scheduled', 'do not call'})
MAX_RADIUS_MILES = 5.0
FILTER_TTL_SECONDS = 3600
FAILED_RETRY_SECONDS = 60
SYNC_CHUNK_DAYS = 31
INCREMENTAL_INTERVAL_SECONDS = 3600
_EARTH_RADIUS_MILES = 3958.7613


def _distance_miles(latitude_a, longitude_a, latitude_b, longitude_b):
    """One exact phone-to-job distance calculation."""
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


def _validated_location(latitude, longitude):
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError) as exc:
        raise ValueError('A valid current location is required.') from exc
    if (not isfinite(latitude) or not isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ValueError('A valid current location is required.')
    return latitude, longitude


def _query(market='', product_type='', rep=''):
    return MapQuery(
        market=_clean_filter(market, 'Market'),
        product_type=_clean_filter(product_type, 'Product'),
        rep=_clean_filter(rep, 'Rep'),
    )


def _merge_filters(*sources):
    buckets = {'markets': {}, 'product_types': {}, 'reps': {}}
    for source in sources:
        if not isinstance(source, MapFilters):
            continue
        for key in buckets:
            for value in getattr(source, key):
                clean = str(value or '').strip()
                if clean:
                    buckets[key].setdefault(clean.casefold(), clean)
    return MapFilters(
        markets=tuple(sorted(buckets['markets'].values(), key=str.casefold)),
        product_types=tuple(sorted(buckets['product_types'].values(), key=str.casefold)),
        reps=tuple(sorted(buckets['reps'].values(), key=str.casefold)),
    )


def _product_matches(value, selected):
    selected = str(selected or '').strip()
    if not selected or selected.casefold() == 'all':
        return True
    wanted = selected.casefold()
    return any(
        part.strip().casefold() == wanted
        for part in str(value or '').split(';')
        if part.strip()
    )


def _group_records(records, query):
    """Preserve appointment grouping before rep selection, using only local records."""
    grouped = {}
    product_records = 0
    for record in records:
        if not isinstance(record, MapRecord) or not _product_matches(record.product_type, query.product_type):
            continue
        product_records += 1
        current = grouped.get(record.work_order_id)
        candidate = {
            'record': record,
            'reps': [record.assigned_rep] if record.assigned_rep else [],
        }
        if current is None:
            grouped[record.work_order_id] = candidate
            continue

        selected = current['record']
        if selected.canceled and not record.canceled:
            grouped[record.work_order_id] = candidate
            continue
        if record.canceled and not selected.canceled:
            continue

        incoming_order = (record.scheduled_at, record.created_at)
        current_order = (selected.scheduled_at, selected.created_at)
        if incoming_order > current_order:
            grouped[record.work_order_id] = candidate
            continue
        if incoming_order == current_order and record.assigned_rep:
            if record.assigned_rep not in current['reps']:
                current['reps'].append(record.assigned_rep)

    selected_rep = str(query.rep or '').strip().casefold()
    matched = []
    for value in grouped.values():
        if selected_rep and not any(
            str(name or '').strip().casefold() == selected_rep
            for name in value['reps']
        ):
            continue
        matched.append(value)
    return product_records, grouped, matched


def _evaluate_local(latitude, longitude, records, query):
    local_records, grouped, matched = _group_records(records, query)
    visible = []
    candidates = []
    missing_location = 0
    excluded_status = 0
    outside_radius = 0
    with_location = 0

    for value in matched:
        record = value['record']
        if record.latitude is None or record.longitude is None:
            missing_location += 1
            continue

        with_location += 1
        job = MapJob(
            source_id=record.work_order_id,
            work_order_number=record.work_order_number,
            lead_name=record.lead_name,
            lead_status=record.lead_status,
            latitude=record.latitude,
            longitude=record.longitude,
            source_record_url=record.source_record_url,
            market=record.market,
            product_type=record.product_type,
            assigned_reps=tuple(value['reps']),
        )
        distance = _distance_miles(latitude, longitude, job.latitude, job.longitude)
        if str(job.lead_status or '').strip().casefold() in EXCLUDED_LEAD_STATUSES:
            outcome = 'excluded-status'
            excluded_status += 1
        elif distance > MAX_RADIUS_MILES:
            outcome = 'outside-radius'
            outside_radius += 1
        else:
            outcome = 'visible'
            visible.append(job)

        candidates.append(MapCandidateDiagnostic(
            work_order_number=job.work_order_number,
            lead_name=job.lead_name,
            lead_status=job.lead_status,
            distance_miles=distance,
            latitude=job.latitude,
            longitude=job.longitude,
            outcome=outcome,
        ))

    visible.sort(
        key=lambda job: (str(job.lead_name or '').casefold(), job.work_order_number)
    )
    candidates.sort(
        key=lambda item: (item.distance_miles, item.work_order_number)
    )
    return tuple(visible), MapDiagnostics(
        local_records=local_records,
        grouped_jobs=len(grouped),
        rep_matched_jobs=len(matched),
        jobs_with_location=with_location,
        jobs_missing_location=missing_location,
        excluded_status=excluded_status,
        outside_radius=outside_radius,
        visible_jobs=len(visible),
        candidates=tuple(candidates[:25]),
    )


def _parse_day(value, label):
    try:
        return datetime.strptime(str(value or '').strip(), '%Y-%m-%d').date()
    except ValueError as exc:
        raise ValueError(f'{label} must be a valid YYYY-MM-DD date.') from exc


class JobMapService:
    """Read local history for map views; web requests never fetch job history externally."""

    def __init__(self, repository, mod_sheet_source, render_pdf, clock=None):
        self.repository = repository
        self.mod_sheet_source = mod_sheet_source
        self.render_pdf = render_pdf
        self.clock = clock or time.time

    def filters(self, *, force_refresh=False):
        now = self.clock()
        local = self.repository.local_filters()
        snapshot = self.repository.filter_snapshot()
        saved = snapshot.get('filters') if snapshot else MapFilters()
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
            filters=_merge_filters(saved, local),
            refreshing=running,
            captured_at=max(captured, self.repository.latest_sync_time()),
            error=error,
        )

    def view(self, latitude, longitude, *, market='', product_type='', rep=''):
        latitude, longitude = _validated_location(latitude, longitude)
        query = _query(market, product_type, rep)
        records = self.repository.records(market=query.market)
        jobs, diagnostics = _evaluate_local(latitude, longitude, records, query)

        error = ''
        coverage = self.repository.coverage()
        sync = self.repository.sync_state()
        if query.market and not records and query.market.casefold() not in coverage:
            if (
                sync.status in ('queued', 'running')
                and sync.market.casefold() == query.market.casefold()
            ):
                error = f'Local map history for {query.market} is still loading.'
            else:
                error = (
                    f'No local map history is loaded for {query.market}. '
                    'Load a history range first.'
                )

        return MapView(
            jobs=jobs,
            captured_at=self.repository.latest_sync_time(query.market),
            error=error,
            diagnostics=diagnostics,
        )

    def request_sync(self, *, since_date, through_date, market):
        since = _parse_day(since_date, 'Since date')
        through = _parse_day(through_date, 'Through date')
        if through < since:
            raise ValueError('Through date must be on or after Since date.')
        market = _clean_filter(market, 'Market')
        if not market:
            raise ValueError('Choose a market before loading map history.')
        request = MapSyncRequest(
            since_date=since.isoformat(),
            through_date=through.isoformat(),
            market=market,
        )
        return self.repository.request_sync(str(uuid4()), request, self.clock())

    def sync_status(self):
        return self.repository.sync_state(), self.repository.coverage()

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


class JobMapSyncService:
    """Worker-owned external metadata refresh and bounded history backfill."""

    def __init__(self, repository, source, clock=None):
        self.repository = repository
        self.source = source
        self.clock = clock or time.time

    def requested_due(self):
        return (
            self.repository.filter_refresh_state().get('status') in ('queued', 'running')
            or self.repository.sync_state().status in ('queued', 'running')
            or self.repository.next_incremental(
                self.clock(), interval_seconds=INCREMENTAL_INTERVAL_SECONDS
            ) is not None
        )

    def run_requested(self):
        if self.repository.filter_refresh_state().get('status') in ('queued', 'running'):
            self._run_filter_refresh()
        if self.repository.sync_state().status in ('queued', 'running'):
            return self._run_history_sync()
        if self.repository.next_incremental(
                self.clock(), interval_seconds=INCREMENTAL_INTERVAL_SECONDS) is not None:
            self._run_incremental()
        return self.repository.sync_state()

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

    @staticmethod
    def _chunks(since, through):
        current = since
        while current <= through:
            end = min(current + timedelta(days=SYNC_CHUNK_DAYS - 1), through)
            yield current, end
            current = end + timedelta(days=1)

    def _run_history_sync(self):
        initial = self.repository.sync_state()
        try:
            since = _parse_day(initial.since_date, 'Since date')
            through = _parse_day(initial.through_date, 'Through date')
            market = _clean_filter(initial.market, 'Market')
            if not market or through < since:
                raise ValueError('Map history sync request is invalid.')
        except ValueError as exc:
            failed = MapSyncView(
                **{**initial.__dict__, 'status': 'failed', 'updated': self.clock(),
                   'error': str(exc)}
            )
            return self.repository.save_sync_state(failed)

        chunks = tuple(self._chunks(since, through))
        cursor_floor = self.clock()
        running = MapSyncView(
            status='running',
            since_date=initial.since_date,
            through_date=initial.through_date,
            market=market,
            total_chunks=len(chunks),
            updated=self.clock(),
        )
        self.repository.save_sync_state(running)

        written = 0
        try:
            for index, (start, end) in enumerate(chunks, start=1):
                progress = MapSyncView(
                    status='running',
                    since_date=initial.since_date,
                    through_date=initial.through_date,
                    market=market,
                    chunk_start=start.isoformat(),
                    chunk_end=end.isoformat(),
                    completed_chunks=index - 1,
                    total_chunks=len(chunks),
                    records_written=written,
                    updated=self.clock(),
                )
                self.repository.save_sync_state(progress)
                records = tuple(self.source.map_records(
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    market=market,
                ))
                if any(not isinstance(record, MapRecord) for record in records):
                    raise ValueError('Map history source returned invalid data.')
                written += self.repository.replace_range(
                    market, start.isoformat(), end.isoformat(), records, self.clock()
                )
                self.repository.save_sync_state(MapSyncView(
                    status='running',
                    since_date=initial.since_date,
                    through_date=initial.through_date,
                    market=market,
                    chunk_start=start.isoformat(),
                    chunk_end=end.isoformat(),
                    completed_chunks=index,
                    total_chunks=len(chunks),
                    records_written=written,
                    updated=self.clock(),
                ))

            completed_at = self.clock()
            self.repository.update_coverage(
                market,
                since.isoformat(),
                through.isoformat(),
                completed_at,
                cursor_at=cursor_floor,
            )
            return self.repository.save_sync_state(MapSyncView(
                status='complete',
                since_date=initial.since_date,
                through_date=initial.through_date,
                market=market,
                completed_chunks=len(chunks),
                total_chunks=len(chunks),
                records_written=written,
                updated=completed_at,
            ))
        except Exception as exc:
            current = self.repository.sync_state()
            detail = str(exc).strip()[:700] or type(exc).__name__
            return self.repository.save_sync_state(MapSyncView(
                status='failed',
                since_date=initial.since_date,
                through_date=initial.through_date,
                market=market,
                chunk_start=current.chunk_start,
                chunk_end=current.chunk_end,
                completed_chunks=current.completed_chunks,
                total_chunks=len(chunks),
                records_written=current.records_written,
                updated=self.clock(),
                error=detail,
            ))

    def _run_incremental(self):
        now = self.clock()
        coverage = self.repository.next_incremental(
            now, interval_seconds=INCREMENTAL_INTERVAL_SECONDS
        )
        if not coverage:
            return 0

        market = str(coverage.get('market') or '').strip()
        since_date = str(coverage.get('since_date') or '')
        try:
            cursor = float(coverage.get('cursor_at', 0) or 0)
        except (TypeError, ValueError):
            cursor = 0.0
        through_date = date.today().isoformat()
        cursor_floor = now
        if not market or not since_date or cursor <= 0:
            self.repository.mark_incremental(
                market, through_date, cursor or now, now,
                error='Map history incremental state is invalid.',
            )
            return 0

        try:
            records = tuple(self.source.map_records_changed(
                modified_since=cursor,
                start_date=since_date,
                end_date=through_date,
                market=market,
            ))
            if any(not isinstance(record, MapRecord) for record in records):
                raise ValueError('Map history source returned invalid data.')
            written = self.repository.upsert_records(market, records, self.clock())
            self.repository.mark_incremental(
                market, through_date, cursor_floor, self.clock(), error=''
            )
            return written
        except Exception as exc:
            detail = str(exc).strip()[:700] or type(exc).__name__
            self.repository.mark_incremental(
                market, through_date, cursor, self.clock(), error=detail
            )
            return 0
