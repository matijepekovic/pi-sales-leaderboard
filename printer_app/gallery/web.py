"""Gallery HTTP boundary. Shares only the printer web host and write protection."""
import re
import time

from flask import (
    Blueprint, Response, abort, current_app, g, jsonify, make_response,
    redirect, render_template, request, send_file, session, url_for,
)


ACCESS_COOKIE = 'gallery_access'


def blueprint(service, access, intake_reader=None, reprocessor=None):
    bp = Blueprint('gallery', __name__, url_prefix='/gallery')

    public_endpoints = {
        'gallery.redeem_access',
        'gallery.qr',
        'gallery.service_worker',
        'gallery.manifest',
    }

    @bp.before_request
    def authorize_gallery():
        if request.endpoint in public_endpoints:
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
            samesite='Strict',
            path='/gallery',
        )
        return response

    @bp.get('')
    @bp.get('/')
    def page():
        require('browse')
        return render_template('gallery.html')

    @bp.get('/api/access')
    def access_info():
        identity = require('browse')
        return jsonify(
            role=identity.role,
            subject=identity.subject,
            expires=identity.expires,
            capabilities=sorted(identity.capabilities),
            csrf=session.get('csrf', ''),
        )

    @bp.post('/api/share')
    def share_access():
        require('share')
        token = access.issue_guest_invite(86400)
        return jsonify(
            url=url_for('gallery.redeem_access', token=token, _external=True),
            expires_in=86400,
        )

    @bp.get('/api/offline/index')
    def offline_index():
        require('offline')
        return jsonify(service.offline_index())

    @bp.get('/queue')
    def queue_page():
        require('manage')
        state = request.args.get('state', '')
        offset = max(0, min(int(request.args.get('offset', '0')), 1000000))
        queue = service.queue(state, offset)
        intake = intake_reader() if intake_reader else []
        return render_template('gallery_queue.html', queue=queue, intake=intake,
                               state_filter=state, offset=offset)

    @bp.get('/jobs/<ident>')
    def import_job_page(ident):
        require('manage')
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
        require('manage')
        retained_job_item(ident, item_id)
        path = service.files.path('crops', item_id)
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype='image/png', conditional=True)

    @bp.post('/jobs/<ident>/items/<item_id>/approve')
    def approve_import_item(ident, item_id):
        require('manage')
        retained_job_item(ident, item_id)
        service.approve_import_item(ident, item_id)
        return redirect(url_for('gallery.import_job_page', ident=ident, offset=action_offset(),
                                action='approved'), code=303)

    @bp.post('/jobs/<ident>/items/<item_id>/delete')
    def delete_import_item(ident, item_id):
        require('manage')
        retained_job_item(ident, item_id)
        service.delete_import_item(ident, item_id)
        return redirect(url_for('gallery.import_job_page', ident=ident, offset=action_offset(),
                                action='deleted'), code=303)

    @bp.post('/jobs/<ident>/reprocess')
    def reprocess_job(ident):
        require('manage')
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
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics import renderSVG

        token = request.args.get('token', '')
        destination = (
            url_for('gallery.redeem_access', token=token, _external=True)
            if token else url_for('gallery.page', _external=True)
        )
        code = QrCodeWidget(destination)
        drawing = Drawing(100, 100)
        drawing.add(code)
        return Response(renderSVG.drawToString(drawing), mimetype='image/svg+xml')

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
        require('manage')
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
        require('manage')
        existing(ident)
        service.lead(ident, request.form.get('lead_name', ''))
        return jsonify(ok=True)

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
        require('manage')
        existing(ident)
        service.date(ident, request.form.get('date', ''))
        return jsonify(ok=True)

    return bp
