"""HTTP boundary for the job map."""
from __future__ import annotations

from io import BytesIO

import math

from flask import Blueprint, abort, jsonify, render_template, request, send_file

from .contract import JobMapSourceError
from .service import MAX_RADIUS_MILES


def blueprint(service):
    bp = Blueprint('job_map', __name__, url_prefix='/map')

    @bp.get('')
    @bp.get('/')
    def page():
        return render_template('job_map.html')

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
            records = service.jobs(latitude, longitude)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        except JobMapSourceError as exc:
            return jsonify(ok=False, error=str(exc)), 503
        return jsonify(ok=True, radius_miles=MAX_RADIUS_MILES, jobs=[{
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
        } for item in records])

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
