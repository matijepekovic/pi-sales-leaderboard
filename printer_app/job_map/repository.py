"""Persistence boundary for local normalized job-map snapshots."""
from __future__ import annotations

from dataclasses import asdict
import json

from .contract import MapFilters, MapJob, MapQuery, MapSourceDiagnostics


SNAPSHOT_KEY = 'job_map_snapshot_v3'
REFRESH_KEY = 'job_map_refresh_v3'
FILTER_SNAPSHOT_KEY = 'job_map_filter_snapshot_v1'
FILTER_REFRESH_KEY = 'job_map_filter_refresh_v1'


def _query_dict(query):
    return {
        'market': str(query.market or ''),
        'product_type': str(query.product_type or ''),
        'rep': str(query.rep or ''),
    }


def _query_from(value):
    if not isinstance(value, dict):
        return None
    try:
        return MapQuery(
            market=str(value.get('market') or ''),
            product_type=str(value.get('product_type') or ''),
            rep=str(value.get('rep') or ''),
        )
    except (TypeError, ValueError):
        return None


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


def _decode_state(raw, *, query=False):
    try:
        state = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    if not isinstance(state, dict):
        return {}
    result = dict(state)
    if query:
        parsed = _query_from(result.get('query'))
        if parsed is not None:
            result['query'] = parsed
    return result


class JobMapRepository:
    """Own durable map/filter refresh state and complete normalized snapshots."""

    def __init__(self, db):
        self.db = db

    def snapshot(self):
        value = self.db.get(SNAPSHOT_KEY, {})
        if not isinstance(value, dict):
            return None
        query = _query_from(value.get('query'))
        raw_jobs = value.get('jobs')
        if query is None or not isinstance(raw_jobs, list):
            return None
        jobs = []
        try:
            for raw in raw_jobs:
                if not isinstance(raw, dict):
                    return None
                jobs.append(MapJob(
                    source_id=str(raw.get('source_id') or ''),
                    work_order_number=str(raw.get('work_order_number') or ''),
                    lead_name=str(raw.get('lead_name') or ''),
                    lead_status=str(raw.get('lead_status') or ''),
                    latitude=float(raw['latitude']),
                    longitude=float(raw['longitude']),
                    source_record_url=str(raw.get('source_record_url') or ''),
                    market=str(raw.get('market') or ''),
                    product_type=str(raw.get('product_type') or ''),
                    assigned_reps=tuple(
                        str(name) for name in raw.get('assigned_reps', ())
                        if isinstance(name, str)
                    ),
                ))
            captured = float(value.get('captured_at', 0))
            raw_diagnostics = value.get('diagnostics', {})
            if not isinstance(raw_diagnostics, dict):
                raw_diagnostics = {}
            diagnostics = MapSourceDiagnostics(
                appointment_rows=max(0, int(raw_diagnostics.get('appointment_rows', 0))),
                grouped_jobs=max(0, int(raw_diagnostics.get('grouped_jobs', 0))),
                jobs_with_location=max(0, int(raw_diagnostics.get('jobs_with_location', 0))),
                jobs_missing_location=max(0, int(raw_diagnostics.get('jobs_missing_location', 0))),
            )
        except (KeyError, TypeError, ValueError):
            return None
        return {
            'query': query,
            'jobs': tuple(jobs),
            'captured_at': captured,
            'diagnostics': diagnostics,
        }

    def replace_snapshot(self, query, jobs, captured_at, diagnostics=None):
        diagnostics = diagnostics if isinstance(diagnostics, MapSourceDiagnostics) else MapSourceDiagnostics()
        payload = {
            'query': _query_dict(query),
            'captured_at': float(captured_at),
            'diagnostics': asdict(diagnostics),
            'jobs': [
                dict(asdict(job), assigned_reps=list(job.assigned_reps))
                for job in jobs
            ],
        }
        self.db.set(SNAPSHOT_KEY, payload)
        return payload

    def refresh_state(self):
        value = self.db.get(REFRESH_KEY, {})
        result = dict(value) if isinstance(value, dict) else {}
        query = _query_from(result.get('query'))
        if query is not None:
            result['query'] = query
        return result

    def request_refresh(self, ident, query, now):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT value FROM meta WHERE key=?', (REFRESH_KEY,)).fetchone()
            state = _decode_state(row['value'] if row else '', query=True)
            if state.get('status') in ('queued', 'running'):
                return state
            state = {
                'id': str(ident),
                'status': 'queued',
                'query': _query_dict(query),
                'updated': float(now),
                'error': '',
            }
            conn.execute(
                'INSERT INTO meta(key,value) VALUES(?,?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                (REFRESH_KEY, json.dumps(state)),
            )
        return dict(state, query=query)

    def save_refresh_state(self, state):
        value = dict(state)
        query = value.get('query')
        if isinstance(query, MapQuery):
            value['query'] = _query_dict(query)
        self.db.set(REFRESH_KEY, value)
        result = dict(state)
        if isinstance(query, MapQuery):
            result['query'] = query
        return result

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
            row = conn.execute('SELECT value FROM meta WHERE key=?', (FILTER_REFRESH_KEY,)).fetchone()
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
