"""Normalize read-only Salesforce resulting rows into existing draft keys."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

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
        if raw_dispo and not dispo:
            raise ResultingSalesforceError('Unknown Salesforce Work Order disposition.')
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
        # Preserve the actual Work Order deposit even for multiple sold products:
        # individual product deposits cannot be reconstructed from a total.
        draft['deposit_override'] = _money(work.get(WO['deposit']))
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
            if dispo:
                draft['lead_status'] = str(lead.get(LEAD_FIELDS['status']) or '')
                draft['previous_result'] = str(
                    lead.get(LEAD_FIELDS['previous_result']) or ''
                )

        per_product, sales, details, seen = {}, {}, set(), set()
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
                raise ResultingSalesforceError('Unknown Salesforce product result.')
            detail = str(item.get(PR['detail']) or '')
            if detail:
                details.add(detail)
            price = _money(item.get(PR['price']))
            if result:
                per_product[product] = {
                    'result': result, 'detail': detail,
                    'price': price, 'deposit': '',
                }
            if result == 'sale' and price and Decimal(price) > 0:
                sales[product] = {'price': price, 'deposit': ''}
            for key in ('free_lead', 'cxl_at_lead'):
                if item.get(PR[key]) is True:
                    draft[key] = True
        if len(details) == 1:
            draft['result_detail'] = next(iter(details))
        if dispo == 'sale':
            total = _money(work.get(WO['deposit']))
            if len(sales) == 1 and total:
                next(iter(sales.values()))['deposit'] = total
            draft['sale_products'] = sales
        elif per_product:
            draft['additional_products'] = True
            draft['product_results'] = per_product
        output[work_id] = draft
    return output
