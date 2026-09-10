"""Independent authenticated Flask app. No worker starts as an import side effect."""
from datetime import datetime, timedelta
import hmac
import secrets
import threading
import time
from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash


def create_app(config, control):
    if len(config.session_secret) < 32 or not config.ui_password_hash:
        raise RuntimeError('Printer UI authentication is not configured; run python -m printer_app configure')
    app = Flask(__name__)
    app.config.update(SECRET_KEY=config.session_secret, SESSION_COOKIE_NAME='printer_app_session', SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=config.secure_cookie,
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=16384)
    failures, lock = {}, threading.Lock()

    @app.template_filter('localtime')
    def localtime(value):
        return datetime.fromtimestamp(value).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z') if value else '-'

    @app.before_request
    def protect():
        if request.endpoint == 'health':
            return None
        session.setdefault('csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            supplied = request.form.get('csrf', '')
            if not hmac.compare_digest(supplied.encode('utf-8'), session['csrf'].encode('utf-8')):
                abort(400, 'Invalid CSRF token')
        if request.endpoint not in {'login', 'static'} and not session.get('authenticated'):
            if request.path.startswith('/api/'):
                return jsonify(error='Printer UI authentication required'), 401
            return redirect(url_for('login'))
        return None

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'none'; style-src 'self'; object-src 'self'; frame-ancestors 'self'; form-action 'self'; base-uri 'none'"
        return response

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        error = ''
        if request.method == 'POST':
            address = request.remote_addr or 'unknown'
            now = time.monotonic()
            with lock:
                for key in list(failures):
                    if now - failures[key][1] > 900:
                        del failures[key]
                count, at = failures.get(address, (0, now))
                if count >= 5 and now - at < 300:
                    return render_template('login.html', error='Too many attempts. Try again later.'), 429
                valid_password = check_password_hash(config.ui_password_hash, request.form.get('password', ''))
                if request.form.get('username', '') == config.ui_user and valid_password:
                    failures.pop(address, None)
                    session.clear()
                    session.update(authenticated=True, csrf=secrets.token_urlsafe(32))
                    session.permanent = True
                    return redirect(url_for('dashboard'))
                if len(failures) >= 512:
                    failures.pop(next(iter(failures)))
                failures[address] = (count + 1, now)
            error = 'Incorrect username or password'
        return render_template('login.html', error=error), 401 if error else 200

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.get('/health')
    def health():
        result = control.health()
        return jsonify(result), 200 if all(result.values()) else 503

    @app.get('/')
    @app.get('/system/print-control')
    def dashboard():
        return render_template('dashboard.html', status=control.status(), jobs=control.recent())

    @app.post('/control/<action>')
    def action(action):
        try:
            control.command(action)
        except ValueError:
            abort(404)
        return redirect(url_for('dashboard'))

    @app.get('/jobs/<job_id>')
    def job(job_id):
        data = control.detail(job_id)
        if data is None:
            abort(404)
        return render_template('job.html', job=data)

    @app.get('/files/<output_id>')
    def artifact(output_id):
        try:
            found = control.artifact(output_id)
        except ValueError:
            abort(404)
        if found is None or not found[0].is_file():
            abort(404)
        path, name = found
        return send_file(path, download_name=name, as_attachment=path.suffix.lower() != '.pdf' or request.args.get('download') == '1')

    return app
