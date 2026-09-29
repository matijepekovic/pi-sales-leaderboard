"""HTTP boundary for the job map."""
from __future__ import annotations

from io import BytesIO
from urllib.parse import urlsplit

import math

from flask import Blueprint, abort, jsonify, redirect, render_template, request, send_file

from .contract import JobMapSourceError
from .service import MAX_RADIUS_MILES


def _secure_page_url(https_access):
    """Return the approved HTTPS map URL when the local secure proxy is ready."""
    if https_access is None or request.is_secure:
        return ''
    state = https_access.status()
    if not state.get('configured'):
        return ''
    hostname = urlsplit('//' + request.host).hostname or ''
    candidates = [
        str(value).strip()
        for value in (*state.get('addresses', ()), *state.get('dns', ()))
        if str(value).strip()
    ]
    target = hostname if hostname in candidates else (candidates[0] if candidates else '')
    if not target:
        return ''
    if ':' in target and not target.startswith('['):
        target = '[' + target + ']'
    return 'https://' + target + request.path


def blueprint(service, *, https_access=None):
    bp = Blueprint('job_map', __name__, url_prefix='/map')

    @bp.get('')
    @bp.get('/')
    def page():
        secure_url = _secure_page_url(https_access)
        if secure_url:
            return redirect(secure_url, code=302)
        return render_template('job_map.html', max_radius_miles=MAX_RADIUS_MILES)

    @bp.get('/api/filters')
    def filters():
        view = service.filters(force_refresh=request.args.get('refresh') == '1')
        return jsonify(
            ok=True,
            refreshing=view.refreshing,
            captured_at=view.captured_at,
            error=view.error,
            filters={
                'markets': list(view.filters.markets),
                'product_types': list(view.filters.product_types),
                'reps': list(view.filters.reps),
            },
        )

    @bp.get('/api/jobs')
    def jobs():
        try:
            latitude = float(request.args.get('lat', ''))
            longitude = float(request.args.get('lon', ''))
            if not math.isfinite(latitude) or not math.isfinite(longitude):
                raise ValueError
        except (TypeError, ValueError):
            return jsonify(ok=False, error='Current location is required.'), 400
        try:
            view = service.view(
                latitude,
                longitude,
                market=request.args.get('market', ''),
                product_type=request.args.get('product', ''),
                rep=request.args.get('rep', ''),
                force_refresh=request.args.get('refresh') == '1',
            )
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(
            ok=True,
            radius_miles=MAX_RADIUS_MILES,
            refreshing=view.refreshing,
            stale=view.stale,
            captured_at=view.captured_at,
            error=view.error,
            jobs=[{
                'source_id': item.source_id,
                'work_order_number': item.work_order_number,
                'lead_name': item.lead_name,
                'lead_status': item.lead_status,
                'latitude': item.latitude,
                'longitude': item.longitude,
                'source_record_url': item.source_record_url,
                'market': item.market,
                'product_type': item.product_type,
                'assigned_reps': list(item.assigned_reps),
            } for item in view.jobs],
            diagnostics={
                'appointment_rows': view.diagnostics.appointment_rows,
                'grouped_jobs': view.diagnostics.grouped_jobs,
                'jobs_with_location': view.diagnostics.jobs_with_location,
                'jobs_missing_location': view.diagnostics.jobs_missing_location,
                'snapshot_jobs': view.diagnostics.snapshot_jobs,
                'excluded_status': view.diagnostics.excluded_status,
                'outside_radius': view.diagnostics.outside_radius,
                'visible_jobs': view.diagnostics.visible_jobs,
                'candidates': [{
                    'work_order_number': item.work_order_number,
                    'lead_name': item.lead_name,
                    'lead_status': item.lead_status,
                    'distance_miles': round(item.distance_miles, 3),
                    'latitude': item.latitude,
                    'longitude': item.longitude,
                    'outcome': item.outcome,
                } for item in view.diagnostics.candidates],
            },
        )

    @bp.get('/mod-sheet')
    def mod_sheet():
        try:
            payload = service.mod_sheet(request.args.get('work_order', ''))
        except ValueError as exc:
            abort(400, str(exc))
        except LookupError as exc:
            abort(404, str(exc))
        except JobMapSourceError as exc:
            abort(503, str(exc))
        return send_file(
            BytesIO(payload),
            mimetype='application/pdf',
            as_attachment=False,
            download_name='MOD-Sheet.pdf',
        )

    return bp
