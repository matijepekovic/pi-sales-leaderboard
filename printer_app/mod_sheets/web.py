"""HTTP boundary for permanent daily MOD Sheet settings."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, g, redirect, render_template, request, url_for

from .policy import ModSheetAutomationSettings


def _checked(name: str) -> bool:
    return request.form.get(name) == '1'


def blueprint(service):
    bp = Blueprint('mod_sheets', __name__)

    @bp.route('/mod-sheets/settings', methods=['GET', 'POST'])
    def settings_page():
        timezone = g.printer_config.timezone
        if request.method == 'POST':
            settings = ModSheetAutomationSettings(
                market_segment=request.form.get('marketsegment', '').strip(),
                product_category=request.form.get('productCategory', 'All').strip() or 'All',
                source_type=request.form.get('sourceType', 'All').strip() or 'All',
                remove_canceled=_checked('removeCanceled'),
                remove_unconfirmed=_checked('removeUnconfirmed'),
                color_code=_checked('colorCode'),
            )
            service.save(settings)
            return redirect(url_for('mod_sheets.settings_page'), code=303)

        snapshot = service.snapshot(timezone)
        today = datetime.now(ZoneInfo(timezone)).strftime('%-m/%-d/%Y')
        return render_template(
            'mod_sheet_settings.html',
            snapshot=snapshot,
            today=today,
        )

    return bp
