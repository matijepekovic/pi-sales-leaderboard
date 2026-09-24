"""HTTP boundary for the isolated Salesforce Sandbox MOD portal."""
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo
import json

from flask import Blueprint, g, jsonify, render_template, request, send_file

from ..mod_sheets.pdf_renderer import render_mod_pdf


def _bool_arg(name, default=False):
    value = request.args.get(name)
    if value is None:
        return default
    return str(value).casefold() in ('1', 'true', 'on', 'yes')


def _record_filters():
    """HTTP-to-MOD filter mapping for PDF generation; rep names do not use status flags."""
    return dict(
        start_date=request.args.get('startdate', ''),
        end_date=request.args.get('enddate', ''),
        market_segment=request.args.get('marketsegment', ''),
        product_category=request.args.get('productCategory', ''),
        source_type=request.args.get('sourceType', ''),
        remove_canceled=_bool_arg('removeCanceled', False),
        remove_unconfirmed=_bool_arg('removeUnconfirmed', False),
    )


def blueprint(service):
    bp = Blueprint('salesforce_sandbox', __name__)

    @bp.get('/salesforce-sandbox')
    def page():
        return render_template('salesforce_sandbox.html', snapshot=service.portal())

    @bp.get('/salesforce-sandbox/explorer')
    def explorer_page():
        # Rendering the shell must never connect or query Salesforce.
        return render_template('salesforce_explorer.html')

    def exploration(action, **parameters):
        snapshot = service.explore(action, **parameters)
        if snapshot.error:
            return jsonify(ok=False, error=snapshot.error), 400 if snapshot.invalid else 503
        return jsonify(ok=True, **snapshot.data)

    @bp.get('/salesforce-sandbox/api/explorer/objects')
    def explorer_objects():
        return exploration('objects')

    @bp.get('/salesforce-sandbox/api/explorer/objects/<name>')
    def explorer_object(name):
        return exploration('object', name=name)

    @bp.post('/salesforce-sandbox/api/explorer/objects/<name>/search')
    def explorer_search(name):
        # POST keeps typed filter values out of URLs and inherits admin/CSRF
        # protection. This endpoint only reads records from the source.
        try:
            columns_text = request.form.get('columns', '[]')
            filters_text = request.form.get('filters', '[]')
            if len(columns_text) > 4096 or len(filters_text) > 20000:
                raise ValueError('Search filters are too large.')
            columns, filters = json.loads(columns_text), json.loads(filters_text)
            if not isinstance(columns, list) or not isinstance(filters, list):
                raise ValueError('Columns and filters must be lists.')
        except (ValueError, TypeError):
            return jsonify(ok=False, error='Use the field and filter controls to build a search.'), 400
        return exploration('search', name=name, columns=columns, filters=filters,
                           match=request.form.get('match', 'all'), after=request.form.get('after', ''))

    @bp.get('/salesforce-sandbox/api/explorer/objects/<name>/records/<record_id>')
    def explorer_record(name, record_id):
        return exploration('record', name=name, record_id=record_id)

    @bp.get('/salesforce-sandbox/api/explorer/objects/<name>/records/<record_id>/related/<relationship>')
    def explorer_related(name, record_id, relationship):
        return exploration('related', name=name, record_id=record_id,
                           relationship=relationship, after=request.args.get('after', ''))

    @bp.get('/salesforce-sandbox/api/connection')
    def connection():
        snapshot = service.connection()
        if snapshot.error:
            return jsonify(
                ok=False,
                error=snapshot.error,
                trace=list(snapshot.trace),
            ), 503
        return jsonify(
            ok=True,
            username=snapshot.status.username,
            alias=snapshot.status.alias,
            instance_url=snapshot.status.instance_url,
            trace=list(snapshot.trace),
        )

    def field_response(snapshot):
        if snapshot.error:
            return jsonify(ok=False, error=snapshot.error, trace=list(snapshot.trace)), 503
        response = jsonify(
            ok=True, key=snapshot.key, saved=snapshot.saved,
            field={'label': snapshot.field.label, 'path': snapshot.field.path,
                   'values': list(snapshot.field.values), 'totals': snapshot.totals},
            trace=list(snapshot.trace),
        )
        response.headers['Cache-Control'] = 'no-store'
        return response

    @bp.get('/salesforce-sandbox/api/field/<key>')
    def field(key):
        # Filter changes/page loads may read saved names, never refresh them.
        return field_response(service.field(key))

    @bp.post('/salesforce-sandbox/api/reps/refresh')
    def refresh_reps():
        # Explicit persisted write, protected by the app's existing admin/CSRF guard.
        filters = {key: request.form.get(param, '') for key, param in (
            ('start_date', 'startdate'), ('end_date', 'enddate'),
            ('market_segment', 'marketsegment'), ('product_category', 'productCategory'),
            ('source_type', 'sourceType'),
        )}
        if request.form.get('dateScope') == 'today':
            today = datetime.now(ZoneInfo(g.printer_config.timezone)).date().isoformat()
            filters.update(start_date=today, end_date=today)
        return field_response(service.refresh_reps(**filters))

    @bp.get('/salesforce-sandbox/mod-sheet')
    def mod_sheet():
        snapshot = service.generate(
            **_record_filters(),
            assigned_service_resource=request.args.get('assignedServiceResource', ''),
            color_code=_bool_arg('colorCode', False),
            limit=1000,
        )
        if snapshot.error:
            return render_template('salesforce_sandbox_error.html', message=snapshot.error), 400
        pdf = BytesIO(render_mod_pdf(snapshot.records, color_code=snapshot.color_code))
        return send_file(
            pdf,
            mimetype='application/pdf',
            as_attachment=False,
            download_name='MOD-Sheet.pdf',
        )

    return bp
