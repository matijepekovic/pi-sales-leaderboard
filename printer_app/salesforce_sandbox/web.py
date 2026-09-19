"""HTTP boundary for the isolated Salesforce Sandbox tab."""
from flask import Blueprint, render_template, request


def blueprint(service):
    bp = Blueprint('salesforce_sandbox', __name__)

    @bp.get('/salesforce-sandbox')
    def page():
        target = request.args.get('org', '')
        if len(target) > 254:
            target = ''
        snapshot = service.snapshot(target)
        return render_template('salesforce_sandbox.html', snapshot=snapshot)

    return bp
