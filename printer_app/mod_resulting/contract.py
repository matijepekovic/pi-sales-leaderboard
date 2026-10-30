"""Normalized MOD resulting inputs. No Salesforce field names belong here."""
from __future__ import annotations

from datetime import date
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
# Normalized, source-backed checkbox keys. Source-specific field identifiers
# and allowed input types belong exclusively to the Salesforce adapter.
SOURCE_CHECKBOXES = frozenset((
    'docs', 'ninety_min', 'promotion', 'review', 'dnr', 'one_leg',
    'free_lead', 'cxl_at_lead',
))
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
    'primary_product': 80, 'lead_status': 120, 'previous_result': 120,
    'start_price_override': 30, 'final_price_override': 30,
    'deposit_override': 30,
}
TIME_RE = re.compile(r'^(?:0?[1-9]|1[0-2]):[0-5][0-9] (?:AM|PM)$')
_NUMBER_RE = re.compile(r'^\$?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?$')
# Numbers may be annotated with letters; use complete amount tokens instead
# of requiring a line to contain only an amount. Never combine separated
# numbers into one value or accept a fractional fragment of 12.345.
_NUMBER_TOKEN_RE = re.compile(
    r'(?<![\d.,-])\$?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?(?![\d.]|,\d)'
)


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
    if set(raw) - set(TEXT_FIELDS) - set(CHECKBOXES) - {'product_results', 'sale_products', 'note_runs', 'checkbox_values'}:
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
    # Store the exact source scalar separately from its visual checkmark. An
    # unedited original is never replaced with a guessed "Yes" on Override.
    source_values = raw.get('checkbox_values', {})
    if not isinstance(source_values, dict) or set(source_values) - SOURCE_CHECKBOXES:
        raise ValueError('Invalid source checkbox values.')
    normalized_values = {}
    for key, entry in source_values.items():
        if (not isinstance(entry, dict) or set(entry) != {'value', 'edited'}
                or type(entry['edited']) is not bool):
            raise ValueError('Invalid source checkbox value.')
        value = entry['value']
        if value is not None and type(value) is not bool and (
            not isinstance(value, str) or len(value) > 3000
        ):
            raise ValueError('Invalid source checkbox value.')
        normalized_values[key] = {'value': value, 'edited': entry['edited']}
    data['checkbox_values'] = normalized_values
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
    # Start and Final remain numeric; Deposit/Payment is one text-compatible
    # value with an optional slash, as on the Salesforce Work Order.
    for field in ('start_price_override', 'final_price_override'):
        if data[field]:
            _money(data[field])
    data['deposit_override'] = deposit_payment_value(data['deposit_override'])
    # Lead-status selections are validated against actual Salesforce picklists
    # in the adapter before any write; empty means use the Dispo default.
    # Salesforce can have DNR checked with no reason. Preserve the actual
    # source checkbox; the editor still asks for a reason before a new write.
    data['dnr_reason'] = ';'.join(dnr_reasons(data['dnr_reason']))
    if not data['dnr']:
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


def product_result_context(draft, results, *, lead_appointment_date, resulted_on):
    """Plan primary/additional identities and date sources without vendor fields.

    Existing Result Appointment Flow: the first selected product is the
    primary issued lead, other selected products are additional (not issued).
    Canceled primary outcomes do not count as issued. The primary result uses
    today's date only for an appointment dated today; historical results use
    the Lead's date. The future/other Flow path copies the existing PIR input
    date and must be resolved by the source adapter during write preflight.

    Missing source dates or an unselected multi-product primary remain
    explicitly unresolved. Phase 3 must not write those fields by guessing.
    """
    try:
        submitted = date.fromisoformat(resulted_on)
    except (TypeError, ValueError) as exc:
        raise ValueError('The resulting date must be an ISO calendar date.') from exc
    lead_day = None
    if lead_appointment_date:
        try:
            lead_day = date.fromisoformat(lead_appointment_date)
        except (TypeError, ValueError) as exc:
            raise ValueError('The Lead appointment date is invalid. Refresh Salesforce.') from exc

    canonical = {}
    for result in results:
        product = result['product']
        key = product.casefold()
        if key in canonical:
            raise ValueError('A product cannot have two resulting entries.')
        canonical[key] = product

    selected = draft.get('primary_product', '').strip()
    if selected and selected.casefold() not in canonical:
        raise ValueError('The primary product must be one of the resulted products.')
    primary = (canonical[selected.casefold()] if selected else
               results[0]['product'] if len(results) == 1 else '')
    planned = {}
    for result in results:
        product = result['product']
        is_primary = bool(primary) and product.casefold() == primary.casefold()
        # An explicit choice is required for multi-product writes in Phase 3;
        # do not silently treat list order as a business decision.
        role = ('primary' if is_primary else
                'additional' if primary else 'unresolved')
        if lead_day is None:
            source, appointment_day = 'unresolved', ''
        elif is_primary and lead_day == submitted:
            source, appointment_day = 'today', submitted.isoformat()
        elif is_primary and lead_day > submitted:
            source, appointment_day = 'existing_result_input', ''
        else:
            source, appointment_day = 'lead', lead_day.isoformat()

        planned[product] = {
            'role': role,
            'counts_as_issued_lead': (is_primary and result['result'] not in ('cxl', 'oos')
                                      if primary else None),
            'appointment_date_source': source,
            'appointment_date': appointment_day,
        }
    return planned


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


def deposit_payment_value(value):
    """Validate a manual Salesforce-compatible Deposit/Payment text entry.

    A deposit-only number is supported for existing drafts. A slash separates
    the deposit and payment, and an empty payment is allowed for cash sales.
    """
    text = '' if value is None else str(value).strip()
    if not text:
        return ''
    if '$' in text:
        raise ValueError('Deposit/Payment does not use dollar signs.')
    parts = text.split('/')
    if len(parts) > 2 or not parts[0].strip():
        raise ValueError('Deposit/Payment must be a deposit or deposit/payment.')
    for part in parts:
        if part.strip():
            _money(part.strip())
    return '/'.join(part.strip().replace(',', '') for part in parts)


def deposit_payment_text(draft):
    """The single Work Order Deposit/Payment value, manual or computed."""
    manual = deposit_payment_value(draft.get('deposit_override', ''))
    if manual:
        return manual
    sales = (sold_products(draft) if draft.get('dispo') == 'sale'
             else individual_product_sales(draft))
    if not sales:
        return ''
    def plain_amount(value):
        # Decimal(0) is a legitimate deposit. Convert explicitly rather
        # than allowing the generic money parser's falsey-value shortcut
        # to treat zero as a blank input.
        return format_money(str(value))[1:].replace(',', '')

    deposit = plain_amount(sum(
        (_money(item['deposit']) for item in sales), Decimal('0')))
    payments = [item['payment'] for item in sales if item['payment']]
    payment = plain_amount(sum(
        (_money(value) for value in payments), Decimal('0'))) if payments else ''
    return deposit + '/' + payment


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
    # Manual redlines live separately from black MOD Notes. Legacy mixed
    # runs remain part of the historical Notes text and are not duplicated.
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
    """Highest/lowest complete amounts, ignoring surrounding letters.

    Numbers is a dedicated numerical column. Annotations are allowed, but
    unrelated Notes and incomplete decimal fragments are never inspected.
    """
    result = []
    for line in str(numbers or '').splitlines():
        for match in _NUMBER_TOKEN_RE.finditer(line):
            value = match.group().replace('$', '').replace(',', '').strip()
            try:
                number = Decimal(value)
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
            'Do Not Call' if draft['dnr'] else
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
