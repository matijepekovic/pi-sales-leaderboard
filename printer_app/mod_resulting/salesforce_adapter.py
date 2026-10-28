"""Salesforce CLI write adapter for MOD resulting.

Every Salesforce object and field name here is an explicit adapter-owned
contract. Core workflow code never depends on Salesforce API names.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
import re
import shlex
import subprocess
from zoneinfo import ZoneInfo


ID_RE = re.compile(r'[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?\Z')
NAME_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,254}\Z')

WORK_ORDER = 'WorkOrder'
LEAD = 'Lead'
# Verified org relationship and chronology fields for historical resulting.
WO_LEAD = 'Lead__c'
WO_APPOINTMENT_DATETIME = 'Appointment_Date_Time__c'
WO_APPOINTMENT_DATE = 'Appointment_Date__c'
SERVICE_APPOINTMENT = 'ServiceAppointment'
PRODUCT_RESULT = 'Product_Interest_Result__c'
# Review exists as a training field, but its live API metadata must be
# verified on checked submissions; do not require it for unrelated jobs.
REVIEW_FIELD = 'Review__c'

WO = {
    'dispo': 'Dispo__c',
    'status': 'Status',
    'mod': 'MOD__c',
    'notes': 'MOD_Notes__c',
    'call_1': 'Call_1__c',
    'call_2': 'Call_2__c',
    'docs': 'Docs__c',
    'ninety_min': 'X90_Min__c',
    'promotion': 'Promotion__c',
    'start_price': 'Start_Price__c',
    'final_price': 'Price__c',
    'deposit': 'Deposit_Payment__c',
    'need': 'Need__c',
    'want': 'Want__c',
}
LEAD_FIELDS = {
    'status': 'Status',
    'previous_result': 'Previous_Result__c',
    'dnr': 'DNR_Do_Not_Reset__c',
    'dnr_reason': 'DNR_Reason__c',
    'one_leg': 'X1_Leg_Appointment__c',
    'product_interest': 'Product_Interest_lead__c',
}
SA = {
    'status': 'Status',
    'work_order': 'FSSK__FSK_Work_Order__c',
}
PR = {
    'lead': 'Lead__c',
    'work_order': 'Work_Order__c',
    'product': 'Product_Interest__c',
    'result': 'Result__c',
    'detail': 'Result_Detail__c',
    'price': 'Price_Given__c',
    'one_leg': 'PR_1_Leg_Appointment__c',
    'free_lead': 'Free_Product_Lead__c',
    'cxl_at_lead': 'CXL_Per_Redline__c',
}

WORK_ORDER_DISPO = {
    'sale': 'Sale',
    'pns': 'PNS',
    'np': 'No Pitch',
    'cxl': 'CXL',
    'nra': 'NRA',
    'oos': 'OOS',
}
PRODUCT_RESULT_VALUE = {
    'sale': 'Sale',
    'pns': 'Pitch No Sale',
    'np': 'No Pitch',
    'cxl': 'Canceled',
    'nra': 'No Rep Available',
    'oos': 'Canceled',
}


class ResultingSalesforceError(RuntimeError):
    pass


def _require_id(value):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ResultingSalesforceError('Salesforce record identity is missing or invalid.')
    return value


def _soql(value):
    if not isinstance(value, str) or len(value) > 1000:
        raise ResultingSalesforceError('Invalid Salesforce query value.')
    return "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"


def _split_multi(value):
    result = []
    seen = set()
    for part in str(value or '').split(';'):
        clean = part.strip()
        key = clean.casefold()
        if clean and key not in seen:
            result.append(clean)
            seen.add(key)
    return result


class ResultingSalesforceAdapter:
    def __init__(self, executable='/usr/bin/sf', target_org='work',
                 timezone_name='America/Los_Angeles', runner=subprocess.run):
        self.executable = executable
        self.target_org = target_org
        self.zone = ZoneInfo(timezone_name)
        self.runner = runner
        self._describes = {}

    def _run(self, parts, *, timeout=60):
        try:
            completed = self.runner(
                [self.executable, *parts, '--target-org', self.target_org, '--json'],
                text=True, capture_output=True, check=False, timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ResultingSalesforceError('Salesforce CLI unavailable or timed out.') from exc
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, ValueError) as exc:
            raise ResultingSalesforceError('Salesforce CLI returned invalid JSON.') from exc
        if completed.returncode or payload.get('status') not in (0, None):
            raise ResultingSalesforceError(
                'Salesforce rejected ' + ' '.join(parts[:3]) + '. Check permissions and values.')
        return payload.get('result') or {}

    def _query(self, soql, *, max_results=2000):
        result = self._run(['data', 'query', '--query', soql], timeout=75)
        if not isinstance(result, dict) or not isinstance(result.get('records'), list):
            raise ResultingSalesforceError('Salesforce query returned invalid records.')
        records = result['records']
        if len(records) > max_results or result.get('done') is False:
            raise ResultingSalesforceError('Salesforce query is incomplete; refusing partial results.')
        return records

    def _describe(self, name):
        if not NAME_RE.fullmatch(name):
            raise ResultingSalesforceError('Invalid Salesforce object name.')
        if name not in self._describes:
            result = self._run(['sobject', 'describe', '--sobject', name])
            if not isinstance(result, dict) or result.get('name') != name:
                raise ResultingSalesforceError('Salesforce returned invalid object metadata.')
            self._describes[name] = result
        return self._describes[name]

    @staticmethod
    def _field(schema, api_name, *, update=True, create=False, types=()):
        matches = [
            field for field in schema.get('fields', [])
            if field.get('name') == api_name
        ]
        if len(matches) != 1:
            raise ResultingSalesforceError(
                'Required Salesforce field is missing: '
                + str(schema.get('name', '?')) + '.' + api_name
            )
        field = matches[0]
        if update and field.get('updateable') is not True:
            raise ResultingSalesforceError(
                str(schema.get('name')) + '.' + api_name + ' is not writable.'
            )
        if create and field.get('createable') is not True:
            raise ResultingSalesforceError(
                str(schema.get('name')) + '.' + api_name + ' is not createable.'
            )
        if types and field.get('type') not in types:
            raise ResultingSalesforceError(
                str(schema.get('name')) + '.' + api_name
                + ' has unexpected type ' + str(field.get('type')) + '.'
            )
        return field

    @staticmethod
    def _choice(field, value):
        if value is None:
            return None
        if field.get('type') not in ('picklist', 'multipicklist'):
            return value
        allowed = {
            str(item.get('value', '')).casefold(): str(item.get('value'))
            for item in field.get('picklistValues', [])
            if isinstance(item, dict) and item.get('active', True) and item.get('value')
        }
        if field.get('type') == 'multipicklist':
            choices = _split_multi(value)
            resolved = []
            for choice in choices:
                actual = allowed.get(choice.casefold())
                if actual is None:
                    raise ResultingSalesforceError(
                        'Salesforce does not allow ' + choice + ' for ' + field['name'] + '.'
                    )
                resolved.append(actual)
            return ';'.join(resolved)
        actual = allowed.get(str(value).casefold())
        if actual is None:
            raise ResultingSalesforceError(
                'Salesforce does not allow ' + str(value) + ' for ' + field['name'] + '.'
            )
        return actual

    @classmethod
    def _value(cls, field, value):
        if value is None:
            return None
        kind = field.get('type')
        if kind == 'boolean':
            if type(value) is not bool:
                raise ResultingSalesforceError(field['name'] + ' must be a checkbox.')
            return value
        if kind == 'reference':
            return _require_id(value)
        if kind in ('picklist', 'multipicklist'):
            return cls._choice(field, value)
        if kind in ('currency', 'double', 'int', 'long', 'percent'):
            if not re.fullmatch(r'\d+(?:\.\d{1,2})?', str(value)):
                raise ResultingSalesforceError('Invalid numeric value for ' + field['name'] + '.')
            return str(value)
        if kind in ('textarea', 'string', 'date', 'datetime', 'time', 'phone'):
            return str(value)
        raise ResultingSalesforceError(
            'Unsupported Salesforce type for ' + field['name'] + ': ' + str(kind)
        )

    def read_results(self, records):
        """Read existing Salesforce resulting fields; never write on Refresh."""
        from .salesforce_refresh import read_result_drafts
        return read_result_drafts(self, records)

    @classmethod
    def _checked_yes(cls, field):
        """Only checked training fields are written; unchecked are omitted."""
        kind = field.get('type')
        if kind == 'boolean':
            return True
        if kind in ('string', 'textarea'):
            return 'Yes'
        if kind == 'picklist':
            return cls._choice(field, 'Yes')
        raise ResultingSalesforceError(
            field.get('name', 'Field') + ' cannot store a checked Yes value.'
        )

    def mod_users(self, market_segment):
        """Read active Sales Managers from the already-imported MOD market.

        Salesforce User.Home_Branch__c and UserRole.Name were verified with
        the existing CLI mapping. Do not infer a market from Title, Division,
        Department, or unverified guessed fields. Never return all users.
        """
        market = str(market_segment or '').strip()
        if not market or len(market) > 128 or any(not ch.isprintable() for ch in market):
            raise ResultingSalesforceError('The imported MOD market is missing or invalid.')

        rows = self._query(
            'SELECT Id,Name,IsActive,Home_Branch__c,UserRole.Name FROM User '
            'WHERE IsActive = true '
            "AND UserRole.Name = 'Sales Manager' "
            'AND Home_Branch__c = ' + _soql(market)
            + ' ORDER BY Name LIMIT 2000'
        )
        users = []
        seen = set()
        for item in rows:
            ident = str(item.get('Id') or '')
            name = str(item.get('Name') or '').strip()
            home_branch = str(item.get('Home_Branch__c') or '').strip()
            role = str((item.get('UserRole') or {}).get('Name') or '').strip()
            if (ID_RE.fullmatch(ident) and name and item.get('IsActive') is True
                    and home_branch.casefold() == market.casefold()
                    and role.casefold() == 'sales manager'
                    and ident not in seen):
                users.append({'id': ident, 'name': name})
                seen.add(ident)
        return users

    @staticmethod
    def _options(field):
        if field.get('type') not in ('picklist', 'multipicklist'):
            raise ResultingSalesforceError(
                'Expected Salesforce dropdown field: ' + field['name']
            )
        options = []
        for item in field.get('picklistValues') or ():
            if isinstance(item, dict) and item.get('active', True) and item.get('value'):
                options.append({
                    'value': str(item['value']),
                    'label': str(item.get('label') or item['value']),
                })
        if not options:
            raise ResultingSalesforceError(
                'Salesforce dropdown has no available choices: ' + field['name']
            )
        return options

    def dropdowns(self):
        lead = self._describe(LEAD)
        product = self._describe(PRODUCT_RESULT)
        return {
            'result_details': self._options(
                self._field(product, PR['detail'], types=('picklist', 'multipicklist'))
            ),
            'dnr_reasons': self._options(
                self._field(lead, LEAD_FIELDS['dnr_reason'], types=('multipicklist',))
            ),
            'products': self._options(
                self._field(product, PR['product'], update=False, types=('picklist',))
            ),
        }

    def _time_value(self, day, entered, field):
        if not entered:
            return None
        stamp = datetime.strptime(day + ' ' + entered, '%Y-%m-%d %I:%M %p')
        kind = field['type']
        if kind == 'datetime':
            return stamp.replace(tzinfo=self.zone).astimezone(timezone.utc).strftime(
                '%Y-%m-%dT%H:%M:%SZ'
            )
        if kind == 'time':
            return stamp.strftime('%H:%M:%S.000Z')
        if kind in ('string', 'textarea'):
            return entered
        raise ResultingSalesforceError(
            field['name'] + ' cannot safely store an AM/PM time.'
        )

    def _appointment_ids(self, work_order_id, day):
        work_order_id = _require_id(work_order_id)
        start = datetime.combine(date.fromisoformat(day), time.min, tzinfo=self.zone)
        end = start + timedelta(days=1)
        lo = start.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        hi = end.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        rows = self._query(
            'SELECT Id FROM ' + SERVICE_APPOINTMENT + ' WHERE '
            + SA['work_order'] + ' = ' + _soql(work_order_id)
            + ' AND SchedStartTime >= ' + lo
            + ' AND SchedStartTime < ' + hi
            + ' ORDER BY Id LIMIT 2000'
        )
        ids = [_require_id(str(row.get('Id') or '')) for row in rows]
        if not ids or len(set(ids)) != len(ids):
            raise ResultingSalesforceError(
                'No unique same-day Service Appointments for Work Order.'
            )
        return ids

    def _existing_product_results(self, lead_id, work_order_id):
        rows = self._query(
            'SELECT Id,' + PR['product'] + ' FROM ' + PRODUCT_RESULT
            + ' WHERE ' + PR['lead'] + ' = ' + _soql(lead_id)
            + ' AND ' + PR['work_order'] + ' = ' + _soql(work_order_id)
            + ' LIMIT 2000'
        )
        result = {}
        for row in rows:
            ident = _require_id(str(row.get('Id') or ''))
            product = str(row.get(PR['product']) or '').strip()
            key = product.casefold()
            if not product or key in result:
                raise ResultingSalesforceError(
                    'Product Interest Result identity is missing or ambiguous.'
                )
            result[key] = ident
        return result

    def _lead_product_interest(self, lead_id):
        rows = self._query(
            'SELECT Id,' + LEAD_FIELDS['product_interest'] + ' FROM ' + LEAD
            + ' WHERE Id = ' + _soql(lead_id) + ' LIMIT 2'
        )
        if len(rows) != 1 or str(rows[0].get('Id') or '') != lead_id:
            raise ResultingSalesforceError('Lead changed or is unavailable.')
        return str(rows[0].get(LEAD_FIELDS['product_interest']) or '')

    @staticmethod
    def _merge_products(existing, sold):
        result = _split_multi(existing)
        seen = {item.casefold() for item in result}
        added = False
        for item in sold:
            key = item.casefold()
            if key not in seen:
                result.append(item)
                seen.add(key)
                added = True
        return ';'.join(result), added

    def _product_operations(self, payload, schema):
        lead_field = self._field(
            schema, PR['lead'], update=False, create=True, types=('reference',)
        )
        wo_field = self._field(
            schema, PR['work_order'], update=False, create=True, types=('reference',)
        )
        product_field = self._field(
            schema, PR['product'], update=False, create=True, types=('picklist',)
        )
        result_field = self._field(
            schema, PR['result'], create=True, types=('picklist',)
        )
        detail_field = self._field(
            schema, PR['detail'], create=True, types=('picklist', 'multipicklist')
        )
        price_field = self._field(
            schema, PR['price'], create=True, types=('currency', 'double', 'int', 'long')
        )
        one_leg_field = self._field(
            schema, PR['one_leg'], create=True, types=('boolean',)
        )
        free_field = self._field(
            schema, PR['free_lead'], create=True, types=('boolean',)
        )
        cxl_field = self._field(
            schema, PR['cxl_at_lead'], create=True, types=('boolean',)
        )

        existing = self._existing_product_results(
            payload['lead_id'], payload['work_order_id']
        )
        operations = []
        for entry in payload['product_results']:
            product = self._choice(product_field, entry['product'])
            result = self._choice(
                result_field, PRODUCT_RESULT_VALUE[entry['result']]
            )
            detail = (
                self._choice(detail_field, entry['detail'])
                if entry.get('detail') else None
            )
            fields = {
                PR['result']: result,
                PR['one_leg']: self._value(one_leg_field, payload['draft']['one_leg']),
                PR['free_lead']: self._value(free_field, payload['draft']['free_lead']),
                PR['cxl_at_lead']: self._value(
                    cxl_field, payload['draft']['cxl_at_lead']
                ),
            }
            old_id = existing.get(str(product).casefold())
            if detail is not None:
                fields[PR['detail']] = detail
            elif old_id:
                fields[PR['detail']] = None

            if entry['result'] == 'sale':
                if not entry.get('price') or str(entry['price']) == '0':
                    raise ResultingSalesforceError(
                        'Sold Product Interest Result requires its own positive Price Given.'
                    )
                fields[PR['price']] = self._value(price_field, entry['price'])
            elif entry['result'] in ('pns', 'np') and old_id:
                # Explicitly clear a stale sale price when a current result is PNS/No Pitch.
                fields[PR['price']] = None

            if old_id:
                operations.append(('update', PRODUCT_RESULT, old_id, fields))
            else:
                fields.update({
                    PR['lead']: self._value(lead_field, payload['lead_id']),
                    PR['work_order']: self._value(wo_field, payload['work_order_id']),
                    PR['product']: product,
                })
                operations.append(('create', PRODUCT_RESULT, '', fields))
        return operations

    def prepare(self, payloads):
        """Preflight the complete batch before any live Salesforce write."""
        wo_schema = self._describe(WORK_ORDER)
        lead_schema = self._describe(LEAD)
        sa_schema = self._describe(SERVICE_APPOINTMENT)
        pr_schema = self._describe(PRODUCT_RESULT)

        sa_status = self._field(sa_schema, SA['status'], types=('picklist',))
        sa_work_order = self._field(
            sa_schema, SA['work_order'], update=False, types=('reference',)
        )
        if WORK_ORDER not in (sa_work_order.get('referenceTo') or []):
            raise ResultingSalesforceError(
                SERVICE_APPOINTMENT + '.' + SA['work_order']
                + ' does not reference WorkOrder.'
            )

        # Validate all writable fields once by exact API name.
        wo_types = {
            'dispo': ('picklist', 'string'),
            'status': ('picklist', 'string'),
            'mod': ('reference',),
            'notes': ('textarea', 'string'),
            'call_1': ('datetime', 'time', 'string', 'textarea'),
            'call_2': ('datetime', 'time', 'string', 'textarea'),
            'docs': ('boolean', 'string', 'textarea', 'picklist'),
            'ninety_min': ('boolean', 'string', 'textarea', 'picklist'),
            'promotion': ('boolean',),
            'start_price': ('currency', 'double', 'int', 'long'),
            'final_price': ('currency', 'double', 'int', 'long'),
            'deposit': ('currency', 'double', 'int', 'long'),
            'need': ('textarea', 'string'),
            'want': ('textarea', 'string'),
        }
        wo_fields = {
            key: self._field(wo_schema, api_name, types=wo_types[key])
            for key, api_name in WO.items()
        }
        lead_types = {
            'status': ('picklist', 'string'),
            'previous_result': ('picklist', 'string'),
            'dnr': ('boolean',),
            'dnr_reason': ('multipicklist',),
            'one_leg': ('boolean',),
            'product_interest': ('multipicklist',),
        }
        lead_fields = {
            key: self._field(lead_schema, api_name, types=lead_types[key])
            for key, api_name in LEAD_FIELDS.items()
        }
        if lead_fields['dnr_reason'].get('type') != 'multipicklist':
            raise ResultingSalesforceError(
                LEAD + '.' + LEAD_FIELDS['dnr_reason'] + ' must be a multi-select field.'
            )

        # Historical Previous Result is resolved from each Lead's earlier
        # resulted Work Orders. The current Work Order's Dispo is never used to
        # infer its own Previous Result. Read everything before the first write.
        from .historical_result import historical_previous_result
        relationship = self._field(
            wo_schema, WO_LEAD, update=False, types=('reference',)
        )
        if LEAD not in (relationship.get('referenceTo') or []):
            raise ResultingSalesforceError(
                WORK_ORDER + '.' + WO_LEAD + ' does not reference Lead.'
            )
        self._field(wo_schema, WO_APPOINTMENT_DATETIME, update=False,
                    types=('datetime',))
        self._field(wo_schema, WO_APPOINTMENT_DATE, update=False,
                    types=('date',))
        history_by_lead = {}
        for lead_id in dict.fromkeys(
            _require_id(payload['lead_id']) for payload in payloads
        ):
            rows = self._query(
                'SELECT Id,' + WO_LEAD + ',' + WO['dispo']
                + ',' + WO_APPOINTMENT_DATETIME + ',' + WO_APPOINTMENT_DATE
                + ' FROM ' + WORK_ORDER
                + ' WHERE ' + WO_LEAD + ' = ' + _soql(lead_id)
                + ' ORDER BY ' + WO_APPOINTMENT_DATETIME + ' DESC LIMIT 2000'
            )
            if any(str(row.get(WO_LEAD) or '') != lead_id for row in rows):
                raise ResultingSalesforceError(
                    'Historical Work Order does not match the selected Lead.'
                )
            history_by_lead[lead_id] = rows
        pending_dispositions = {
            _require_id(payload['work_order_id']): WORK_ORDER_DISPO[payload['dispo']]
            for payload in payloads
        }

        operations = []
        # Different Work Orders can refer to the same Lead. Accumulate pivot
        # additions across the whole End of Day batch; never overwrite a pivot
        # added by an earlier Work Order in this same batch.
        lead_interest_in_batch = {}
        for payload in payloads:
            work_order_id = _require_id(payload['work_order_id'])
            lead_id = _require_id(payload['lead_id'])
            mod_id = _require_id(payload['mod_id'])
            appointment_ids = self._appointment_ids(work_order_id, payload['day'])

            appointment_status = self._choice(
                sa_status, payload['fields']['appointment_status']
            )
            plan = [
                ('update', SERVICE_APPOINTMENT, ident, {
                    SA['status']: appointment_status,
                })
                for ident in appointment_ids
            ]

            wo_values = {
                WO['dispo']: self._value(
                    wo_fields['dispo'],
                    self._choice(wo_fields['dispo'], WORK_ORDER_DISPO[payload['dispo']])
                    if wo_fields['dispo'].get('type') in ('picklist', 'multipicklist')
                    else WORK_ORDER_DISPO[payload['dispo']],
                ),
                WO['status']: self._value(
                    wo_fields['status'],
                    self._choice(wo_fields['status'], payload['fields']['work_order_status'])
                    if wo_fields['status'].get('type') in ('picklist', 'multipicklist')
                    else payload['fields']['work_order_status'],
                ),
                WO['mod']: self._value(wo_fields['mod'], mod_id),
                WO['notes']: self._value(
                    wo_fields['notes'],
                    '\n'.join(part for part in (
                        payload['draft']['numbers'],
                        payload['draft']['notes'],
                        payload['final_redlines'],
                    ) if part).strip(),
                ),
                WO['promotion']: self._value(
                    wo_fields['promotion'], payload['draft']['promotion']
                ),
                WO['need']: self._value(wo_fields['need'], payload['draft']['need']),
                WO['want']: self._value(wo_fields['want'], payload['draft']['want']),
            }
            for key in ('docs', 'ninety_min'):
                if payload['draft'][key]:
                    wo_values[WO[key]] = self._checked_yes(wo_fields[key])
            if payload['draft']['review']:
                review = self._field(
                    wo_schema, REVIEW_FIELD,
                    types=('boolean', 'string', 'textarea', 'picklist')
                )
                wo_values[REVIEW_FIELD] = self._checked_yes(review)
            for key in ('call_1', 'call_2'):
                if payload['draft'][key]:
                    wo_values[WO[key]] = self._time_value(
                        payload['day'], payload['draft'][key], wo_fields[key]
                    )
            # These two values have independent manual overrides. Neither
            # field requires the other field to be populated.
            if payload['fields']['price']['highest']:
                wo_values[WO['start_price']] = self._value(
                    wo_fields['start_price'], payload['fields']['price']['highest']
                )
            if payload['fields']['price']['lowest']:
                wo_values[WO['final_price']] = self._value(
                    wo_fields['final_price'], payload['fields']['price']['lowest']
                )
            if payload['deposit_total'] != '':
                # The total is from actual sold products, never a Work Order
                # price. Zero is a valid deposit total.
                wo_values[WO['deposit']] = self._value(
                    wo_fields['deposit'], payload['deposit_total']
                )
            plan.append(('update', WORK_ORDER, work_order_id, wo_values))

            lead_values = {
                LEAD_FIELDS['status']: self._value(
                    lead_fields['status'],
                    self._choice(
                        lead_fields['status'], payload['fields']['lead_status']
                    ) if lead_fields['status'].get('type') in ('picklist', 'multipicklist')
                    else payload['fields']['lead_status'],
                ),
                LEAD_FIELDS['dnr']: self._value(
                    lead_fields['dnr'], payload['draft']['dnr']
                ),
                LEAD_FIELDS['one_leg']: self._value(
                    lead_fields['one_leg'], payload['draft']['one_leg']
                ),
            }
            if payload['draft']['dnr']:
                lead_values[LEAD_FIELDS['dnr_reason']] = self._choice(
                    lead_fields['dnr_reason'], payload['draft']['dnr_reason']
                )
            else:
                lead_values[LEAD_FIELDS['dnr_reason']] = None
            previous = historical_previous_result(
                history_by_lead[lead_id], work_order_id,
                timezone_name=self.zone.key,
                pending_dispositions=pending_dispositions,
            )
            if previous is None and lead_fields['previous_result'].get('nillable') is False:
                raise ResultingSalesforceError(
                    'Lead.Previous_Result__c is required and cannot be blank.'
                )
            # A missing/unsupported latest historical result intentionally
            # clears the prior Lead value, rather than preserving a stale one.
            lead_values[LEAD_FIELDS['previous_result']] = (
                self._choice(lead_fields['previous_result'], previous)
                if previous is not None else None
            )

            sold = [
                entry['product'] for entry in payload['product_results']
                if entry['result'] == 'sale'
            ]
            if sold:
                current = lead_interest_in_batch.get(lead_id)
                if current is None:
                    current = self._lead_product_interest(lead_id)
                merged, changed = self._merge_products(current, sold)
                lead_interest_in_batch[lead_id] = merged
                if changed:
                    lead_values[LEAD_FIELDS['product_interest']] = self._choice(
                        lead_fields['product_interest'], merged
                    ) if lead_fields['product_interest'].get('type') == 'multipicklist' else merged
            plan.append(('update', LEAD, lead_id, lead_values))
            plan.extend(self._product_operations(payload, pr_schema))
            operations.append(plan)
        return operations

    @staticmethod
    def _values_argument(values):
        chunks = []
        for key, value in values.items():
            if not NAME_RE.fullmatch(key):
                raise ResultingSalesforceError('Unsafe Salesforce field name.')
            if value is True:
                raw = 'true'
            elif value is False:
                raw = 'false'
            elif value is None:
                raw = ''
            else:
                raw = str(value)
            chunks.append(key + '=' + shlex.quote(raw))
        return ' '.join(chunks)

    def apply(self, operations):
        """Apply only a preflighted plan. No shell interpolation is used."""
        for action, object_name, record_id, values in operations:
            pairs = self._values_argument(values)
            if action == 'update':
                self._run([
                    'data', 'update', 'record', '--sobject', object_name,
                    '--record-id', _require_id(record_id), '--values', pairs,
                ])
            elif action == 'create':
                self._run([
                    'data', 'create', 'record', '--sobject', object_name,
                    '--values', pairs,
                ])
            else:
                raise ResultingSalesforceError('Unknown resulting operation.')
