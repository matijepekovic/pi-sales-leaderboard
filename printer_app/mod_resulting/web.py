"""HTTP-only boundary for the independent digital MOD sheet sandbox."""
from __future__ import annotations

import json

from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request, send_file, url_for

from .surface import SheetSurfaceError, overlay_css
from .cover_report import has_result


def blueprint(service, surface, *, color_code=None, pdfs=None):
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
        try:
            checkbox_specs = service.checkbox_fields()
        except Exception:
            # The saved raw value remains inspectable when live field metadata
            # is temporarily unavailable; edits fail closed rather than guess.
            checkbox_specs = {}
            current_app.logger.warning('MOD checkbox field metadata unavailable.')
        return render_template(
            'mod_resulting.html',
            data=data, users=users,
            result_details=choices['result_details'],
            dnr_reasons=choices['dnr_reasons'],
            products=choices.get('products', []),
            live_writes_enabled=service.allow_salesforce_writes,
            color_code=bool(color_code()) if color_code else False,
            checkbox_specs=checkbox_specs,
            pdfs_remaining=sum(not has_result(sheet["draft"]) for sheet in data["sheets"]),
            pdfs_available=bool(data["sheets"]) and pdfs is not None,
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
            payload = (surface.image(record, color_code=bool(color_code()))
                       if color_code else surface.image(record))
        except SheetSurfaceError as exc:
            return Response(str(exc), status=503, mimetype='text/plain')
        return Response(payload, mimetype='image/png')

    @bp.post('/api/pdfs/start')
    def pdfs_start():
        if pdfs is None:
            abort(503)
        try:
            result = pdfs.begin(service.day())
        except (ValueError, LookupError) as exc:
            return jsonify(ok=False, error=str(exc)), 422
        job_id = result["job_id"]
        return jsonify(ok=True, **result,
                       editor_url=url_for('mod_resulting.pdfs_cover', job_id=job_id),
                       calc_editor_url=url_for('mod_resulting.pdfs_calc', job_id=job_id),
                       status_url=url_for('mod_resulting.pdfs_status', job_id=job_id)), 202

    @bp.get('/pdfs/cover/<int:job_id>')
    def pdfs_cover(job_id):
        if pdfs is None:
            abort(404)
        try:
            data = pdfs.editor(service.day(), job_id)
        except LookupError:
            abort(404)
        return render_template('mod_cover_editor.html', data=data)

    @bp.get('/pdfs/calc/<int:job_id>')
    def pdfs_calc(job_id):
        if pdfs is None:
            abort(404)
        try:
            data = pdfs.calc_editor(service.day(), job_id)
        except LookupError:
            abort(404)
        return render_template('mod_calc_editor.html', data=data)

    @bp.post('/api/pdfs/calc/confirm')
    def pdfs_calc_confirm():
        if pdfs is None:
            abort(503)
        try:
            job_id = int(request.form.get('job_id', ''))
            revision = int(request.form.get('revision', ''))
            raw = request.form.get('edits', '')
            if len(raw) > 10000:
                raise ValueError('OLY Calc edit is too large.')
            edits = json.loads(raw)
            next_revision = pdfs.confirm_calc(service.day(), job_id, edits, revision)
        except (ValueError, TypeError, LookupError, json.JSONDecodeError) as exc:
            return jsonify(ok=False, error=str(exc)), 409
        return jsonify(ok=True, revision=next_revision)

    @bp.get('/api/pdfs/calc/status')
    def pdfs_calc_status():
        if pdfs is None:
            abort(404)
        job_id = request.args.get('job_id', type=int)
        if job_id is None:
            return jsonify(ok=False, error='PDF job ID required.'), 400
        try:
            status = pdfs.calc_status(service.day(), job_id)
        except LookupError:
            abort(404)
        return jsonify(ok=True, **status,
                       download_url=(url_for('mod_resulting.pdfs_download_calc', job_id=job_id)
                                     if status['ready'] else None))

    @bp.get('/pdfs/calc/download/<int:job_id>')
    def pdfs_download_calc(job_id):
        if pdfs is None:
            abort(404)
        try:
            path = pdfs.calc_pdf_path(service.day(), job_id)
        except LookupError:
            abort(404)
        except ValueError as exc:
            return Response(str(exc), status=409, mimetype='text/plain')
        response = send_file(path, mimetype='application/pdf', as_attachment=False,
                             download_name='OLY-Calc-' + service.day() + '.pdf')
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
        return response

    @bp.post('/api/pdfs/confirm')
    def pdfs_confirm():
        if pdfs is None:
            abort(503)
        try:
            job_id = int(request.form.get('job_id', ''))
            revision = int(request.form.get('revision', ''))
            raw = request.form.get('edits', '')
            if len(raw) > 180000:
                raise ValueError('Cover edit is too large.')
            edits = json.loads(raw)
            next_revision = pdfs.confirm(service.day(), job_id, edits, revision)
        except (ValueError, TypeError, LookupError, json.JSONDecodeError) as exc:
            return jsonify(ok=False, error=str(exc)), 409
        return jsonify(ok=True, revision=next_revision)

    @bp.get('/api/pdfs/status')
    def pdfs_status():
        if pdfs is None:
            abort(404)
        job_id = request.args.get('job_id', type=int)
        if job_id is None:
            return jsonify(ok=False, error='PDF job ID required.'), 400
        try:
            status = pdfs.status(service.day(), job_id)
        except LookupError:
            abort(404)
        return jsonify(ok=True, **status,
                       download_url=(url_for('mod_resulting.pdfs_download', job_id=job_id)
                                     if status['ready'] else None))

    @bp.get('/pdfs/redlines/<int:job_id>')
    def pdfs_download(job_id):
        if pdfs is None:
            abort(404)
        try:
            path = pdfs.pdf_path(service.day(), job_id)
        except LookupError:
            abort(404)
        except ValueError as exc:
            return Response(str(exc), status=409, mimetype='text/plain')
        response = send_file(path, mimetype='application/pdf', as_attachment=False,
                             download_name='OLY-Redlines-' + service.day() + '.pdf')
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
        return response

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
            revision = int(request.form.get('revision', '-1'))
            data = json.loads(raw)
            ident = request.form.get('work_order_id', '')
            result = service.save(service.day(), ident, data, revision)
        except (ValueError, TypeError, LookupError, json.JSONDecodeError) as exc:
            return jsonify(ok=False, error=str(exc)), 409
        return jsonify(ok=True, revision=result)

    @bp.get('/api/submission-status')
    def submission_status():
        job_id = request.args.get('job_id', type=int)
        day = service.day()
        return jsonify(
            ok=True,
            submission=service.repository.latest_submission(day, job_id=job_id),
            notifications=service.repository.recent_submission_items(day),
        )

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
            result = service.enqueue(service.day(), selected)
        except (ValueError, TypeError, LookupError, json.JSONDecodeError) as exc:
            return jsonify(ok=False, error=str(exc)), 422
        except Exception as exc:
            # No partial-success claim on remote errors. Stored receipts survive retries.
            return jsonify(ok=False, error=str(exc)[:500]), 502
        return jsonify(ok=True, **result), 202

    return bp
