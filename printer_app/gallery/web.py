"""Gallery HTTP boundary. Shares only the printer web host and write protection."""
import re
import time
from urllib.parse import urlsplit

from flask import (
    Blueprint, Response, abort, current_app, g, jsonify, make_response,
    redirect, render_template, request, send_file, session, url_for,
)


ACCESS_COOKIE = 'gallery_access'


def blueprint(service, access, intake_reader=None, reprocessor=None, admin_session=None, https_access=None):
    bp = Blueprint('gallery', __name__, url_prefix='/gallery')

    public_endpoints = {
        'gallery.redeem_access',
        'gallery.qr',
        'gallery.service_worker',
        'gallery.manifest',
    }
    admin_endpoints = {
        'gallery.queue_page',
        'gallery.import_job_page',
        'gallery.import_item_image',
        'gallery.import_item_lead_name',
        'gallery.approve_import_item',
        'gallery.delete_import_item',
        'gallery.reprocess_job',
        'gallery.summary',
        'gallery.document_date',
    }

    @bp.before_request
    def authorize_gallery():
        if request.endpoint in public_endpoints:
            return None
        if request.endpoint in admin_endpoints:
            admin = admin_session() if admin_session else None
            g.printer_admin = admin
            if admin is None:
                if request.path.startswith('/gallery/api/') or request.method != 'GET':
                    return jsonify(error='Printer admin login required.'), 401
                target = request.full_path if request.query_string else request.path
                return redirect(url_for('admin_login', next=target))
            if admin.must_change:
                return redirect(url_for('admin_change_password', next=request.path))
            return None
        identity = access.resolve(request.cookies.get(ACCESS_COOKIE, ''))
        if identity is None:
            if request.path.startswith('/gallery/api/') or request.method != 'GET':
                return jsonify(error='Gallery access expired. Open a new access link.'), 401
            return render_template('gallery_access.html'), 401
        g.gallery_identity = identity
        return None

    def require(capability):
        identity = getattr(g, 'gallery_identity', None)
        if identity is None or not identity.allows(capability):
            abort(403)
        return identity

    def require_admin():
        admin = getattr(g, 'printer_admin', None)
        if admin is None or admin.must_change:
            abort(403)
        return admin

    @bp.errorhandler(ValueError)
    def bad_value(exc):
        return jsonify(error=str(exc)), 400

    @bp.errorhandler(LookupError)
    def missing(exc):
        return jsonify(error=str(exc)), 404

    @bp.get('/access/<token>')
    def redeem_access(token):
        target = request.args.get('next') or url_for('gallery.page')
        if not (target == '/gallery' or target.startswith('/gallery/')):
            target = url_for('gallery.page')
        # Opening Gallery from Print Control again must not silently create a new
        # full identity and orphan this device's existing offline store.
        existing = access.resolve(request.cookies.get(ACCESS_COOKIE, ''))
        if existing is not None and existing.role == 'full':
            return redirect(target, code=303)
        grant = access.redeem(token)
        if grant is None:
            return render_template('gallery_access.html', expired=True), 410
        response = redirect(target, code=303)
        if grant.identity.expires is None:
            max_age = 365 * 86400
        else:
            max_age = max(1, int(grant.identity.expires - time.time()))
        response.set_cookie(
            ACCESS_COOKIE,
            grant.token,
            max_age=max_age,
            httponly=True,
            secure=bool(current_app.config.get('SESSION_COOKIE_SECURE')),
            # Lax permits the one top-level HTTP -> HTTPS transition used by
            # full-device Offline setup. Gallery writes still require CSRF +
            # same-origin checks, so cross-site POSTs remain rejected.
            samesite='Lax',
            path='/gallery',
        )
        return response

    def secure_device_state():
        state = https_access.status() if https_access else {'configured': False, 'addresses': [], 'dns': []}
        hostname = urlsplit('//' + request.host).hostname or ''
        candidates = [*state.get('addresses', []), *state.get('dns', [])]
        target = hostname if hostname in candidates else (candidates[0] if candidates else hostname)
        if ':' in target and not target.startswith('['):
            target = '[' + target + ']'
        return dict(
            configured=bool(state.get('configured') and target),
            secure_url=('https://' + target + url_for('gallery.page')) if target else '',
            fingerprint=state.get('fingerprint', ''),
        )

    @bp.get('')
    @bp.get('/')
    def page():
        require('browse')
        return render_template('gallery.html')

    @bp.get('/offline-setup')
    def offline_setup():
        require('offline')
        state = secure_device_state()
        response = make_response(render_template('gallery_offline_setup.html', secure=state))
        # Existing full devices may still carry the older SameSite=Strict cookie.
        # Refresh the exact same credential as Lax before the one top-level
        # HTTP -> HTTPS transition; the full identity/subject does not change.
        token = request.cookies.get(ACCESS_COOKIE, '')
        if token:
            response.set_cookie(
                ACCESS_COOKIE,
                token,
                max_age=365 * 86400,
                httponly=True,
                secure=bool(current_app.config.get('SESSION_COOKIE_SECURE')),
                samesite='Lax',
                path='/gallery',
            )
        return response

    @bp.get('/offline-setup/root-ca.cer')
    def offline_root_ca():
        require('offline')
        path = https_access.root_certificate() if https_access else None
        if not path:
            abort(503)
        response = send_file(
            path,
            mimetype='application/pkix-cert',
            as_attachment=True,
            download_name='stats-gallery-local-ca.cer',
            conditional=False,
        )
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @bp.get('/api/access')
    def access_info():
        identity = require('browse')
        result = dict(
            role=identity.role,
            subject=identity.subject,
            expires=identity.expires,
            capabilities=sorted(identity.capabilities),
            csrf=session.get('csrf', ''),
        )
        if identity.allows('offline'):
            result['secure_offline'] = secure_device_state()
        return jsonify(result)

    def qr_svg(destination):
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics import renderSVG
        code = QrCodeWidget(destination)
        drawing = Drawing(100, 100)
        drawing.add(code)
        value = renderSVG.drawToString(drawing)
        return value.decode('utf-8') if isinstance(value, bytes) else value

    @bp.post('/api/share')
    def share_access():
        identity = require('share')
        shared = access.create_guest_share(identity.subject, request.form.get('name', ''))
        token = shared.pop('token')
        host = urlsplit('//' + request.host).hostname or ''
        if ':' in host and not host.startswith('['):
            host = '[' + host + ']'
        port = int(current_app.config.get('PRINTER_PORT', 5055))
        destination = f'http://{host}:{port}' + url_for('gallery.redeem_access', token=token)
        return jsonify(session=shared, qr_svg=qr_svg(destination))

    @bp.get('/api/shares')
    def active_shares():
        identity = require('share')
        return jsonify(sessions=access.active_shares(identity.subject))

    @bp.post('/api/shares/<share_id>/revoke')
    def revoke_share(share_id):
        identity = require('share')
        access.revoke_share(identity.subject, share_id)
        return jsonify(ok=True)

    @bp.get('/api/offline/index')
    def offline_index():
        require('offline')
        return jsonify(service.offline_index())

    @bp.get('/queue')
    def queue_page():
        require_admin()
        state = request.args.get('state', '')
        offset = max(0, min(int(request.args.get('offset', '0')), 1000000))
        queue = service.queue(state, offset)
        intake = intake_reader() if intake_reader else []
        return render_template('gallery_queue.html', queue=queue, intake=intake,
                               state_filter=state, offset=offset)

    @bp.get('/jobs/<ident>')
    def import_job_page(ident):
        require_admin()
        if not re.fullmatch(r'[a-f0-9]{64}', ident):
            abort(404)
        offset = max(0, min(int(request.args.get('offset', '0')), 1000000))
        job = service.import_job(ident, offset)
        if not job:
            abort(404)
        return render_template('gallery_job.html', job=job, offset=offset)

    def retained_job_item(import_id, item_id):
        if not re.fullmatch(r'[a-f0-9]{64}', import_id) or not re.fullmatch(r'[a-f0-9]{64}', item_id):
            abort(404)
        item = service.import_item(import_id, item_id)
        if not item:
            abort(404)
        return item

    def action_offset():
        return max(0, min(int(request.form.get('offset', '0')), 1000000))

    @bp.get('/jobs/<ident>/items/<item_id>/image')
    def import_item_image(ident, item_id):
        require_admin()
        retained_job_item(ident, item_id)
        path = service.files.path('crops', item_id)
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype='image/png', conditional=True)

    @bp.post('/jobs/<ident>/items/<item_id>/lead-name')
    def import_item_lead_name(ident, item_id):
        require_admin()
        retained_job_item(ident, item_id)
        result = service.import_item_lead(
            ident, item_id, request.form.get('lead_name', '')
        )
        return redirect(
            url_for(
                'gallery.import_job_page',
                ident=ident,
                offset=action_offset(),
                action='renamed',
                renamed_state=result['state'],
            ) + '#item-' + item_id,
            code=303,
        )

    @bp.post('/jobs/<ident>/items/<item_id>/approve')
    def approve_import_item(ident, item_id):
        require_admin()
        retained_job_item(ident, item_id)
        service.approve_import_item(ident, item_id)
        return redirect(url_for('gallery.import_job_page', ident=ident, offset=action_offset(),
                                action='approved'), code=303)

    @bp.post('/jobs/<ident>/items/<item_id>/delete')
    def delete_import_item(ident, item_id):
        require_admin()
        retained_job_item(ident, item_id)
        service.delete_import_item(ident, item_id)
        return redirect(url_for('gallery.import_job_page', ident=ident, offset=action_offset(),
                                action='deleted'), code=303)

    @bp.post('/jobs/<ident>/reprocess')
    def reprocess_job(ident):
        require_admin()
        if not re.fullmatch(r'[a-f0-9]{64}', ident):
            abort(404)
        if reprocessor is None:
            abort(503)
        reprocessor.reprocess(ident)
        state = request.args.get('state', '')
        offset = max(0, min(int(request.args.get('offset', '0')), 1000000))
        return redirect(url_for('gallery.queue_page', state=state, offset=offset, reprocess='1'), code=303)

    @bp.get('/qr.svg')
    def qr():
        # Control supplies a short-lived full-access enrollment token. The
        # generated SVG never calls an external QR service.
        token = request.args.get('token', '')
        destination = (
            url_for('gallery.redeem_access', token=token, _external=True)
            if token else url_for('gallery.page', _external=True)
        )
        return Response(qr_svg(destination), mimetype='image/svg+xml')

    @bp.get('/service-worker.js')
    def service_worker():
        response = make_response(current_app.send_static_file('gallery_sw.js'))
        response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
        response.headers['Service-Worker-Allowed'] = '/gallery/'
        return response

    @bp.get('/manifest.webmanifest')
    def manifest():
        response = make_response(current_app.send_static_file('gallery.webmanifest'))
        response.headers['Content-Type'] = 'application/manifest+json'
        return response

    @bp.get('/api/items')
    def items():
        require('browse')
        return jsonify(service.search(request.args.get('q', ''), int(request.args.get('offset', '0')),
                                      request.args.get('date', '')))

    @bp.get('/api/summary')
    def summary():
        require_admin()
        try:
            return jsonify(service.summary(g.printer_config.gallery))
        except Exception:
            return jsonify(error='Gallery storage is unavailable. Printer operation is separate.'), 503

    def existing(ident):
        if not re.fullmatch(r'[a-f0-9]{64}', ident):
            abort(404)
        item = service.item(ident)
        if not item:
            abort(404)
        return item

    @bp.get('/api/items/<ident>')
    def detail(ident):
        require('browse')
        return jsonify(existing(ident))

    @bp.get('/api/items/<ident>/related')
    def related(ident):
        require('browse')
        existing(ident)
        return jsonify(service.related(ident, int(request.args.get('offset', '0')),
                                       request.args.get('date', '')))

    @bp.post('/api/items/<ident>/lead-name')
    def lead_name(ident):
        require('edit_identity')
        existing(ident)
        result = service.lead(ident, request.form.get('lead_name', ''))
        return jsonify(ok=True, **result)

    @bp.get('/image/<ident>')
    def image(ident):
        require('browse')
        existing(ident)
        path = service.files.path('crops', ident)
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype='image/png', conditional=True)

    @bp.post('/api/items/<ident>/notes')
    def note(ident):
        require('notes')
        existing(ident)
        service.note(ident, request.form.get('note_id', ''), request.form.get('author', ''), request.form.get('body', ''))
        return jsonify(ok=True)

    @bp.post('/api/items/<ident>/date')
    def document_date(ident):
        require_admin()
        existing(ident)
        service.date(ident, request.form.get('date', ''))
        return jsonify(ok=True)

    return bp
