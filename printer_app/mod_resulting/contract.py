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
    'docs', 'bid_sheets', 'pictures', 'promotion', 'review', 'one_leg',
    'free_lead', 'power_questions', 't_close', 'ninety_min',
    'dnr', 'cxl_at_lead', 'additional_products',
)
TEXT_FIELDS = (
    'numbers', 'notes', 'redlines', 'call_1', 'call_2', 'need', 'want',
    'result_detail', 'dnr_reason', 'dispo', 'primary_product',
)
MAX_LENGTHS = {
    # One MOD Notes text can contain both halves of a legacy split draft.
    'numbers': 1800, 'notes': 9000, 'redlines': 4500,
    'call_1': 8, 'call_2': 8, 'need': 1000, 'want': 1000,
    'result_detail': 120, 'dnr_reason': 500, 'dispo': 8,
    'primary_product': 60,
}
TIME_RE = re.compile(r'^(?:0?[1-9]|1[0-2]):[0-5][0-9] (?:AM|PM)$')
_NUMBER_RE = re.compile(r'^\$?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?$')


def _money(value, *, allow_blank=True):
    value = str(value or '').strip()
    if not value:
        if allow_blank:
            return None
        raise ValueError('A money value is required.')
    if not _NUMBER_RE.fullmatch(value):
        raise ValueError('Money values must be non-negative numbers with at most two decimals.')
    try:
        number = Decimal(value.replace('$', '').replace(',', '').strip())
    except InvalidOperation as exc:
        raise ValueError('Invalid money value.') from exc
    if not number.is_finite() or number < 0:
        raise ValueError('Money values must be non-negative.')
    return number


