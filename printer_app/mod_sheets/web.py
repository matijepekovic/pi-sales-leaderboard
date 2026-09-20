"""HTTP boundary for permanent and test MOD Sheet settings."""
from __future__ import annotations

from datetime import datetime
import re
import secrets
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from ..print_options import CHOICES, NUMBERS, PrintOptions
from .policy import ModSheetAutomationSettings


PRINT_CHOICES = {
    'paper': CHOICES['PRINT_PAPER'][2],
    'orientation': CHOICES['PRINT_ORIENTATION'][2],
    'color': CHOICES['PRINT_COLOR'][2],
    'sides': CHOICES['PRINT_SIDES'][2],
    'pdf_scaling': CHOICES['PDF_SCALING'][2],
}
COPY_RANGE = NUMBERS['PRINT_COPIES'][2:]


def _checked(name: str) -> bool:
    return request.form.get(name) == '1'


def _settings_from_form() -> ModSheetAutomationSettings:
    copies = request.form.get('printCopies', '1')
    if not copies.isascii() or not copies.isdecimal():
        raise ValueError('Copies must be a whole number.')
    print_options = PrintOptions(
        paper=request.form.get('printPaper', 'source'),
        orientation=request.form.get('printOrientation', 'source'),
        color=request.form.get('printColor', 'default'),
        sides=request.form.get('printSides', 'default'),
        copies=int(copies),
        pdf_scaling=request.form.get('pdfScaling', 'default'),
    )
    return ModSheetAutomationSettings(
        market_segment=request.form.get('marketsegment', '').strip(),
        product_category=request.form.get('productCategory', 'All').strip() or 'All',
        source_type=request.form.get('sourceType', 'All').strip() or 'All',
        remove_canceled=_checked('removeCanceled'),
        remove_unconfirmed=_checked('removeUnconfirmed'),
        color_code=_checked('colorCode'),
        print_options=print_options,
    )


def blueprint(settings_service, test_service):
    bp = Blueprint('mod_sheets', __name__)

    @bp.route('/mod-sheets/settings', methods=['GET', 'POST'])
    def settings_page():
        timezone = g.printer_config.timezone
        if request.method == 'POST':
            try:
                settings = _settings_from_form()
            except ValueError as exc:
                abort(400, str(exc))

            action = request.form.get('action', 'save')
            if action == 'save':
                settings_service.save(settings)
            elif action == 'test':
                token = request.form.get('testToken', '')
                if not re.fullmatch(r'[0-9a-f]{32}', token):
                    abort(400, 'Invalid test print token.')
                test_service.run(settings, timezone, token)
            else:
                abort(400, 'Unknown MOD Sheet action.')
            return redirect(url_for('mod_sheets.settings_page'), code=303)

        snapshot = settings_service.snapshot(timezone)
        today = datetime.now(ZoneInfo(timezone)).strftime('%-m/%-d/%Y')
        return render_template(
            'mod_sheet_settings.html',
            snapshot=snapshot,
            today=today,
            print_choices=PRINT_CHOICES,
            copy_range=COPY_RANGE,
            test_token=secrets.token_hex(16),
        )

    return bp
