"""HTTP boundary for the job map."""
from __future__ import annotations

from io import BytesIO

from flask import Blueprint, abort, jsonify, make_response, render_template, request, send_file

from .contract import JobMapSourceError


def blueprint(service):
    bp = Blueprint('job_map', __name__, url_prefix='/map')

    @bp.get('')
    @bp.get('/')
    def page():
        response = make_response(render_template('job_map.html'))
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self' https://unpkg.com; "
            "style-src 'self' https://unpkg.com; "
            "img-src 'self' data: blob: https://unpkg.com https://tiles.openfreemap.org; "
            "connect-src 'self' https://tiles.openfreemap.org; worker-src 'self' blob:; "
            "frame-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'self'; form-action 'self'"
        )
        return response

    @bp.get('/api/jobs')
    def jobs():
        try:
            records = service.jobs()
        except JobMapSourceError as exc:
            return jsonify(ok=False, error=str(exc)), 503
        return jsonify(ok=True, jobs=[{
            'source_id': item.source_id,
            'work_order_number': item.work_order_number,
            'lead_name': item.lead_name,
            'lead_status': item.lead_status,
            'latitude': item.latitude,
            'longitude': item.longitude,
            'source_record_url': item.source_record_url,
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
