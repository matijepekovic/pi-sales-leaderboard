"""HTTP-only boundary for the independent digital MOD sheet sandbox."""
from __future__ import annotations

import json

from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request, send_file

from .surface import SheetSurfaceError, overlay_css


def blueprint(service, surface):
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
            if not users:
                market = service.repository.imported_market(day)
                notice = notice or (
                    'No active Sales Managers found in the imported '
                    + (market or 'unknown') + ' market.'
                )
        except Exception as exc:
            users = []
            notice = notice or 'Salesforce MOD list unavailable: ' + str(exc)[:180]
        try:
            choices = service.dropdowns()
        except Exception:
            # No made-up Salesforce dropdown options. The saved sheet and
            # other local controls remain available when metadata is offline.
            choices = {'result_details':[], 'dnr_reasons':[], 'products':[]}
            current_app.logger.warning('MOD resulting Salesforce picklists unavailable.')
        # Existing draft selections are grounded values, not guessed picklist
        # options. Keep them visible and lossless through offline Refresh.
        # The Salesforce writer independently validates every option before
        # any write is permitted.
        for sheet in data['sheets']:
            draft = sheet['draft']
            for value in str(draft.get('dnr_reason') or '').split(';'):
                value = value.strip()
                if value and not any(o['value'] == value for o in choices['dnr_reasons']):
                    choices['dnr_reasons'].append({'value': value, 'label': value})
            details = [draft.get('result_detail', '')]
            details.extend(
                str(item.get('detail') or '')
                for item in draft.get('product_results', {}).values()
                if isinstance(item, dict)
            )
            for value in details:
                if value and not any(o['value'] == value for o in choices['result_details']):
                    choices['result_details'].append({'value': value, 'label': value})
            for value in draft.get('sale_products', {}):
                if value and not any(o['value'] == value for o in choices['products']):
                    choices['products'].append({'value': value, 'label': value})
        return render_template(
            'mod_resulting.html',
            data=data, users=users,
            result_details=choices['result_details'],
            dnr_reasons=choices['dnr_reasons'],
            products=choices.get('products', []),
            live_writes_enabled=service.allow_salesforce_writes,
            notice=notice,
        )

    @bp.get('/surface.css')
    def surface_styles():
        return Response(overlay_css(), mimetype='text/css')

    @bp.get('/sheet/<day>/<work_order_id>.png')
    def sheet_image(day, work_order_id):
        try:
            record = service.sheet_record(day, work_order_id)
        except (LookupError, ValueError):
            abort(404)
        try:
            payload = surface.image(record)
        except SheetSurfaceError as exc:
            return Response(str(exc), status=503, mimetype='text/plain')
        return Response(payload, mimetype='image/png')

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

    @bp.post('/api/clear')
    def clear_local():
        try:
            count = service.clear_local(service.day())
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

    @bp.post('/api/override')
    def override():
        try:
            revision = service.override(
                service.day(), request.form.get('work_order_id', ''),
                int(request.form.get('revision', '-1'))
            )
        except (ValueError, TypeError, LookupError) as exc:
            return jsonify(ok=False, error=str(exc)), 409
        return jsonify(ok=True, revision=revision)

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
            mode = request.form.get('mode', '')
            if mode == 'all':
                if request.form.get('work_order_ids'):
                    raise ValueError('Submit All cannot include selected Work Orders.')
                selected = None
            elif mode == 'selected':
                raw = request.form.get('work_order_ids', '')
                if len(raw) > 75000:
                    raise ValueError('Too many selected Work Orders.')
                selected = json.loads(raw)
                if not isinstance(selected, list):
                    raise ValueError('Choose a list of Work Orders.')
            else:
                raise ValueError('Choose Submit All or Submit Selected.')
            result = service.submit(service.day(), selected)
        except (ValueError, TypeError, LookupError, json.JSONDecodeError) as exc:
            return jsonify(ok=False, error=str(exc)), 422
        except Exception as exc:
            # No partial-success claim on remote errors. Stored receipts survive retries.
            return jsonify(ok=False, error=str(exc)[:500]), 502
        return jsonify(ok=True, **result)

    return bp
