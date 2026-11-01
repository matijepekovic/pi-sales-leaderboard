"""Normalize read-only Salesforce resulting rows into existing draft keys."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from .salesforce_adapter import (
    LEAD_FIELDS, PR, PR_ISSUED_COUNT, WO, REVIEW_FIELD, PRODUCT_RESULT_VALUE,
    WORK_ORDER_DISPO,
    ResultingSalesforceError,
)


def _money(value):
    if value is None or value == '':
        return ''
    original = str(value)
    try:
        result = Decimal(original)
    except (InvalidOperation, ValueError):
        return original
    if not result.is_finite() or result < 0 or result.as_tuple().exponent < -2:
        return original
    return format(result, 'f')


def _clock(value, zone):
    text = str(value or '').strip()
    if not text:
        return ''
    ampm = re.fullmatch(r'(0?[1-9]|1[0-2]):([0-5]\d) (AM|PM)', text)
    if ampm:
        return str(int(ampm[1])) + ':' + ampm[2] + ' ' + ampm[3]
    clock = re.fullmatch(r'([01]\d|2[0-3]):([0-5]\d)(?::[0-5]\d(?:\.\d+)?)?Z?', text)
    if clock:
        hour, minute = int(clock[1]), clock[2]
    else:
        try:
            stamp = text.replace('Z', '+00:00')
            if re.search(r'[+-]\d{4}$', stamp):
                stamp = stamp[:-5] + stamp[-5:-2] + ':' + stamp[-2:]
            parsed = datetime.fromisoformat(stamp)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(zone)
            hour, minute = parsed.hour, parsed.strftime('%M')
        except ValueError:
            return text
    return str(hour % 12 or 12) + ':' + str(minute).zfill(2) + (
        ' PM' if hour >= 12 else ' AM')


def _checked(value):
    """Project a source scalar to an indicator without discarding the source."""
    if value is None or value is False:
        return False
    if value is True:
        return True
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().casefold() not in (
            'false', 'no', '0', 'off', 'unchecked', 'none', 'null',
        )
    return bool(value)


def _source_value(value):
    """Keep the exact supported Salesforce scalar; never invent a yes/no label."""
    return value if value is None or isinstance(value, (str, bool)) else str(value)


def project_salesforce_drafts(zone, identities, works, leads, products):
    dispositions = {name.casefold(): key for key, name in WORK_ORDER_DISPO.items()}
    results = {name.casefold(): key for key, name in PRODUCT_RESULT_VALUE.items()
               if key != 'oos'}
    output = {}
    for work_id, lead_id in identities.items():
        work = works[work_id]
        raw_dispo = str(work.get(WO['dispo']) or '').strip()
        dispo = dispositions.get(raw_dispo.casefold(), raw_dispo)
        # Lead.Status is checked before trusting any Work Order or Product result.
        content = str(work.get(WO['notes']) or '')
        draft = {
            'dispo': dispo,
            # Salesforce has one MOD_Notes__c text field. Dispo only affects
            # its visual styling in the digital MOD sheet.
            'notes': content,
            'redlines': '',
            'call_1': _clock(work.get(WO['call_1']), zone),
            'call_2': _clock(work.get(WO['call_2']), zone),
            'need': str(work.get(WO['need']) or ''),
            'want': str(work.get(WO['want']) or ''),
            'checkbox_values': {},
        }
        for field in ('docs', 'ninety_min', 'promotion'):
            value = _source_value(work.get(WO[field]))
            draft['checkbox_values'][field] = {'value': value, 'edited': False}
            draft[field] = _checked(value)
        if REVIEW_FIELD in work:
            review = _source_value(work[REVIEW_FIELD])
            draft['checkbox_values']['review'] = {
                'value': review, 'edited': False,
            }
            draft['review'] = _checked(review)
        prices = [_money(work.get(WO[key])) for key in ('start_price', 'final_price')]
        draft['numbers'] = '\n'.join(price for price in prices if price)
        # This is an existing Salesforce text value, not a Stats manual edit.
        remote_deposit = work.get(WO['deposit'])
        draft['deposit_override'] = '' if remote_deposit is None else str(remote_deposit)
        if lead_id:
            lead = leads[lead_id]
            dnr = lead.get(LEAD_FIELDS['dnr'])
            one_leg = lead.get(LEAD_FIELDS['one_leg'])
            draft['checkbox_values']['dnr'] = {
                'value': _source_value(dnr), 'edited': False,
            }
            draft['checkbox_values']['one_leg'] = {
                'value': _source_value(one_leg), 'edited': False,
            }
            draft['dnr'] = _checked(dnr)
            draft['dnr_reason'] = str(lead.get(LEAD_FIELDS['dnr_reason']) or '')
            draft['one_leg'] = _checked(one_leg)
            # These are independent Salesforce fields, not conditional on
            # WorkOrder.Dispo__c being populated.
            draft['lead_status'] = str(lead.get(LEAD_FIELDS['status']) or '')
            draft['previous_result'] = str(
                lead.get(LEAD_FIELDS['previous_result']) or ''
            )
        lead_canceled = draft.get('lead_status', '').strip().casefold() == 'canceled'
        if lead_canceled:
            # The actual Salesforce Lead status wins even when the Work Order
            # has a contradictory Dispo or no existing product result.
            dispo = draft['dispo'] = 'cxl'
        # A source disposition outside the locally supported edit choices
        # remains the actual Salesforce text; it cannot invalidate Refresh.
        source_products = tuple(products.get(work_id, ()))
        source_keys = set()
        needs_full_source = False
        for item in source_products:
            product_key = str(item.get(PR['product']) or '').strip().casefold()
            if not product_key or product_key in source_keys:
                needs_full_source = True
            source_keys.add(product_key)
        if needs_full_source:
            # Store all identities where a product-keyed edit UI cannot
            # represent the full Salesforce record set without data loss.
            draft['source_product_records'] = [{
                'id': str(item.get('Id') or ''),
                'product': item.get(PR['product']),
                'result': item.get(PR['result']),
                'detail': item.get(PR['detail']),
                'price': item.get(PR['price']),
                'one_leg': item.get(PR['one_leg']),
                'free_lead': item.get(PR['free_lead']),
                'cxl_at_lead': item.get(PR['cxl_at_lead']),
            } for item in source_products]

        per_product, sales, details, seen = {}, {}, set(), set()
        ranked_results = []
        product_flags = {'free_lead': [], 'cxl_at_lead': []}
        issued_primary = []
        for item in source_products:
            product = str(item.get(PR['product']) or '').strip()
            if not product or product.casefold() in seen:
                # These records survive intact in source_product_records.
                continue
            seen.add(product.casefold())
            if item.get(PR_ISSUED_COUNT) is True:
                issued_primary.append(product)
            raw_result = str(item.get(PR['result']) or '').strip()
            result = results.get(raw_result.casefold(), raw_result)
            detail = str(item.get(PR['detail']) or '')
            if detail:
                details.add(detail)
            price = _money(item.get(PR['price']))
            if result:
                # When WorkOrder.Dispo__c is empty, choose the best-supported
                # product result. A price of zero is still a recorded value;
                # false checkboxes are not extra evidence. Never guess on
                # conflicting results with an equal amount of information.
                evidence = int(bool(detail.strip())) + int(
                    item.get(PR['price']) is not None
                ) + sum(
                    item.get(PR[key]) is True
                    for key in ('one_leg', 'free_lead', 'cxl_at_lead')
                )
                ranked_results.append((evidence, result, detail.strip()))
                per_product[product] = {
                    'result': result, 'detail': detail,
                    'price': price, 'deposit': '',
                }
            if result == 'sale' and price:
                try:
                    sold_price = Decimal(price)
                    positive_sale = sold_price.is_finite() and sold_price > 0
                except (InvalidOperation, ValueError):
                    positive_sale = True
                if positive_sale:
                    sales[product] = {'price': price, 'deposit': ''}
            for key in ('free_lead', 'cxl_at_lead'):
                value = _source_value(item.get(PR[key]))
                product_flags[key].append(value)
                if _checked(value):
                    draft[key] = True
        # Salesforce's issued-lead flag is authoritative on Refresh. More than
        # one flagged product is ambiguous; never choose a primary by order.
        if len(issued_primary) == 1:
            draft['primary_product'] = issued_primary[0]
        # When products disagree, show the values together rather than
        # guessing which one owns this sheet-level checkmark. Preserve every
        # original product checkbox by omitting it from Override writes until
        # the user deliberately edits that checkmark.
        for key, values in product_flags.items():
            if values:
                display = (
                    values[0] if all(value == values[0] for value in values)
                    else ' / '.join(
                        'Empty' if value is None else str(value)
                        for value in values
                    )
                )
                draft['checkbox_values'][key] = {
                    'value': display, 'edited': False,
                }
        # Product-specific explanations must never become the reason for a
        # Lead-authoritative CXL if their results contradict cancellation.
        chosen_details = set() if lead_canceled else details
        if not dispo and ranked_results:
            most_information = max(score for score, _, _ in ranked_results)
            leaders = [(result, detail) for score, result, detail in ranked_results
                       if score == most_information]
            contenders = {result for result, _ in leaders}
            if len(contenders) == 1:
                dispo = contenders.pop()
                draft['dispo'] = dispo
                # Main Result Detail belongs to the same winning product(s);
                # never attach a losing product's reason to the chosen Dispo.
                chosen_details = {detail for _, detail in leaders if detail}
            else:
                chosen_details = set()
        if len(chosen_details) == 1:
            draft['result_detail'] = next(iter(chosen_details))
        if per_product:
            # Preserve every product's actual Salesforce result, including
            # minority outcomes when the main Dispo is Sale.
            draft['additional_products'] = True
            draft['product_results'] = per_product
        if dispo == 'sale':
            # One sold product can be reconstructed from the Work Order total.
            # Multiple products cannot be split reliably from that total.
            total = draft['deposit_override']
            if len(sales) == 1 and total:
                parts = total.split('/', 1)
                sold = next(iter(sales.values()))
                sold['deposit'] = parts[0]
                if len(parts) == 2 and parts[1]:
                    sold['payment'] = parts[1]
            draft['sale_products'] = sales
        output[work_id] = draft
    return output