def money_text(value):
    number = _money(value)
    if number is None:
        return ''
    text = format(number, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def format_money(value):
    number = _money(value, allow_blank=False)
    whole, dot, fraction = f'{number:.2f}'.partition('.')
    grouped = f'{int(whole):,}'
    if fraction == '00':
        return '$' + grouped
    return '$' + grouped + '.' + fraction


def dnr_reasons(value):
    seen = set()
    result = []
    for part in str(value or '').split(';'):
        clean = part.strip()
        key = clean.casefold()
        if clean and key not in seen:
            result.append(clean)
            seen.add(key)
    return tuple(result)


def clean_draft(raw):
    if not isinstance(raw, dict):
        raise ValueError('Invalid MOD draft.')
    if set(raw) - set(TEXT_FIELDS) - set(CHECKBOXES) - {'product_results', 'sale_products'}:
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
    if not data['dnr']:
        data['dnr_reason'] = ''
    else:
        data['dnr_reason'] = ';'.join(dnr_reasons(data['dnr_reason']))
    for key in ('call_1', 'call_2'):
        if data[key] and not TIME_RE.fullmatch(data[key]):
            raise ValueError(key + ' must be entered with AM or PM.')

    product_results = raw.get('product_results', {})
    if not isinstance(product_results, dict) or len(product_results) > 24:
        raise ValueError('Invalid additional product results.')
    normalized = {}
    for product, info in product_results.items():
        if not isinstance(product, str) or not 0 < len(product.strip()) <= 80 or not isinstance(info, dict):
            raise ValueError('Invalid product selection.')
        outcome = info.get('result', '')
        detail = info.get('detail', '')
        price = info.get('price', '')
        deposit = info.get('deposit', '')
        if (outcome not in PRODUCT_RESULTS or not isinstance(detail, str)
                or len(detail) > 120 or not isinstance(price, str)
                or not isinstance(deposit, str) or len(price) > 30
                or len(deposit) > 30):
            raise ValueError('Invalid product result.')
        if price.strip():
            _money(price)
        if deposit.strip():
            _money(deposit)
        normalized[product.strip()] = {
            'result': outcome, 'detail': detail.strip(),
            'price': price.strip(), 'deposit': deposit.strip(),
        }
    data['product_results'] = normalized

    sale_products = raw.get('sale_products', {})
    if not isinstance(sale_products, dict) or len(sale_products) > 40:
        raise ValueError('Invalid sold product selection.')
    sales = {}
    for product, info in sale_products.items():
        if not isinstance(product, str) or not 0 < len(product.strip()) <= 80 or not isinstance(info, dict):
            raise ValueError('Invalid sold product selection.')
        price = info.get('price', '')
        deposit = info.get('deposit', '')
        if not isinstance(price, str) or not isinstance(deposit, str):
            raise ValueError('Sale price and deposit must be entered as text values.')
        if len(price) > 30 or len(deposit) > 30:
            raise ValueError('Sale price or deposit is too long.')
        # Validate entered values now; selection with price zero is retained in
        # the draft but later treated as not sold by the workflow.
        if price.strip():
            _money(price)
        if deposit.strip():
            _money(deposit)
        sales[product.strip()] = {'price': price.strip(), 'deposit': deposit.strip()}
    data['sale_products'] = sales
    return data


def dnr_redline(reason):
    values = dnr_reasons(reason)
    return 'DNR - ' + '; '.join(values) if values else ''


def sold_products(draft):
    """Return only selected sale products with a strictly positive price."""
    result = []
    for product, info in draft.get('sale_products', {}).items():
        price = _money(info.get('price', ''))
        if price is None or price == 0:
            continue
        deposit = _money(info.get('deposit', ''))
        if deposit is None:
            raise ValueError('Enter a deposit for sold product ' + product + ' (0 is valid).')
        result.append({
            'product': product,
            'price': money_text(info['price']),
            'deposit': money_text(info['deposit']),
        })
    return tuple(result)


def individual_product_sales(draft):
    """Explicit individual Sale results never change the main disposition."""
    sold = []
    if draft.get('additional_products') and draft.get('dispo') != 'sale':
        for product, entry in draft.get('product_results', {}).items():
            if entry['result'] != 'sale':
                continue
            price = _money(entry.get('price', ''))
            if price is None or price == 0:
                continue
            deposit = _money(entry.get('deposit', ''))
            if deposit is None:
                raise ValueError('Enter a deposit for sold product ' + product + ' (0 is valid).')
            sold.append({
                'product': product,
                'price': money_text(entry['price']),
                'deposit': money_text(entry['deposit']),
            })
    return tuple(sold)


def sale_redlines(draft):
    sales = (sold_products(draft) if draft.get('dispo') == 'sale'
             else individual_product_sales(draft))
    return tuple(
        'SALE ' + item['product'] + ': ' + format_money(item['price'])
        + ' | Deposit: ' + format_money(item['deposit'])
        for item in sales
    )


def final_redline_text(draft):
    lines = [line for line in str(draft.get('redlines') or '').splitlines() if line.strip()]
    if draft.get('dnr') and draft.get('dnr_reason'):
        lines.append(dnr_redline(draft['dnr_reason']))
    lines.extend(sale_redlines(draft))
    result = []
    seen = set()
    for line in lines:
        key = line.strip().casefold()
        if key and key not in seen:
            result.append(line.strip())
            seen.add(key)
    return '\n'.join(result)


def prices(numbers):
    """Only full numeric lines count; text and fragments are never guessed."""
    result = []
    for line in str(numbers or '').splitlines():
        value = line.strip()
        if not value or not _NUMBER_RE.fullmatch(value):
            continue
        try:
            number = Decimal(value.replace('$', '').replace(',', '').strip())
        except InvalidOperation:
            continue
        if number.is_finite() and number >= 0:
            result.append(number)
    return {
        'highest': money_text(str(max(result))) if result else '',
        'lowest': money_text(str(min(result))) if result else '',
    }


def outcome_fields(draft):
    """Derive the normalized result fields from the authoritative main Dispo."""
    dispo = draft['dispo']
    if not dispo:
        return None
    return {
        'lead_status': {
            'sale': 'Sale Pending', 'pns': 'Nurturing',
            'np': 'Nurturing', 'cxl': 'Canceled',
            'nra': 'Nurturing', 'oos': 'Out of Scope',
        }[dispo],
        'appointment_status': 'No Rep Available' if dispo == 'nra' else (
            'Canceled' if dispo in ('cxl', 'oos') else 'Completed'
        ),
        'work_order_status': 'Canceled' if dispo in ('cxl', 'oos') else 'Completed',
        'previous_result': {
            'pns': 'Pitch No Sale', 'np': 'No Pitch',
            'nra': 'No Rep Available',
        }.get(dispo, ''),
        'price': prices(draft['numbers']),
    }
