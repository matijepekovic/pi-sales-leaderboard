"""HTTP-only boundary for the independent digital MOD sheet sandbox."""
from __future__ import annotations

import json

from flask import Blueprint, abort, jsonify, render_template, request, send_file

from ..mod_sheets.pdf_renderer import MOD_ROW_HEIGHTS, MOD_TABLE_WIDTH
from .contract import RESULT_DETAILS


def blueprint(service):
    bp = Blueprint('mod_resulting', __name__, url_prefix='/mod-resulting')

    @bp.get('')
    def page():
        day = service.day()
        notice = ''
        try:
            data = service.snapshot(day)
        except Exception as exc:
            data = {'day': day, 'state': service.repository.day(day),
                    'sheets': service.repository.sheets(day)}
            notice = str(exc)[:250]
        try:
            users = service.users()
        except Exception as exc:
            users = []
            notice = notice or 'Salesforce MOD list unavailable: ' + str(exc)[:180]
        try:
            choices = service.dropdowns()
        except Exception:
            # Training reference options permit safe offline draft review;
            # the Salesforce writer independently validates live picklists.
            choices = {
                'result_details':[{'value':value,'label':value}
                                  for value in RESULT_DETAILS],
                'dnr_reasons':[{'value':value,'label':value}
                               for value in ('Roofing','Bath','Siding','Windows',
                                             'Behavior','Finance')],
            }
            notice = notice or 'Salesforce picklists unavailable; draft choices are unverified.'
        return render_template(
            'mod_resulting.html',
            data=data, users=users,
            result_details=choices['result_details'],
            dnr_reasons=choices['dnr_reasons'],
            row_heights=MOD_ROW_HEIGHTS, sheet_width=MOD_TABLE_WIDTH,
            notice=notice,
        )

    @bp.get('/pdf')
    def pdf():
        day = service.day()
        state = service.repository.day(day)
        target = (service.output_directory / (day + '-completed.pdf')
                  if service.output_directory else None)
        if not state or not state['submitted_at'] or target is None or not target.is_file():
            abort(404)
        return send_file(target, mimetype='application/pdf', as_attachment=True,
                         download_name='MOD-Sheets-' + day + '.pdf')

    @bp.post('/api/refresh')
    def refresh():
        try:
            count = service.refresh(service.day())
        except Exception as exc:
            return jsonify(ok=False, error=str(exc)[:400]), 422
        return jsonify(ok=True, count=count)

    @bp.post('/api/mod')
    def choose_mod():
        try:
            name = service.set_mod(service.day(), request.form.get('mod_user_id', ''))
        except (ValueError, LookupError) as exc:
            return jsonify(ok=False, error=str(exc)), 400
        except Exception as exc:
            return jsonify(ok=False, error=str(exc)[:300]), 422
        return jsonify(ok=True, mod=name)

    @bp.post('/api/save')
    def save():
        try:
            raw = request.form.get('draft', '')
            if len(raw) > 14000:
                raise ValueError('MOD draft is too large.')
            revision = int(request.form.get('revision', '-1'))
            data = json.loads(raw)
            ident = request.form.get('work_order_id', '')
            result = service.save(service.day(), ident, data, revision)
        except (ValueError, TypeError, LookupError, json.JSONDecodeError) as exc:
            return jsonify(ok=False, error=str(exc)), 409
        return jsonify(ok=True, revision=result)

    @bp.post('/api/submit')
    def submit():
        try:
            result = service.submit(service.day())
        except (ValueError, LookupError) as exc:
            return jsonify(ok=False, error=str(exc)), 422
        except Exception as exc:
            # No partial-success claim on remote errors. Stored receipts survive retries.
            return jsonify(ok=False, error=str(exc)[:500]), 502
        return jsonify(ok=True, **result)

    return bp
