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
    'lead_status', 'previous_result', 'start_price_override',
    'final_price_override', 'deposit_override',
)
MAX_LENGTHS = {
    # One MOD Notes text can contain both halves of a legacy split draft.
    'numbers': 1800, 'notes': 9000, 'redlines': 4500,
    'call_1': 8, 'call_2': 8, 'need': 1000, 'want': 1000,
    'result_detail': 120, 'dnr_reason': 500, 'dispo': 8,
    'primary_product': 60, 'lead_status': 120, 'previous_result': 120,
    'start_price_override': 30, 'final_price_override': 30,
    'deposit_override': 30,
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
    if set(raw) - set(TEXT_FIELDS) - set(CHECKBOXES) - {'product_results', 'sale_products', 'note_runs'}:
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
    runs = raw.get('note_runs', [])
    if not isinstance(runs, list) or len(runs) > 256:
        raise ValueError('Invalid MOD Notes formatting.')
    normalized_runs = []
    for run in runs:
        if (not isinstance(run, dict) or set(run) != {'text', 'red'}
                or not isinstance(run['text'], str) or type(run['red']) is not bool):
            raise ValueError('Invalid MOD Notes formatting.')
        if not run['text']:
            continue
        if normalized_runs and normalized_runs[-1]['red'] == run['red']:
            normalized_runs[-1]['text'] += run['text']
        else:
            normalized_runs.append({'text': run['text'], 'red': run['red']})
    if normalized_runs and ''.join(item['text'] for item in normalized_runs) != data['notes']:
        raise ValueError('MOD Notes formatting does not match its text.')
    data['note_runs'] = normalized_runs
    if data['dispo'] not in DISPOSITIONS:
        raise ValueError('Choose a valid disposition.')
    # Explicit amount overrides are optional. Without one, the numeric notes
    # column (or sold-product deposit sum) retains the current behavior.
    for field in ('start_price_override', 'final_price_override', 'deposit_override'):
        if data[field]:
            _money(data[field])
    # Lead-status selections are validated against actual Salesforce picklists
    # in the adapter before any write; empty means use the Dispo default.
    # DNR only applies when at least one reason is actually selected.
    # A checked box with no reasons is an unchecked DNR, not Do Not Call.
    data['dnr_reason'] = ';'.join(dnr_reasons(data['dnr_reason']))
    if not data['dnr'] or not data['dnr_reason']:
        data['dnr'] = False
        data['dnr_reason'] = ''
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
        payment = info.get('payment', '')
        if (outcome not in PRODUCT_RESULTS or not isinstance(detail, str)
                or len(detail) > 120 or not isinstance(price, str)
                or not isinstance(deposit, str) or not isinstance(payment, str)
                or len(price) > 30 or len(deposit) > 30
                or len(payment) > 30):
            raise ValueError('Invalid product result.')
        for amount in (price, deposit, payment):
            if amount.strip():
                _money(amount)
        normalized[product.strip()] = {
            'result': outcome, 'detail': detail.strip(),
            'price': price.strip(), 'deposit': deposit.strip(),
            **({'payment': payment.strip()} if 'payment' in info else {}),
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
        payment = info.get('payment', '')
        if not all(isinstance(amount, str) for amount in (price, deposit, payment)):
            raise ValueError('Sale price, deposit and payment must be entered as text values.')
        if any(len(amount) > 30 for amount in (price, deposit, payment)):
            raise ValueError('Sale amount exceeds the allowed length.')
        # Zero-priced selected products stay unresulted. Payment is optional,
        # including for cash sales, and never becomes a Salesforce amount field.
        for amount in (price, deposit, payment):
            if amount.strip():
                _money(amount)
        sales[product.strip()] = {
            'price': price.strip(), 'deposit': deposit.strip(),
            **({'payment': payment.strip()} if 'payment' in info else {}),
        }
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
            'payment': money_text(info.get('payment', '')),
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
                'payment': money_text(entry.get('payment', '')),
            })
    return tuple(sold)


