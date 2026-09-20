"""Standalone printer control UI. This process never polls email or submits print jobs."""
from __future__ import annotations

import hmac
import secrets
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import g, Flask, abort, jsonify, redirect, render_template, request, send_file, session, url_for

from .admin_auth import AdminAuthService
from .admin_auth_repository import AdminAuthRepository
from .print_options import CHOICES as PRINT_CHOICES, NUMBERS as PRINT_NUMBERS
from .config import Config, environment_file
from .settings import SettingsService, SettingsError
from .settings_repository import SettingsRepository, SettingsStorageError, SettingsConflict
from .gmail_client import test_connection
from .db import Database
from .print_schedule import DAYS as SCHEDULE_DAYS, MODES as SCHEDULE_MODES
from .print_dispatch import PrintDispatchService
from .print_queue_repository import PrintQueueRepository
from .retention_repository import RetentionRepository
from .attachment_routing_repository import AttachmentRoutingRepository
from .gallery.bootstrap import build as build_gallery, build_access as build_gallery_access
from .gallery.web import blueprint as gallery_blueprint
from .gallery_reprocess import GalleryReprocessService
from .https_adapter import GalleryHttpsAdapter
from .salesforce_sandbox.adapter import SalesforceCliAdapter
from .salesforce_sandbox.service import SalesforceSandboxService
from .salesforce_sandbox.web import blueprint as salesforce_sandbox_blueprint


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
        PRINTER_PORT=cfg.port,
        MAX_CONTENT_LENGTH=16384, MAX_FORM_MEMORY_SIZE=16384, MAX_FORM_PARTS=64)
    db = Database(cfg.db_path)
    admin_auth = AdminAuthService(AdminAuthRepository(db))

    def request_command(name):
        with db.connect() as conn:
            if not conn.execute('SELECT 1 FROM commands WHERE name=?', (name,)).fetchone():
                conn.execute('INSERT INTO commands(name,created) VALUES (?,?)', (name, time.time()))

    app.extensions['printer_db'] = db
    app.extensions['printer_settings'] = settings
    app.extensions['printer_admin_auth'] = admin_auth
    gallery = build_gallery(cfg.data_dir)
    gallery_access = build_gallery_access(cfg.data_dir)
    gallery_https = GalleryHttpsAdapter(cfg.data_dir)
    intake = AttachmentRoutingRepository(db)
    reprocess = GalleryReprocessService(gallery, intake, lambda: request_command('run-now'))
    app.extensions['printer_gallery'] = gallery
    app.extensions['gallery_access'] = gallery_access
    app.extensions['gallery_reprocess'] = reprocess
    app.extensions['gallery_https'] = gallery_https

    def current_admin_session():
        return admin_auth.session_state(session.get('printer_admin_revision'))

    app.register_blueprint(gallery_blueprint(
        gallery, gallery_access, intake.intake, reprocess,
        admin_session=current_admin_session, https_access=gallery_https,
    ))

    # Beta-only, read-only external source. Salesforce details stay behind the
    # adapter and this composition boundary; Gallery and printing do not depend on it.
    salesforce_sandbox = SalesforceSandboxService(
        SalesforceCliAdapter(executable='/usr/bin/sf', target_org='work')
    )
    app.extensions['salesforce_sandbox'] = salesforce_sandbox
    app.register_blueprint(salesforce_sandbox_blueprint(salesforce_sandbox))

    @app.template_filter('localtime')
    def localtime(value):
        return datetime.fromtimestamp(float(value), ZoneInfo(getattr(g, 'printer_config', cfg).timezone)).strftime('%Y-%m-%d %H:%M:%S %Z') if value else '—'

    def safe_next(value):
        value = str(value or '')
        if not value.startswith('/') or value.startswith('//'):
            return url_for('control')
        return value

    def login_redirect():
        target = request.full_path if request.query_string else request.path
        return redirect(url_for('admin_login', next=safe_next(target)))

    def normalized_origin(value):
        try:
            parsed = urlsplit(str(value or ''))
            if parsed.scheme not in ('http', 'https') or not parsed.hostname:
                return ''
            port = parsed.port
        except ValueError:
            return ''
        host = parsed.hostname
        if ':' in host and not host.startswith('['):
            host = '[' + host + ']'
        if port and not ((parsed.scheme == 'http' and port == 80) or
                         (parsed.scheme == 'https' and port == 443)):
            host += ':' + str(port)
        return parsed.scheme + '://' + host

    def effective_request_origin():
        scheme, host = request.scheme, request.host
        # Only the local HTTPS adapter may define forwarded origin metadata.
        # Direct LAN clients cannot make spoofed proxy headers relax CSRF.
        if request.remote_addr in ('127.0.0.1', '::1'):
            forwarded_proto = request.headers.get('X-Forwarded-Proto', '').split(',', 1)[0].strip()
            forwarded_host = request.headers.get('X-Forwarded-Host', '').split(',', 1)[0].strip()
            if forwarded_proto in ('http', 'https'):
                scheme = forwarded_proto
            if forwarded_host and '/' not in forwarded_host and '\\' not in forwarded_host and all(
                    c.isalnum() or c in '.-:[]' for c in forwarded_host):
                host = forwarded_host
        return normalized_origin(scheme + '://' + host)

    @app.before_request
    def protect_writes_and_admin():
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
            if (origin and normalized_origin(origin) != effective_request_origin()) or request.headers.get('Sec-Fetch-Site') == 'cross-site':
                abort(403, 'Cross-site changes are not allowed')
            if any(len(request.form.getlist(key)) != 1 for key in request.form):
                abort(400, 'Duplicate form field')
            supplied = request.form.get('csrf', '')
            if not hmac.compare_digest(str(session['csrf']).encode(), supplied.encode()):
                abort(400, 'Invalid CSRF token')

        # Work-order Gallery has its own full/temporary access system. Normal
        # Gallery requests must not depend on the printer-admin database. Its
        # administrative subroutes resolve the injected admin session lazily.
        if request.blueprint == 'gallery':
            return None

        admin = current_admin_session()
        g.printer_admin = admin

        if request.endpoint == 'admin_login':
            if admin and request.method == 'GET':
                return redirect(url_for('admin_change_password') if admin.must_change else url_for('control'))
            return None

        if request.endpoint in ('admin_change_password', 'admin_logout'):
            if not admin:
                return login_redirect()
            return None

        if not admin:
            if request.path.startswith('/api/'):
                return jsonify(error='Printer admin login required.'), 401
            return login_redirect()

        if admin.must_change:
            return redirect(url_for('admin_change_password', next=safe_next(request.path)))
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
        if values.pop('gallery_present', '') == '1':
            values.setdefault('GALLERY_ENABLED', '0')
        if values.pop('cleanup_present', '') == '1':
            for key in ('CLEANUP_ENABLED', 'CLEANUP_EMAILS'):
                values.setdefault(key, '0')
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
            print_schedule=dispatch().summary(), cleanup=RetentionRepository(db).state(),
            gallery_intake_errors=AttachmentRoutingRepository(db).failures())

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

    @app.route('/login', methods=['GET', 'POST'])
    def admin_login():
        error, code = '', 200
        next_url = safe_next(request.values.get('next'))
        if request.method == 'POST':
            state, error = admin_auth.authenticate(
                request.form.get('username', ''),
                request.form.get('password', ''),
                request.remote_addr or 'unknown',
            )
            if state:
                session.clear()
                session['csrf'] = secrets.token_urlsafe(32)
                session['printer_admin_revision'] = state.revision
                session.permanent = True
                if state.must_change:
                    return redirect(url_for('admin_change_password', next=next_url), code=303)
                return redirect(next_url, code=303)
            code = 429 if error.startswith('Too many') else 401
        return render_template('admin_login.html', error=error, next_url=next_url), code

    @app.route('/change-password', methods=['GET', 'POST'])
    def admin_change_password():
        admin = g.printer_admin
        next_url = safe_next(request.values.get('next'))
        error, code = '', 200
        if request.method == 'POST':
            try:
                revision = admin_auth.change_password(
                    request.form.get('current_password', ''),
                    request.form.get('new_password', ''),
                    request.form.get('confirmation', ''),
                )
                session['printer_admin_revision'] = revision
                session['csrf'] = secrets.token_urlsafe(32)
                return redirect(next_url, code=303)
            except (ValueError, LookupError) as exc:
                error, code = str(exc), 400
        return render_template(
            'admin_change_password.html',
            forced=admin.must_change,
            error=error,
            next_url=next_url,
        ), code

    @app.post('/logout')
    def admin_logout():
        session.pop('printer_admin_revision', None)
        session['csrf'] = secrets.token_urlsafe(32)
        return redirect(url_for('admin_login'), code=303)

    @app.get('/')
    @app.get('/system/print-control')
    def control():
        timing = dispatch()
        # Optional gallery monitoring must never take down Print Control.
        try:
            gallery_queue, gallery_intake, gallery_error = gallery.queue(limit=5), intake.intake(), ''
        except Exception:
            gallery_queue, gallery_intake = None, []
            gallery_error = 'Gallery monitoring is unavailable. Printing is separate.'
        try:
            full_invite = gallery_access.issue_full_invite()
            full_url = url_for('gallery.redeem_access', token=full_invite,
                               next=url_for('gallery.page'))
        except Exception:
            # Gallery access must never become a dependency of printer control.
            full_invite, full_url = '', url_for('gallery.page')
            gallery_error = gallery_error or 'Gallery access is unavailable. Printing is separate.'
        return render_template('control.html', state=state(), jobs=[timing.describe_job(j) for j in db.recent()],
            gallery_queue=gallery_queue, gallery_intake=gallery_intake, gallery_error=gallery_error,
            gallery_full_token=full_invite, gallery_full_url=full_url)

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
            request_command(action)
        else:
            abort(404)
        return redirect(url_for('control'))

    @app.route('/print-queue/<int:attachment_id>/remove', methods=['GET', 'POST'])
    def remove_print_queue(attachment_id):
        try:
            item = dispatch().removal_info(attachment_id)
            if request.method == 'POST':
                if request.form.get('confirm') != 'remove':
                    abort(400, 'Confirm removal of this attachment.')
                dispatch().remove(attachment_id)
                return redirect(url_for('control', removed='1') + '#printQueue', code=303)
            return render_template('remove_print.html', item=item, error='')
        except LookupError:
            abort(404)
        except ValueError as exc:
            return render_template('remove_print.html', item=item, error=str(exc)), 409

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


def web_server_options(cfg):
    """Waitress owns trusted-proxy interpretation at the web-server boundary."""
    return dict(
        host=cfg.host,
        port=cfg.port,
        threads=4,
        max_request_body_size=16384,
        channel_timeout=30,
        ident='printer-app',
        # Caddy connects to Waitress only over this explicit loopback backend.
        # Direct LAN clients are not trusted to supply X-Forwarded-* metadata.
        trusted_proxy='127.0.0.1',
        trusted_proxy_count=1,
        trusted_proxy_headers={'x-forwarded-host', 'x-forwarded-proto'},
        clear_untrusted_proxy_headers=True,
    )


def main():
    from waitress import serve
    cfg = Config.from_env()
    serve(create_app(cfg), **web_server_options(cfg))


if __name__ == '__main__':
    main()
