"""Read-only, exact-field Salesforce hydration of daily MOD resulting sheets.

The application never constructs SOQL itself and never writes during Refresh.
"""
from .salesforce_adapter import (
    ID_RE, LEAD, LEAD_FIELDS, PR, PRODUCT_RESULT, WORK_ORDER, WO, WO_LEAD,
    ResultingSalesforceError, _require_id, _soql,
)
from .salesforce_drafts import project_salesforce_drafts


def read_result_drafts(adapter, records):
    records = tuple(records)
    if not records:
        return {}
    identities = {
        _require_id(record.source_id): str(record.lead_source_id or '')
        for record in records
    }
    works, leads, products = {}, {}, {}
    work_keys = sorted(identities)
    for offset in range(0, len(work_keys), 40):
        batch = work_keys[offset:offset + 40]
        ids = ','.join(_soql(key) for key in batch)
        for item in adapter._query(
            'SELECT Id,' + ','.join(WO.values()) + ',' + WO_LEAD
            + ' FROM ' + WORK_ORDER
            + ' WHERE Id IN (' + ids + ') ORDER BY Id LIMIT 2000'
        ):
            key = _require_id(str(item.get('Id') or ''))
            if key not in batch or key in works:
                raise ResultingSalesforceError('Work Order refresh returned unexpected records.')
            works[key] = item
        if any(key not in works for key in batch):
            raise ResultingSalesforceError('Salesforce Work Order is missing during Refresh.')
        for key in batch:
            # Direct WorkOrder.Lead__c recovers a Lead missing from an imported
            # sheet; never use a different Lead when two source identities clash.
            linked_lead = str(works[key].get(WO_LEAD) or '').strip()
            if linked_lead:
                linked_lead = _require_id(linked_lead)
                if identities[key] and _require_id(identities[key]) != linked_lead:
                    raise ResultingSalesforceError('Work Order Lead changed during Refresh.')
                identities[key] = linked_lead

        # Different Work Orders may share a Lead. Fetch each Lead exactly
        # once across every SOQL page rather than treating repeats as invalid.
        lead_ids = sorted({_require_id(identities[key])
                           for key in batch if identities[key]} - set(leads))
        if lead_ids:
            filter_ids = ','.join(_soql(key) for key in lead_ids)
            fields = (LEAD_FIELDS['dnr'], LEAD_FIELDS['dnr_reason'],
                      LEAD_FIELDS['one_leg'], LEAD_FIELDS['status'],
                      LEAD_FIELDS['previous_result'])
            for item in adapter._query(
                'SELECT Id,' + ','.join(fields) + ' FROM ' + LEAD
                + ' WHERE Id IN (' + filter_ids + ') ORDER BY Id LIMIT 2000'
            ):
                key = _require_id(str(item.get('Id') or ''))
                if key not in lead_ids or key in leads:
                    raise ResultingSalesforceError('Lead refresh returned unexpected records.')
                leads[key] = item
            if any(key not in leads for key in lead_ids):
                raise ResultingSalesforceError('Salesforce Lead is missing during Refresh.')

        result_fields = (
            PR['work_order'], PR['lead'], PR['product'], PR['result'],
            PR['detail'], PR['price'], PR['one_leg'], PR['free_lead'],
            PR['cxl_at_lead'],
        )
        for item in adapter._query(
            'SELECT Id,' + ','.join(result_fields) + ' FROM ' + PRODUCT_RESULT
            + ' WHERE ' + PR['work_order'] + ' IN (' + ids + ')'
            + ' ORDER BY Id LIMIT 2000'
        ):
            key = _require_id(str(item.get(PR['work_order']) or ''))
            if key not in batch or (
                identities[key] and item.get(PR['lead'])
                and item[PR['lead']] != identities[key]
            ):
                raise ResultingSalesforceError('Product result refresh identity mismatch.')
            products.setdefault(key, []).append(item)
    return project_salesforce_drafts(adapter.zone, identities, works, leads, products)
