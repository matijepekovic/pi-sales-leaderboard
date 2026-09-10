"""Standalone authenticated web UI. This process never polls email or submits print jobs."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash

from .config import Config
from .db import Database


def create_app(cfg: Config | None = None) -> Flask:
    cfg = cfg or Config.from_env()
    if not cfg.password_hash or len(cfg.secret_key) < 32:
        raise ValueError('Printer UI credentials are required. Run printer_app.bootstrap init first.')
    app = Flask(__name__)
    app.config.update(SECRET_KEY=cfg.secret_key, SESSION_COOKIE_NAME='printer_app_session',
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
        SESSION_COOKIE_SECURE=cfg.secure_cookie, PERMANENT_SESSION_LIFETIME=8 * 3600,
        MAX_CONTENT_LENGTH=8192, MAX_FORM_MEMORY_SIZE=8192, MAX_FORM_PARTS=10)
    db = Database(cfg.db_path)
    app.extensions['printer_db'] = db
    auth_version = hashlib.sha256(cfg.password_hash.encode()).hexdigest()

    @app.template_filter('localtime')
    def localtime(value):
        return datetime.fromtimestamp(float(value), ZoneInfo(cfg.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z') if value else '—'

    @app.before_request
    def protect():
        if request.endpoint == 'health':
            return None
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        if request.method == 'POST':
            supplied = request.form.get('csrf', '')
            if not hmac.compare_digest(str(session['csrf']), supplied):
                abort(400, 'Invalid CSRF token')
        if request.endpoint not in ('login', 'static') and session.get('auth') != auth_version:
            if request.path.startswith('/api/'):
                return jsonify(error='Authentication required'), 401
            return redirect(url_for('login'))
        return None

    @app.after_request
    def security_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers.setdefault('Content-Security-Policy',
            "default-src 'self'; script-src 'none'; style-src 'self'; frame-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'self'")
        return response

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        error = ''
        if request.method == 'POST':
            address = request.remote_addr or 'unknown'
            now = time.time()
            with db.connect() as conn:
                conn.execute('DELETE FROM login_limits WHERE reset_at<?', (now,))
                row = conn.execute('SELECT * FROM login_limits WHERE address=?', (address,)).fetchone()
                if row and row['attempts'] >= 10:
                    return render_template('login.html', error='Too many attempts. Try again in five minutes.'), 429
                conn.execute('''INSERT INTO login_limits VALUES (?,1,?) ON CONFLICT(address)
                    DO UPDATE SET attempts=attempts+1''', (address, now + 300))
            valid = check_password_hash(cfg.password_hash, request.form.get('password', ''))
            if valid and hmac.compare_digest(request.form.get('username', ''), cfg.ui_user):
                db.execute('DELETE FROM login_limits WHERE address=?', (address,))
                session.clear()
                session.update(auth=auth_version, csrf=secrets.token_urlsafe(32))
                session.permanent = True
                return redirect(url_for('control'))
            error = 'Incorrect username or password.'
        return render_template('login.html', error=error), 401 if error else 200

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    def state():
        heartbeat = db.get('worker_heartbeat', 0)
        return dict(queue=cfg.queue, printer=db.get('printer_status', {'known': False, 'online': False, 'detail': 'Waiting for worker'}),
            worker_alive=time.time() - heartbeat < 30, paused=db.get('paused', False),
            last_check=db.get('last_check'), next_check=db.get('next_check'),
            gmail=db.get('gmail_state', 'STARTING'), monitor_error=db.get('monitor_error', ''),
            last_success=db.get('last_successful_print'), last_error=db.get('last_printer_error'))

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
        return render_template('control.html', state=state(), jobs=db.recent())

    @app.get('/api/status')
    def api_status():
        return jsonify(state())

    @app.post('/control/<action>')
    def command(action):
        if action in ('pause', 'resume'):
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
        return render_template('job.html', job=job, outputs=outputs, preview=preview,
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
