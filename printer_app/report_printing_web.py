"""HTTP interface for independently scheduled Salesforce printing jobs."""
import json
import uuid

from flask import Blueprint, g, redirect, render_template, request, url_for

from .print_options import PrintOptions, CHOICES, NUMBERS
from .report_printing_contract import ReportPrintingJob, ScheduledReport


def blueprint(repository, source):
    bp = Blueprint('report_printing', __name__, url_prefix='/report-printing')

    @bp.get('/')
    def page():
        jobs = repository.list()
        selected = next((j for j in jobs if j.job_id == request.args.get('edit')), None)
        try:
            reports = source.search_reports('')
            error = ''
        except Exception as exc:
            reports, error = (), str(exc)
        return render_template('report_printing.html', jobs=jobs, selected=selected,
                               available=reports, error=error, choices=CHOICES, numbers=NUMBERS,
                               runs=repository.runs())

    @bp.post('/save')
    def save():
        try:
            old = next((j for j in repository.list() if j.job_id == request.form.get('job_id')), None)
            options = PrintOptions().apply({key: request.form[key] for key in (*CHOICES, *NUMBERS)
                                           if key in request.form})
            selected = request.form.getlist('report_id')
            catalog = {r['id']: r['name'] for r in source.search_reports('')}
            if not selected or any(r not in catalog for r in selected):
                raise ValueError('Select valid Salesforce reports.')
            reports = []
            for report_id in selected:
                raw = request.form.get('override_' + report_id, '{}')
                overrides = json.loads(raw)
                if not isinstance(overrides, dict):
                    raise ValueError('Invalid report overrides')
                reports.append(ScheduledReport(report_id, catalog[report_id], overrides))
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
