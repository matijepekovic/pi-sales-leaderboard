"""Persistence boundary for normalized local job-map history and sync state."""
from __future__ import annotations

import json

from .contract import MapFilters, MapRecord, MapSyncRequest, MapSyncView


FILTER_SNAPSHOT_KEY = 'job_map_filter_snapshot_v1'
FILTER_REFRESH_KEY = 'job_map_filter_refresh_v1'
SYNC_KEY = 'job_map_history_sync_v1'
COVERAGE_KEY = 'job_map_history_coverage_v1'


def _filter_dict(filters):
    return {
        'markets': list(filters.markets),
        'product_types': list(filters.product_types),
        'reps': list(filters.reps),
    }


def _filters_from(value):
    if not isinstance(value, dict):
        return None
    result = {}
    for key in ('markets', 'product_types', 'reps'):
        raw = value.get(key, [])
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            return None
        result[key] = tuple(raw)
    return MapFilters(**result)


def _decode_state(raw):
    try:
        state = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return dict(state) if isinstance(state, dict) else {}


def _sync_view(value):
    value = value if isinstance(value, dict) else {}
    try:
        return MapSyncView(
            status=str(value.get('status') or ''),
            since_date=str(value.get('since_date') or ''),
            through_date=str(value.get('through_date') or ''),
            market=str(value.get('market') or ''),
            chunk_start=str(value.get('chunk_start') or ''),
            chunk_end=str(value.get('chunk_end') or ''),
            completed_chunks=max(0, int(value.get('completed_chunks', 0))),
            total_chunks=max(0, int(value.get('total_chunks', 0))),
            records_written=max(0, int(value.get('records_written', 0))),
            updated=float(value.get('updated', 0) or 0),
            error=str(value.get('error') or ''),
        )
    except (TypeError, ValueError):
        return MapSyncView(error='Map sync state is invalid.')


