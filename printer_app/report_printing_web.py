"""HTTP interface for independently scheduled Salesforce printing jobs."""
import json
import uuid

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

from .print_options import PrintOptions, CHOICES, NUMBERS
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
            all_reports = source.search_reports(term, folder=folder)
            matched = [r for r in all_reports if (r['folder'] or 'Unfiled') == folder]
            return jsonify(reports=matched, total=len(matched))
        except Exception:
            return jsonify(error='Report search unavailable'), 503

    @bp.post('/save')
    def save():
        try:
            old = next((j for j in repository.list() if j.job_id == request.form.get('job_id')), None)
            options = PrintOptions().apply({key: request.form[key] for key in (*CHOICES, *NUMBERS)
                                           if key in request.form})
            selected = request.form.getlist('report_id')
            if not selected or len(selected) != len(set(selected)):
                raise ValueError('Select reports without duplicates.')
            previous = {r.report_id: r.name for r in old.reports} if old else {}
            reports = []
            for report_id in selected:
                raw = request.form.get('override_' + report_id, '{}')
                overrides = json.loads(raw)
                if not isinstance(overrides, dict):
                    raise ValueError('Invalid report overrides')
                name = previous.get(report_id) or request.form.get('report_name_' + report_id, '')
                if not name or len(name) > 255 or not report_id.startswith('00O'):
                    raise ValueError('Invalid selected report.')
                reports.append(ScheduledReport(report_id, name, overrides))
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