def sale_amount_totals(draft):
    """Combined sold-product amounts for the MOD Deposit/Payment display."""
    sales = (sold_products(draft) if draft.get('dispo') == 'sale'
             else individual_product_sales(draft))
    if not sales:
        return {'deposit': '', 'payment': ''}
    deposit = sum((Decimal(item['deposit']) for item in sales), Decimal('0'))
    payments = [
        Decimal(item['payment']) for item in sales if item.get('payment')
    ]
    return {
        'deposit': money_text(str(deposit)),
        'payment': money_text(str(sum(payments, Decimal('0')))) if payments else '',
    }


def deposit_payment_text(draft):
    """Display Deposit/Payment without currency symbols; keep legacy override."""
    totals = sale_amount_totals(draft)
    deposit = (
        money_text(draft['deposit_override'])
        if draft.get('deposit_override') else totals['deposit']
    )
    if totals['deposit'] != '' or totals['payment'] != '':
        return deposit + '/' + totals['payment']
    return deposit


def sale_redlines(draft):
    sales = (sold_products(draft) if draft.get('dispo') == 'sale'
             else individual_product_sales(draft))
    return tuple(
        'SALE ' + item['product'] + ': ' + format_money(item['price'])
        + ' | Deposit: ' + format_money(item['deposit'])
        + (' | Payment: ' + format_money(item['payment'])
           if item['payment'] else '')
        for item in sales
    )


def note_runs_for_display(draft):
    """One MOD Notes editor with per-entry ink; keep old split drafts readable."""
    stored = draft.get('note_runs') or []
    if stored:
        runs = [dict(text=part['text'], red=part['red']) for part in stored]
    else:
        notes = str(draft.get('notes') or '')
        runs = [{'text': notes, 'red': False}] if notes else []
    legacy = str(draft.get('redlines') or '')
    if legacy:
        if runs:
            runs.append({'text': '\n', 'red': False})
        runs.append({'text': legacy, 'red': True})
    return runs


def user_redline_text(draft):
    """Only user characters entered as red ink, not the earlier black notes."""
    return '\n'.join(part['text'].strip() for part in note_runs_for_display(draft)
                     if part['red'] and part['text'].strip())


def result_detail_redlines(draft):
    result = []
    detail = str(draft.get('result_detail') or '').strip()
    if detail:
        result.append(detail)
    if draft.get('additional_products') and draft.get('dispo') != 'sale':
        for product, info in (draft.get('product_results') or {}).items():
            choice = str(info.get('detail') or '').strip()
            if choice:
                result.append(choice)
    return tuple(result)


def final_redline_text(draft):
    # Historical drafts have a separate redlines key. New red characters
    # already belong to notes and must not be appended a second time.
    lines = [line for line in str(draft.get('redlines') or '').splitlines() if line.strip()]
    lines.extend(result_detail_redlines(draft))
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
        # The current Lead Status is strictly derived from today's Dispo and
        # DNR. Old manually edited draft fields remain accepted for backward
        # compatibility, but can never override the authoritative outcome.
        'lead_status': (
            'Do Not Call' if draft['dnr'] and draft['dnr_reason'] else
            {'sale':'Sale Pending', 'pns':'Nurturing',
             'np':'Nurturing', 'cxl':'Canceled',
             'nra':'Nurturing', 'oos':'Out of Scope'}[dispo]
        ),
        'appointment_status': 'No Rep Available' if dispo == 'nra' else (
            'Canceled' if dispo in ('cxl', 'oos') else 'Completed'
        ),
        'work_order_status': 'Canceled' if dispo in ('cxl', 'oos') else 'Completed',
        'price': {
            'highest': draft['start_price_override'] or prices(draft['numbers'])['highest'],
            'lowest': draft['final_price_override'] or prices(draft['numbers'])['lowest'],
        },
    }
