"""Standalone printer control UI. This process never polls email or submits print jobs."""
from __future__ import annotations

import hmac
import secrets
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import g, Flask, abort, jsonify, redirect, render_template, request, send_file, session, url_for

from .print_options import CHOICES as PRINT_CHOICES, NUMBERS as PRINT_NUMBERS
from .config import Config, environment_file
from .settings import SettingsService, SettingsError
from .settings_repository import SettingsRepository, SettingsStorageError, SettingsConflict
from .gmail_client import test_connection
from .db import Database
from .print_schedule import DAYS as SCHEDULE_DAYS, MODES as SCHEDULE_MODES
from .print_dispatch import PrintDispatchService
from .print_queue_repository import PrintQueueRepository


def create_app(cfg: Config | None = None, settings_service: SettingsService | None = None) -> Flask:
    cfg = cfg or Config.from_env()
    if len(cfg.secret_key) < 32:
        raise ValueError('Printer UI session secret is required. Run printer_app.bootstrap init first.')
    settings = settings_service or SettingsService(
        SettingsRepository(cfg.env_file or environment_file()), cfg, test_connection)
    app = Flask(__name__)
    app.config.update(SECRET_KEY=cfg.secret_key, SESSION_COOKIE_NAME='printer_app_session',
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
        SESSION_COOKIE_SECURE=cfg.secure_cookie, PERMANENT_SESSION_LIFETIME=8 * 3600,
        MAX_CONTENT_LENGTH=8192, MAX_FORM_MEMORY_SIZE=8192, MAX_FORM_PARTS=64)
    db = Database(cfg.db_path)
    app.extensions['printer_db'] = db
    app.extensions['printer_settings'] = settings

    @app.template_filter('localtime')
    def localtime(value):
        return datetime.fromtimestamp(float(value), ZoneInfo(getattr(g, 'printer_config', cfg).timezone)).strftime('%Y-%m-%d %H:%M:%S %Z') if value else '—'

    @app.before_request
    def protect_writes():
        if request.endpoint in ('health', 'static'):
            return None
        try:
            g.printer_config, g.settings_revision = settings.read()
        except (SettingsError, SettingsStorageError):
            g.printer_config, g.settings_revision = cfg, ''
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
            session.permanent = True
        if request.method == 'POST':
            origin = request.headers.get('Origin')
            if (origin and origin != request.host_url.rstrip('/')) or request.headers.get('Sec-Fetch-Site') == 'cross-site':
                abort(403, 'Cross-site changes are not allowed')
            if any(len(request.form.getlist(key)) != 1 for key in request.form):
                abort(400, 'Duplicate form field')
            supplied = request.form.get('csrf', '')
            if not hmac.compare_digest(str(session['csrf']).encode(), supplied.encode()):
                abort(400, 'Invalid CSRF token')
        return None

    @app.after_request
    def security_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        # no-referrer makes native form POSTs send Origin: null, so our own
        # Settings/Control forms fail the origin guard. Keep same-origin metadata
        # while still withholding referrers from every external destination.
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers.setdefault('Content-Security-Policy',
            "default-src 'self'; script-src 'self'; style-src 'self'; frame-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'self'")
        return response

    def dispatch():
        current = getattr(g, 'printer_config', cfg)
        return PrintDispatchService(PrintQueueRepository(db), current.print_schedule, current.timezone)

    def settings_form():
        # Distinct checkbox names keep the duplicate-field protection intact;
        # normalize only here, where browser form details belong.
        values = request.form.to_dict()
        if values.pop('schedule_days_present', '') == '1':
            if 'PRINT_SCHEDULE_DAYS' in values:
                abort(400, 'Duplicate schedule days representation')
            selected = []
            for key, _ in SCHEDULE_DAYS:
                value = values.pop('schedule_day_' + key, None)
                if value is not None:
                    if value != '1':
                        abort(400, 'Invalid schedule day')
                    selected.append(key)
            values['PRINT_SCHEDULE_DAYS'] = ','.join(selected)
        return values

    def state():
        heartbeat = db.get('worker_heartbeat', 0)
        current = getattr(g, 'printer_config', cfg)
        return dict(queue=current.queue, email_enabled=current.email_enabled,
            settings_applied=bool(getattr(g, 'settings_revision', '')) and g.settings_revision == db.get('settings_revision'),
            settings_error=db.get('settings_error', ''), printer=db.get('printer_status', {'known': False, 'online': False, 'detail': 'Waiting for worker'}),
            worker_alive=time.time() - heartbeat < 30, paused=db.get('paused', False),
            last_check=db.get('last_check'), next_check=db.get('next_check'),
            gmail=db.get('gmail_state', 'STARTING'), monitor_error=db.get('monitor_error', ''),
            last_success=db.get('last_successful_print'), last_error=db.get('last_printer_error'),
            print_schedule=dispatch().summary())

    @app.get('/health')
    def health():
        try:
            db.one('SELECT 1')
            live = time.time() - db.get('worker_heartbeat', 0) < 30
            known = bool(db.get('printer_status', {}).get('known'))
            result = dict(web=True, database=True, worker_running=live, cups_queue_known=known)
        except Exception:
            result = dict(web=True, database=False, worker_running=False, cups_queue_known=False)
        return jsonify(result), 200 if all(result.values()) else 503

    @app.get('/')
    @app.get('/system/print-control')
    def control():
        timing = dispatch()
        return render_template('control.html', state=state(), jobs=[timing.describe_job(j) for j in db.recent()])

    def settings_view(error='', code=200):
        try:
            current, revision = settings.read()
        except (SettingsError, SettingsStorageError):
            current, revision = cfg, ''
            error, code = 'Could not read settings. Use the leaderboard Update button to repair the installation.', 503
        return render_template('settings.html', values=settings.public_values(current),
            password_saved=bool(current.email_password), revision=revision, queue=current.queue,
            print_choices=PRINT_CHOICES, print_numbers=PRINT_NUMBERS,
            schedule_days=SCHEDULE_DAYS, schedule_modes=SCHEDULE_MODES,
            error=error, saved=request.args.get('saved') == '1', state=state()), code

    @app.route('/settings', methods=['GET', 'POST'])
    def settings_page():
        if request.method == 'POST':
            try:
                settings.save(settings_form())
            except SettingsConflict as exc:
                return settings_view(str(exc), 409)
            except (SettingsError, SettingsStorageError) as exc:
                return settings_view(str(exc), 400)
            return redirect(url_for('settings_page', saved='1'), code=303)
        return settings_view()

    @app.post('/settings/test-email')
    def settings_test_email():
        try:
            ok, message = settings.test_email(settings_form())
            return jsonify(ok=ok, message=message), 200 if ok else 400
        except (SettingsError, SettingsStorageError) as exc:
            return jsonify(ok=False, message=str(exc)), 400

    @app.get('/api/status')
    def api_status():
        return jsonify(state())

    @app.post('/control/<action>')
    def command(action):
        if action == 'print-queued-now':
            dispatch().request_print_now()
        elif action in ('pause', 'resume'):
            db.set('paused', action == 'pause')
        elif action in ('run-now', 'test-print'):
            with db.connect() as conn:
                if not conn.execute('SELECT 1 FROM commands WHERE name=?', (action,)).fetchone():
                    conn.execute('INSERT INTO commands(name,created) VALUES (?,?)', (action, time.time()))
        else:
            abort(404)
        return redirect(url_for('control'))

    @app.get('/jobs/<int:job_id>')
    def job_detail(job_id):
        job = db.job(job_id)
        if not job:
            abort(404)
        outputs = db.rows('SELECT * FROM outputs WHERE job_id=? ORDER BY id', (job_id,))
        preview = next((item for item in reversed(outputs) if item['path'].lower().endswith('.pdf')), None)
        return render_template('job.html', job=dispatch().describe_job(job), outputs=outputs, preview=preview,
            print_settings=db.job_print_settings(job_id),
            steps=db.rows('SELECT * FROM steps WHERE job_id=? ORDER BY id', (job_id,)),
            attempts=db.rows('SELECT * FROM print_attempts WHERE job_id=? ORDER BY id', (job_id,)))

    def allowed_file(value: str) -> Path:
        path = Path(value).resolve()
        if not path.is_relative_to(cfg.data_dir.resolve()) or not path.is_file():
            abort(404)
        return path

    @app.get('/outputs/<int:output_id>')
    def output_file(output_id):
        output = db.one('SELECT * FROM outputs WHERE id=?', (output_id,))
        if not output:
            abort(404)
        path = allowed_file(output['path'])
        pdf = path.suffix.lower() == '.pdf'
        response = send_file(path, mimetype='application/pdf' if pdf else 'application/octet-stream',
                             as_attachment=not pdf or request.args.get('download') == '1', download_name=path.name)
        if pdf:
            response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
        return response

    @app.get('/attachments/<int:attachment_id>')
    def attachment_file(attachment_id):
        attachment = db.one('SELECT path FROM attachments WHERE id=?', (attachment_id,))
        if not attachment or not attachment['path']:
            abort(404)
        path = allowed_file(attachment['path'])
        return send_file(path, mimetype='application/octet-stream', as_attachment=True, download_name=path.name)

    return app


def main():
    from waitress import serve
    cfg = Config.from_env()
    serve(create_app(cfg), host=cfg.host, port=cfg.port, threads=4,
          max_request_body_size=8192, channel_timeout=30, ident='printer-app')


if __name__ == '__main__':
    main()
