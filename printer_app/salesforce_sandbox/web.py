"""HTTP boundary for the isolated Salesforce Sandbox MOD portal."""
from flask import Blueprint, render_template, request


def _bool_arg(name, default=False):
    value = request.args.get(name)
    if value is None:
        return default
    return str(value).casefold() in ('1', 'true', 'on', 'yes')


def blueprint(service):
    bp = Blueprint('salesforce_sandbox', __name__)

    @bp.get('/salesforce-sandbox')
    def page():
        target = request.args.get('org', '')
        if len(target) > 254:
            target = ''
        snapshot = service.portal(target)
        return render_template('salesforce_sandbox.html', snapshot=snapshot)

    @bp.get('/salesforce-sandbox/mod-sheet')
    def mod_sheet():
        target = request.args.get('org', '')
        if len(target) > 254:
            target = ''
        snapshot = service.generate(
            target,
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
        return render_template('salesforce_mod_sheet.html', snapshot=snapshot), 400 if snapshot.error else 200

    return bp
