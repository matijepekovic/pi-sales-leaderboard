"""Persistence boundary for local normalized job-map snapshots."""
from __future__ import annotations

from dataclasses import asdict
import json

from .contract import MapJob, MapQuery


SNAPSHOT_KEY = 'job_map_snapshot_v1'
REFRESH_KEY = 'job_map_refresh_v1'


def _query_dict(query):
    return {
        'latitude': float(query.latitude),
        'longitude': float(query.longitude),
        'radius_miles': float(query.radius_miles),
    }


def _query_from(value):
    if not isinstance(value, dict):
        return None
    try:
        return MapQuery(
            latitude=float(value['latitude']),
            longitude=float(value['longitude']),
            radius_miles=float(value['radius_miles']),
        )
    except (KeyError, TypeError, ValueError):
        return None


class JobMapRepository:
    """Own durable map refresh state and the last complete normalized snapshot."""

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
        except (KeyError, TypeError, ValueError):
            return None
        return {'query': query, 'jobs': tuple(jobs), 'captured_at': captured}

    def replace_snapshot(self, query, jobs, captured_at):
        payload = {
            'query': _query_dict(query),
            'captured_at': float(captured_at),
            'jobs': [
                dict(asdict(job), assigned_reps=list(job.assigned_reps))
                for job in jobs
            ],
        }
        self.db.set(SNAPSHOT_KEY, payload)
        return payload

    def refresh_state(self):
        value = self.db.get(REFRESH_KEY, {})
        if not isinstance(value, dict):
            return {}
        result = dict(value)
        query = _query_from(result.get('query'))
        if query is not None:
            result['query'] = query
        return result

    def request_refresh(self, ident, query, now):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT value FROM meta WHERE key=?', (REFRESH_KEY,)).fetchone()
            try:
                state = json.loads(row['value']) if row else {}
            except (TypeError, ValueError):
                state = {}
            if isinstance(state, dict) and state.get('status') in ('queued', 'running'):
                result = dict(state)
                saved_query = _query_from(result.get('query'))
                if saved_query is not None:
                    result['query'] = saved_query
                return result
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