class JobMapRepository:
    """Own local map records, metadata choices, history coverage, and sync requests."""

    def __init__(self, db):
        self.db = db

    def records(self, *, market=''):
        sql = '''SELECT source_record_id,work_order_id,work_order_number,scheduled_at,
            scheduled_day,created_at,canceled,lead_name,lead_status,latitude,longitude,
            source_record_url,market,product_type,assigned_rep
            FROM job_map_records'''
        args = ()
        market = str(market or '').strip()
        if market:
            sql += ' WHERE lower(market)=lower(?)'
            args = (market,)
        sql += ' ORDER BY scheduled_at ASC,created_at ASC,source_record_id ASC'
        rows = self.db.rows(sql, args)
        result = []
        for row in rows:
            try:
                result.append(MapRecord(
                    source_record_id=str(row['source_record_id']),
                    work_order_id=str(row['work_order_id']),
                    work_order_number=str(row['work_order_number']),
                    scheduled_at=float(row['scheduled_at']),
                    scheduled_day=str(row['scheduled_day']),
                    created_at=float(row['created_at']),
                    canceled=bool(row['canceled']),
                    lead_name=str(row['lead_name'] or ''),
                    lead_status=str(row['lead_status'] or ''),
                    latitude=(None if row['latitude'] is None else float(row['latitude'])),
                    longitude=(None if row['longitude'] is None else float(row['longitude'])),
                    source_record_url=str(row['source_record_url'] or ''),
                    market=str(row['market'] or ''),
                    product_type=str(row['product_type'] or ''),
                    assigned_rep=str(row['assigned_rep'] or ''),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(result)

    @staticmethod
    def _upsert_record(conn, scope_market, record, synced_at):
        if not isinstance(record, MapRecord):
            raise ValueError('Map history source returned invalid records.')
        conn.execute(
            '''INSERT INTO job_map_records(
                source_record_id,work_order_id,work_order_number,scheduled_at,
                scheduled_day,created_at,canceled,lead_name,lead_status,latitude,
                longitude,source_record_url,market,product_type,assigned_rep,
                scope_market,synced_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_record_id) DO UPDATE SET
                work_order_id=excluded.work_order_id,
                work_order_number=excluded.work_order_number,
                scheduled_at=excluded.scheduled_at,
                scheduled_day=excluded.scheduled_day,
                created_at=excluded.created_at,
                canceled=excluded.canceled,
                lead_name=excluded.lead_name,
                lead_status=excluded.lead_status,
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                source_record_url=excluded.source_record_url,
                market=excluded.market,
                product_type=excluded.product_type,
                assigned_rep=excluded.assigned_rep,
                scope_market=excluded.scope_market,
                synced_at=excluded.synced_at''',
            (
                record.source_record_id, record.work_order_id,
                record.work_order_number, float(record.scheduled_at),
                record.scheduled_day, float(record.created_at),
                1 if record.canceled else 0, record.lead_name,
                record.lead_status, record.latitude, record.longitude,
                record.source_record_url, record.market,
                record.product_type, record.assigned_rep,
                scope_market, float(synced_at),
            ),
        )

    def replace_range(self, scope_market, start_day, end_day, records, synced_at):
        """Atomically replace one bounded Salesforce market/date slice."""
        scope_market = str(scope_market or '').strip()
        if not scope_market:
            raise ValueError('A market is required for map history sync.')
        records = tuple(records)
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(
                'DELETE FROM job_map_records WHERE lower(scope_market)=lower(?) '
                'AND scheduled_day>=? AND scheduled_day<=?',
                (scope_market, str(start_day), str(end_day)),
            )
            for record in records:
                self._upsert_record(conn, scope_market, record, synced_at)
        return len(records)

    def upsert_records(self, scope_market, records, synced_at):
        """Apply bounded incremental changes without replacing unaffected history."""
        scope_market = str(scope_market or '').strip()
        if not scope_market:
            raise ValueError('A market is required for map history sync.')
        records = tuple(records)
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for record in records:
                self._upsert_record(conn, scope_market, record, synced_at)
        return len(records)

    def latest_sync_time(self, market=''):
        market = str(market or '').strip()
        if market:
            row = self.db.one(
                'SELECT MAX(synced_at) AS value FROM job_map_records WHERE lower(market)=lower(?)',
                (market,),
            )
        else:
            row = self.db.one('SELECT MAX(synced_at) AS value FROM job_map_records')
        try:
            return float(row['value']) if row and row['value'] is not None else 0.0
        except (KeyError, TypeError, ValueError):
            return 0.0

    def local_filters(self):
        rows = self.db.rows(
            'SELECT market,product_type,assigned_rep FROM job_map_records'
        )
        markets, products, reps = {}, {}, {}
        for row in rows:
            market = str(row.get('market') or '').strip()
            rep = str(row.get('assigned_rep') or '').strip()
            if market:
                markets.setdefault(market.casefold(), market)
            if rep:
                reps.setdefault(rep.casefold(), rep)
            for product in str(row.get('product_type') or '').split(';'):
                product = product.strip()
                if product:
                    products.setdefault(product.casefold(), product)
        return MapFilters(
            markets=tuple(sorted(markets.values(), key=str.casefold)),
            product_types=tuple(sorted(products.values(), key=str.casefold)),
            reps=tuple(sorted(reps.values(), key=str.casefold)),
        )

    def filter_snapshot(self):
        value = self.db.get(FILTER_SNAPSHOT_KEY, {})
        if not isinstance(value, dict):
            return None
        filters = _filters_from(value.get('filters'))
        if filters is None:
            return None
        try:
            captured = float(value.get('captured_at', 0))
        except (TypeError, ValueError):
            return None
        return {'filters': filters, 'captured_at': captured}

    def replace_filter_snapshot(self, filters, captured_at):
        payload = {
            'filters': _filter_dict(filters),
            'captured_at': float(captured_at),
        }
        self.db.set(FILTER_SNAPSHOT_KEY, payload)
        return payload

    def filter_refresh_state(self):
        value = self.db.get(FILTER_REFRESH_KEY, {})
        return dict(value) if isinstance(value, dict) else {}

    def request_filter_refresh(self, ident, now):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute(
                'SELECT value FROM meta WHERE key=?', (FILTER_REFRESH_KEY,)
            ).fetchone()
            state = _decode_state(row['value'] if row else '')
            if state.get('status') in ('queued', 'running'):
                return state
            state = {
                'id': str(ident),
                'status': 'queued',
                'updated': float(now),
                'error': '',
            }
            conn.execute(
                'INSERT INTO meta(key,value) VALUES(?,?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                (FILTER_REFRESH_KEY, json.dumps(state)),
            )
        return state

    def save_filter_refresh_state(self, state):
        value = dict(state)
        self.db.set(FILTER_REFRESH_KEY, value)
        return value

    def request_sync(self, ident, request, now):
        if not isinstance(request, MapSyncRequest):
            raise ValueError('Map sync request is invalid.')
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT value FROM meta WHERE key=?', (SYNC_KEY,)).fetchone()
            state = _decode_state(row['value'] if row else '')
            if state.get('status') in ('queued', 'running'):
                return _sync_view(state)
            state = {
                'id': str(ident),
                'status': 'queued',
                'since_date': request.since_date,
                'through_date': request.through_date,
                'market': request.market,
                'chunk_start': '',
                'chunk_end': '',
                'completed_chunks': 0,
                'total_chunks': 0,
                'records_written': 0,
                'updated': float(now),
                'error': '',
            }
            conn.execute(
                'INSERT INTO meta(key,value) VALUES(?,?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                (SYNC_KEY, json.dumps(state)),
            )
        return _sync_view(state)

    def sync_state(self):
        return _sync_view(self.db.get(SYNC_KEY, {}))

    def save_sync_state(self, view):
        if isinstance(view, MapSyncView):
            value = {
                'status': view.status,
                'since_date': view.since_date,
                'through_date': view.through_date,
                'market': view.market,
                'chunk_start': view.chunk_start,
                'chunk_end': view.chunk_end,
                'completed_chunks': view.completed_chunks,
                'total_chunks': view.total_chunks,
                'records_written': view.records_written,
                'updated': view.updated,
                'error': view.error,
            }
        elif isinstance(view, dict):
            value = dict(view)
        else:
            raise ValueError('Map sync state is invalid.')
        self.db.set(SYNC_KEY, value)
        return _sync_view(value)

    def coverage(self):
        value = self.db.get(COVERAGE_KEY, {})
        return dict(value) if isinstance(value, dict) else {}

    def update_coverage(self, market, since_date, through_date, now, *, cursor_at=0.0):
        market = str(market or '').strip()
        if not market:
            return self.coverage()
        coverage = self.coverage()
        key = market.casefold()
        current = coverage.get(key, {})
        since = str(current.get('since_date') or since_date)
        through = str(current.get('through_date') or through_date)
        if str(since_date) < since:
            since = str(since_date)
        if str(through_date) > through:
            through = str(through_date)
        existing_cursor = float(current.get('cursor_at', 0) or 0)
        coverage[key] = {
            'market': market,
            'since_date': since,
            'through_date': through,
            'updated': float(now),
            'cursor_at': existing_cursor or float(cursor_at or now),
            'last_incremental_attempt': float(
                current.get('last_incremental_attempt', 0) or 0
            ),
            'incremental_error': str(current.get('incremental_error') or ''),
        }
        self.db.set(COVERAGE_KEY, coverage)
        return coverage

    def next_incremental(self, now, *, interval_seconds=3600):
        candidates = []
        for key, value in self.coverage().items():
            if not isinstance(value, dict):
                continue
            try:
                cursor = float(value.get('cursor_at', 0) or 0)
                attempted = float(value.get('last_incremental_attempt', 0) or 0)
            except (TypeError, ValueError):
                continue
            market = str(value.get('market') or '').strip()
            since = str(value.get('since_date') or '')
            if market and since and cursor > 0 and float(now) - attempted >= interval_seconds:
                candidates.append((attempted, key, dict(value)))
        return min(candidates, default=(None, None, None))[2]

    def mark_incremental(self, market, through_date, cursor_at, now, *, error=''):
        coverage = self.coverage()
        key = str(market or '').strip().casefold()
        current = dict(coverage.get(key, {}))
        if not current:
            return coverage
        if not error:
            current['through_date'] = max(
                str(current.get('through_date') or ''), str(through_date)
            )
            current['cursor_at'] = float(cursor_at)
            current['updated'] = float(now)
        current['last_incremental_attempt'] = float(now)
        current['incremental_error'] = str(error or '')
        coverage[key] = current
        self.db.set(COVERAGE_KEY, coverage)
        return coverage
