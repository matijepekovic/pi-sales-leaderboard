"""HTTP interface for independently scheduled Salesforce printing jobs."""
import json
import uuid

from flask import Blueprint, g, jsonify, make_response, redirect, render_template, request, url_for

from .print_options import PrintOptions, CHOICES, NUMBERS
from .report_notes_contract import ReportNotesError, ReportNotesOptions
from .report_printing_contract import ReportPrintingJob, ScheduledReport


def blueprint(repository, source):
    bp = Blueprint('report_printing', __name__, url_prefix='/report-printing')

    @bp.get('/')
    def page():
        jobs = repository.list()
        selected = next((j for j in jobs if j.job_id == request.args.get('edit')), None)
        return render_template('report_printing.html', jobs=jobs, selected=selected,
                               choices=CHOICES, numbers=NUMBERS, runs=repository.runs())

    @bp.get('/folders')
    def folders():
        """Search folder names before opening any folder."""
        term = request.args.get('q', '').strip()
        if len(term) > 100:
            return jsonify(error='Invalid folder search'), 400
        try:
            reports = source.search_reports('')
            names = sorted({r['folder'] or 'Unfiled' for r in reports}, key=str.casefold)
            matched = [name for name in names if term.casefold() in name.casefold()]
            return jsonify(folders=matched, total=len(matched))
        except Exception:
            return jsonify(error='Folder search unavailable'), 503

    @bp.get('/search')
    def search():
        """Search report names only inside an explicitly selected folder."""
        term = request.args.get('q', '').strip()
        folder = request.args.get('folder', '').strip()
        if len(term) > 100 or len(folder) > 200 or not folder:
            return jsonify(error='Choose a folder first'), 400
        try:
            fresh_reports = source.refresh_report_folder(folder)
            matched = [r for r in fresh_reports if (r['folder'] or 'Unfiled') == folder
                       and term.casefold() in r['name'].casefold()]
            return jsonify(reports=matched, total=len(matched))
        except Exception:
            return jsonify(error='Report search unavailable'), 503

    @bp.post('/preview')
    def preview():
        # The application's normal admin, origin, duplicate-field, and CSRF
        # protections apply. Downloads/conversion belong to the service, not HTTP.
        from .report_printing_service import preview_report
        try:
            report_id = request.form['report_id']
            if not report_id.isalnum() or not 1 <= len(report_id) <= 100:
                raise ValueError('Invalid report ID.')
            kind = request.form.get('kind', 'pdf')
            if kind not in ('columns', 'pdf'):
                raise ValueError('Invalid preview request.')
            raw_options = json.loads(request.form.get('options', '{}'))
            if not isinstance(raw_options, dict):
                raise ValueError('Invalid print settings.')
            options = PrintOptions().apply(raw_options)
            notes = None if kind == 'columns' else ReportNotesOptions.from_dict(
                json.loads(request.form.get('notes', '{}')))
        except (ValueError, KeyError, TypeError):
            return jsonify(error='Invalid preview settings. Check the selected columns and spacing.'), 400
        try:
            data, columns, placements = preview_report(source, report_id, g.printer_config, options, notes)
            if kind == 'columns':
                response = jsonify(columns=list(columns))
            else:
                response = make_response(data)
                response.headers['Content-Type'] = 'application/pdf'
                response.headers['Content-Disposition'] = 'inline; filename="report-preview.pdf"'
                response.headers['X-Notes-Rows'] = str(sum(p.rows for p in placements))
                response.headers['X-Notes-Scale'] = str(min((p.scale for p in placements), default=1))
            response.headers['Cache-Control'] = 'no-store'
            return response
        except ReportNotesError as exc:
            return jsonify(error=str(exc)), 422
        except Exception:
            # No source credentials, workbook contents, or local paths in errors.
            return jsonify(error='Report preview unavailable. Check the connection, print settings, and page policy.'), 503

    @bp.post('/save')
    def save():
        try:
            old = next((j for j in repository.list() if j.job_id == request.form.get('job_id')), None)
            options = PrintOptions().apply({key: request.form[key] for key in (*CHOICES, *NUMBERS)
                                           if key in request.form})
            selected = request.form.getlist('report_id')
            if not selected or len(selected) != len(set(selected)):
                raise ValueError('Select reports without duplicates.')
            previous = {r.report_id: r for r in old.reports} if old else {}
            reports = []
            for report_id in selected:
                raw = request.form.get('override_' + report_id, '{}')
                overrides = json.loads(raw)
                if not isinstance(overrides, dict):
                    raise ValueError('Invalid report overrides')
                prior = previous.get(report_id)
                name = prior.name if prior else request.form.get('report_name_' + report_id, '')
                if not name or len(name) > 255 or not report_id.startswith('00O'):
                    raise ValueError('Invalid selected report.')
                notes = prior.notes if prior else ReportNotesOptions()
                if 'notes_' + report_id in request.form:
                    notes = ReportNotesOptions.from_dict(json.loads(request.form['notes_' + report_id]))
                reports.append(ScheduledReport(report_id, name, overrides, notes))
            hour, minute = map(int, request.form['time'].split(':'))
            job = ReportPrintingJob(
                job_id=old.job_id if old else uuid.uuid4().hex,
                name=request.form['name'].strip(), timezone=g.printer_config.timezone,
                hour=hour, minute=minute,
                weekdays=tuple(int(v) for v in request.form.getlist('weekday')),
                defaults=options, reports=tuple(reports),
                enabled=request.form.get('enabled') == 'on')
            repository.save(job)
            return redirect(url_for('.page'))
        except (ValueError, KeyError, TypeError) as exc:
            return str(exc), 400

    @bp.post('/<job_id>/delete')
    def delete(job_id):
        repository.delete(job_id)
        return redirect(url_for('.page'))

    return bp
