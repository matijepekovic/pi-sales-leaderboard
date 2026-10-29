"""Normalize read-only Salesforce resulting rows into existing draft keys."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from .contract import deposit_payment_value

from .salesforce_adapter import (
    LEAD_FIELDS, PR, WO, PRODUCT_RESULT_VALUE, WORK_ORDER_DISPO,
    ResultingSalesforceError,
)


def _money(value):
    if value is None or value == '':
        return ''
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ResultingSalesforceError('Invalid Salesforce resulting amount.') from exc
    if not result.is_finite() or result < 0 or result.as_tuple().exponent < -2:
        raise ResultingSalesforceError('Invalid Salesforce resulting amount.')
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
        except ValueError as exc:
            raise ResultingSalesforceError('Invalid Salesforce call time.') from exc
    return str(hour % 12 or 12) + ':' + str(minute).zfill(2) + (
        ' PM' if hour >= 12 else ' AM')


def project_salesforce_drafts(zone, identities, works, leads, products):
    dispositions = {name.casefold(): key for key, name in WORK_ORDER_DISPO.items()}
    results = {name.casefold(): key for key, name in PRODUCT_RESULT_VALUE.items()
               if key != 'oos'}
    output = {}
    for work_id, lead_id in identities.items():
        work = works[work_id]
        raw_dispo = str(work.get(WO['dispo']) or '').strip()
        dispo = dispositions.get(raw_dispo.casefold(), '')
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
        }
        for field in ('docs', 'ninety_min', 'promotion'):
            value = work.get(WO[field])
            if value is not None and not isinstance(value, bool):
                raise ResultingSalesforceError('Invalid Salesforce checkbox value.')
            draft[field] = value is True
        prices = [_money(work.get(WO[key])) for key in ('start_price', 'final_price')]
        draft['numbers'] = '\n'.join(price for price in prices if price)
        # Salesforce's existing Deposit/Payment field is text and can contain
        # both amounts separated by '/'. Preserve it exactly as a manual value.
        try:
            draft['deposit_override'] = deposit_payment_value(work.get(WO['deposit']))
        except ValueError as exc:
            raise ResultingSalesforceError('Invalid Salesforce Deposit/Payment.') from exc
        if lead_id:
            lead = leads[lead_id]
            dnr = lead.get(LEAD_FIELDS['dnr'])
            one_leg = lead.get(LEAD_FIELDS['one_leg'])
            if (dnr is not None and not isinstance(dnr, bool)) or (
                one_leg is not None and not isinstance(one_leg, bool)
            ):
                raise ResultingSalesforceError('Invalid Salesforce Lead checkbox.')
            draft['dnr'] = dnr is True
            draft['dnr_reason'] = str(lead.get(LEAD_FIELDS['dnr_reason']) or '')
            draft['one_leg'] = one_leg is True
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
        elif raw_dispo and not dispo:
            raise ResultingSalesforceError('Unknown Salesforce Work Order disposition.')

        per_product, sales, details, seen = {}, {}, set()
        ranked_results = []
        for item in products.get(work_id, ()):
            product = str(item.get(PR['product']) or '').strip()
            if not product:
                continue
            if product.casefold() in seen:
                raise ResultingSalesforceError('Duplicate Salesforce product result.')
            seen.add(product.casefold())
            raw_result = str(item.get(PR['result']) or '').strip()
            result = results.get(raw_result.casefold(), '')
            if raw_result and not result:
                if lead_canceled:
                    # An unrecognized product result cannot veto a canceled
                    # Lead; leave that product untouched rather than guess.
                    continue
                raise ResultingSalesforceError('Unknown Salesforce product result.')
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
            if result == 'sale' and price and Decimal(price) > 0:
                sales[product] = {'price': price, 'deposit': ''}
            for key in ('free_lead', 'cxl_at_lead'):
                if item.get(PR[key]) is True:
                    draft[key] = True
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
