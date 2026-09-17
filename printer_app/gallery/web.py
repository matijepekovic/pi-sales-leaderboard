"""Gallery HTTP boundary. Shares only the printer web host and write protection."""
import re
from flask import Blueprint, Response, abort, g, jsonify, render_template, request, send_file, url_for


def blueprint(service):
    bp = Blueprint('gallery', __name__, url_prefix='/gallery')

    @bp.errorhandler(ValueError)
    def bad_value(exc):
        return jsonify(error=str(exc)), 400

    @bp.errorhandler(LookupError)
    def missing(exc):
        return jsonify(error=str(exc)), 404

    @bp.get('')
    @bp.get('/')
    def page():
        return render_template('gallery.html')

    @bp.get('/qr.svg')
    def qr():
        # Local generation, no URL-shortener, cloud API or external image requests.
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics import renderSVG
        code = QrCodeWidget(url_for('gallery.page', _external=True))
        drawing = Drawing(100, 100)
        drawing.add(code)
        return Response(renderSVG.drawToString(drawing), mimetype='image/svg+xml')

    @bp.get('/api/items')
    def items():
        return jsonify(service.search(request.args.get('q', ''), int(request.args.get('offset', '0'))))

    @bp.get('/api/summary')
    def summary():
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
        # Data for the in-gallery dialog, not a separate document page.
        return jsonify(existing(ident))

    @bp.get('/api/items/<ident>/related')
    def related(ident):
        existing(ident)
        return jsonify(service.related(ident, int(request.args.get('offset', '0'))))

    @bp.post('/api/items/<ident>/lead-name')
    def lead_name(ident):
        existing(ident)
        service.lead(ident, request.form.get('lead_name', ''))
        return jsonify(ok=True)

    @bp.get('/image/<ident>')
    def image(ident):
        existing(ident)
        path = service.files.path('crops', ident)
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype='image/png', conditional=True)

    @bp.post('/api/items/<ident>/notes')
    def note(ident):
        existing(ident)
        service.note(ident, request.form.get('note_id', ''), request.form.get('author', ''), request.form.get('body', ''))
        return jsonify(ok=True)

    @bp.post('/api/items/<ident>/date')
    def document_date(ident):
        existing(ident)
        service.date(ident, request.form.get('date', ''))
        return jsonify(ok=True)

    return bp
