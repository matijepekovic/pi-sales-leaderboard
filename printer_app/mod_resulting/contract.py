"""Normalized MOD resulting inputs. No Salesforce field names belong here."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

DISPOSITIONS = ('', 'sale', 'pns', 'np', 'cxl', 'nra', 'oos')
PRODUCT_RESULTS = ('sale', 'pns', 'np', 'cxl', 'nra', 'oos')
RESULT_DETAILS = (
    '3rd Party Influence', 'Cancel in contracts', 'Health/Safety Concerns',
    'Leftover/Missing Redline', 'Never Confirmed', 'Non-Homeowners',
    'Not Home', 'Not Interested', 'Other Estimates', 'Out of Scope',
    'Porched', 'Price Objection', 'Procrastination', 'Repair Only',
)
CHECKBOXES = (
    'docs', 'bid_sheets', 'pictures', 'promotion', 'one_leg',
    'free_lead', 'power_questions', 't_close', 'ninety_min',
    'dnr', 'cxl_at_lead', 'additional_products',
)
TEXT_FIELDS = (
    'numbers', 'notes', 'redlines', 'call_1', 'call_2', 'need', 'want',
    'result_detail', 'dnr_reason', 'dispo',
)
MAX_LENGTHS = {
    'numbers': 1800, 'notes': 4500, 'redlines': 4500,
    'call_1': 8, 'call_2': 8, 'need': 1000, 'want': 1000,
    'result_detail': 120, 'dnr_reason': 160, 'dispo': 8,
}
TIME_RE = re.compile(r'^(?:0?[1-9]|1[0-2]):[0-5][0-9] (?:AM|PM)$')
_NUMBER_RE = re.compile(r'^\$?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?$')


def clean_draft(raw):
    if not isinstance(raw, dict):
        raise ValueError('Invalid MOD draft.')
    if set(raw) - set(TEXT_FIELDS) - set(CHECKBOXES) - {'product_results'}:
        raise ValueError('Unknown MOD draft fields.')
    data = {}
    for key in TEXT_FIELDS:
        value = raw.get(key, '')
        if not isinstance(value, str) or len(value) > MAX_LENGTHS[key]:
            raise ValueError(key + ' exceeds the allowed text length.')
        data[key] = value.strip() if key not in ('notes', 'redlines', 'numbers') else value
    for key in CHECKBOXES:
        value = raw.get(key, False)
        if type(value) is not bool:
            raise ValueError(key + ' must be a checkbox.')
        data[key] = value
    if data['dispo'] not in DISPOSITIONS:
        raise ValueError('Choose a valid disposition.')
    if data['result_detail'] and data['result_detail'] not in RESULT_DETAILS:
        raise ValueError('Choose a valid Result Detail.')
    if data['dnr_reason'] and not data['dnr']:
        raise ValueError('DNR Reason requires DNR.')
    for key in ('call_1', 'call_2'):
        if data[key] and not TIME_RE.fullmatch(data[key]):
            raise ValueError(key + ' must be entered with AM or PM.')
    product_results = raw.get('product_results', {})
    if not isinstance(product_results, dict) or len(product_results) > 12:
        raise ValueError('Invalid additional product results.')
    normalized = {}
    for product, info in product_results.items():
        if not isinstance(product, str) or not 0 < len(product) <= 60 or not isinstance(info, dict):
            raise ValueError('Invalid product selection.')
        outcome = info.get('result', '')
        detail = info.get('detail', '')
        if outcome not in PRODUCT_RESULTS or detail not in ('', *RESULT_DETAILS):
            raise ValueError('Invalid product result.')
        normalized[product] = {'result': outcome, 'detail': detail}
    data['product_results'] = normalized
    return data


def prices(numbers):
    """Only full numeric lines count; text and fragments are never guessed."""
    result = []
    for line in str(numbers or '').splitlines():
        value = line.strip()
        if not value:
            continue
        if not _NUMBER_RE.fullmatch(value):
            continue
        try:
            number = Decimal(value.replace('$', '').replace(',', '').strip())
        except InvalidOperation:
            continue
        if number.is_finite() and number >= 0:
            result.append(number)
    return {
        'highest': str(max(result)) if result else '',
        'lowest': str(min(result)) if result else '',
    }


def outcome_fields(draft):
    """Lead result is derived, never requested as another UI dropdown."""
    dispo = draft['dispo']
    if not dispo:
        return None
    lead = {
        'sale': 'Sale Pending', 'pns': 'Nurturing',
        'np': 'Nurturing', 'cxl': 'Canceled',
        'nra': 'Nurturing', 'oos': 'Out of Scope',
    }[dispo]
    if draft['dnr']:
        if not draft['dnr_reason'].strip():
            raise ValueError('Choose a DNR Reason.')
        lead = 'Do Not Call'
    return {
        'lead_status': lead,
        'appointment_status': 'No Rep Available' if dispo == 'nra' else (
            'Canceled' if dispo in ('cxl', 'oos') else 'Completed'
        ),
        # Work Order Status is deliberately not guessed for NRA/OOS.
        'work_order_status': 'Canceled' if dispo in ('cxl', 'oos') else 'Completed'
        if dispo in ('sale', 'pns', 'np') else '',
        'previous_result': {'pns': 'Pitch No Sale', 'np': 'No Pitch',
                            'nra': 'No Rep Available'}.get(dispo, ''),
        'price': prices(draft['numbers']),
    }
