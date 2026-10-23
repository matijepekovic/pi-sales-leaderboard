"""Admin-only Outlook trial HTTP interface. All workflow decisions live in the service."""
from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, send_file, session, url_for

from .repository import SandboxError
from .service import OutlookSandboxService


def blueprint(service: OutlookSandboxService) -> Blueprint:
    bp = Blueprint('outlook_sandbox', __name__)

    def page(error: str = '', code: int = 200):
        return render_template('outlook_sandbox.html',
                               config=service.configuration(),
                               error=error,
                               saved=request.args.get('saved') == '1'), code

    def result(action):
        try:
            return jsonify(ok=True, result=action())
        except SandboxError as exc:
            return jsonify(ok=False, message=str(exc)), 400
        except Exception:
            # Never echo raw token, IMAP, or Microsoft SDK exception payloads.
            return jsonify(ok=False, message='Outlook sandbox request failed. Check the server logs.'), 503

    @bp.get('/outlook-sandbox')
    def page_view():
        return page()

    @bp.post('/outlook-sandbox/config')
    def configure():
        try:
            service.configure(request.form.to_dict())
        except SandboxError as exc:
            return page(str(exc), 400)
        return redirect(url_for('outlook_sandbox.page_view', saved='1'), code=303)

    @bp.post('/outlook-sandbox/connect')
    def connect():
        return result(service.start_login)

    @bp.post('/outlook-sandbox/disconnect')
    def disconnect():
        return result(lambda: (service.disconnect(), {'disconnected': True})[1])

    @bp.get('/outlook-sandbox/status')
    def status():
        return result(service.status)

    @bp.post('/outlook-sandbox/folders')
    def folders():
        return result(service.folders)

    @bp.post('/outlook-sandbox/check')
    def check():
        return result(service.check)

    @bp.post('/outlook-sandbox/stage')
    def stage():
        uid = request.form.get('uid', '')
        def action():
            record = service.stage(uid)
            for item in record['files']:
                item['download_url'] = url_for('outlook_sandbox.file', stage_id=record['id'], index=item['index'])
            return record
        return result(action)

    @bp.get('/outlook-sandbox/staged/<stage_id>/<int:index>')
    def file(stage_id: str, index: int):
        try:
            path, name = service.repository.file(stage_id, index)
        except SandboxError:
            return ('Not found', 404)
        return send_file(path, as_attachment=True, download_name=name,
                         mimetype='application/octet-stream')

    return bp
