"""HTTP boundary for the isolated Salesforce Sandbox MOD portal."""
from io import BytesIO

from flask import Blueprint, jsonify, render_template, request, send_file

from .pdf_renderer import render_mod_pdf


def _bool_arg(name, default=False):
    value = request.args.get(name)
    if value is None:
        return default
    return str(value).casefold() in ('1', 'true', 'on', 'yes')


def blueprint(service):
    bp = Blueprint('salesforce_sandbox', __name__)

    @bp.get('/salesforce-sandbox')
    def page():
        return render_template('salesforce_sandbox.html', snapshot=service.portal())

    @bp.get('/salesforce-sandbox/api/metadata')
    def metadata():
        snapshot = service.metadata()
        if snapshot.error:
            return jsonify(ok=False, error=snapshot.error), 503
        return jsonify(
            ok=True,
            username=snapshot.status.username,
            alias=snapshot.status.alias,
            fields={
                key: list(value.values)
                for key, value in snapshot.fields.items()
            },
        )

    @bp.get('/salesforce-sandbox/mod-sheet')
    def mod_sheet():
        snapshot = service.generate(
            start_date=request.args.get('startdate', ''),
            end_date=request.args.get('enddate', ''),
            market_segment=request.args.get('marketsegment', ''),
            product_category=request.args.get('productCategory', ''),
            source_type=request.args.get('sourceType', ''),
            remove_canceled=_bool_arg('removeCanceled', False),
            remove_unconfirmed=_bool_arg('removeUnconfirmed', False),
            color_code=_bool_arg('colorCode', False),
            limit=1000,
        )
        if snapshot.error:
            return render_template('salesforce_sandbox_error.html', message=snapshot.error), 400
        pdf = BytesIO(render_mod_pdf(snapshot.records, color_code=snapshot.color_code))
        return send_file(
            pdf,
            mimetype='application/pdf',
            as_attachment=False,
            download_name='MOD-Sheet.pdf',
        )

    return bp
