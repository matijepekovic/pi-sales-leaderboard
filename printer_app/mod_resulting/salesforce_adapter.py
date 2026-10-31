"""Salesforce CLI write adapter for MOD resulting.

Every Salesforce object and field name here is an explicit adapter-owned
contract. Core workflow code never depends on Salesforce API names.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import json
import re
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
# The native Result Appointment Flow selects Service Appointments by ParentRecordId.
SA_PARENT = 'ParentRecordId'
PRODUCT_RESULT = 'Product_Interest_Result__c'
# Result Appointment Flow fields, owned and validated by this adapter only.
PR_ISSUED_COUNT = 'Include_in_Issued_Lead_Count__c'
PR_APPOINTMENT_DATE = 'PR_Appointment_Date__c'
# Exact creation-time source mappings from Result Appointment Flow v30.
# Kept vendor-specific in the replaceable Salesforce adapter.
PIR_LEAD_COPY = {
    'PR_Appointment_Time__c': 'Appointment_Time__c',
    'PR_Approved_By_Supervisor__c': 'Approved_By_Supervisor__c',
    'PR_Canvass_Set_By__c': 'Canvass_Set_By__c',
    'PR_Confirmed_By__c': 'Confirmed_By__c',
    'PR_Lead_Source__c': 'LeadSource',
    'PR_Reset_By__c': 'Reset_By__c',
    'PR_Set_By__c': 'Set_By__c',
    'PR_Sub_Source__c': 'Sub_Source__c',
}

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

    def _run(self, parts, *, timeout=60, input_body=None):
        # JSON writes travel through stdin, never through the CLI's fragile
        # shell-like --values parser or process command-line arguments.
        run_options = dict(text=True, capture_output=True,
                           check=False, timeout=timeout)
        if input_body is not None:
            run_options['input'] = input_body
        try:
            completed = self.runner(
                [self.executable, *parts, '--target-org', self.target_org, '--json'],
                **run_options,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ResultingSalesforceError('Salesforce CLI unavailable or timed out.') from exc
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, ValueError) as exc:
            raise ResultingSalesforceError('Salesforce CLI returned invalid JSON.') from exc
        if completed.returncode or payload.get('status') not in (0, None):
            # Salesforce CLI --json already includes the actual rejection.
            # Preserve its code and message instead of replacing them with a
            # generic permissions warning. Never echo CLI arguments/values.
            code = str(payload.get('name') or payload.get('errorCode') or '').strip()
            reason = payload.get('message')
            if not reason:
                result = payload.get('result') or payload.get('data')
                if isinstance(result, dict):
                    reason = result.get('message') or result.get('errors')
                elif isinstance(result, list):
                    reason = result
            if isinstance(reason, list):
                reason = '; '.join(
                    str(item.get('message') or item.get('errorCode') or item)
                    if isinstance(item, dict) else str(item)
                    for item in reason
                )
            reason = str(reason or '').strip()
            # Salesforce error text may contain data values; never surface an
            # access token or authorization header even if one is echoed.
            reason = re.sub(
                r'(?i)\bBearer\s+[^\s,;]+', 'Bearer [REDACTED]', reason)
            reason = re.sub(
                r'(?i)\b(accessToken|sfdxAuthUrl|authorization)\s*[:=]\s*\S+',
                r'\1=[REDACTED]', reason)
            object_name = (parts[parts.index('--sobject') + 1]
                           if '--sobject' in parts else 'Salesforce')
            operation = ' '.join(parts[:3])
            detail = (code + ': ' if code and reason and code not in reason
                      else code if code and not reason else '') + reason
            raise ResultingSalesforceError(
                object_name + ' ' + operation + ' failed: '
                + (detail or 'Salesforce returned no error details.'))
        return payload.get('result') or {}

    def _query(self, soql, *, max_results=2000):
        result = self._run(['data', 'query', '--query', soql], timeout=75)
        if not isinstance(result, dict) or not isinstance(result.get('records'), list):
            raise ResultingSalesforceError('Salesforce query returned invalid records.')
        records = result['records']
        if len(records) > max_results or result.get('done') is False:
            raise ResultingSalesforceError('Salesforce query is incomplete; refusing partial results.')
        return records

    def prepare_metadata(self):
        """Warm the four write schemas on the worker before End of Day."""
        for name in (WORK_ORDER, LEAD, SERVICE_APPOINTMENT, PRODUCT_RESULT):
            self._describe(name)

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

    def checkbox_fields(self):
        """Safe presentation contracts; never expose source API field names."""
        groups = (
            (WORK_ORDER, ('docs', 'ninety_min', 'promotion', 'review')),
            (LEAD, ('dnr', 'one_leg')),
            (PRODUCT_RESULT, ('free_lead', 'cxl_at_lead')),
        )
        definitions = {}
        for object_name, keys in groups:
            schema = self._describe(object_name)
            names = WO if object_name == WORK_ORDER else (
                LEAD_FIELDS if object_name == LEAD else PR
            )
            for key in keys:
                name = REVIEW_FIELD if key == 'review' else names[key]
                match = [item for item in schema.get('fields', ())
                         if item.get('name') == name]
                if len(match) != 1:
                    continue
                field = match[0]
                kind = field.get('type')
                if kind not in ('boolean', 'string', 'textarea', 'picklist'):
                    continue
                definitions[key] = {
                    'kind': kind,
                    'editable': field.get('updateable') is True,
                    'nullable': field.get('nillable') is not False,
                    'length': min(int(field.get('length') or 3000), 3000),
                    'choices': [
                        {'value': str(item['value']),
                         'label': str(item.get('label') or item['value'])}
                        for item in (field.get('picklistValues') or ())
                        if kind == 'picklist' and isinstance(item, dict)
                        and item.get('active', True) and item.get('value')
                    ],
                }
        return definitions

    @classmethod
    def _source_checkbox_value(cls, field, value):
        """A deliberate edit is validated against live field metadata."""
        kind = field.get('type')
        if value is None or value == '':
            if field.get('nillable') is False:
                raise ResultingSalesforceError(
                    field['name'] + ' cannot be cleared.')
            return None
        if type(value) is bool:
            if kind == 'boolean':
                return value
            if value:
                return cls._checked_yes(field)
            if field.get('nillable') is False:
                raise ResultingSalesforceError(
                    field['name'] + ' cannot be unchecked without a value.')
            return None
        if not isinstance(value, str):
            raise ResultingSalesforceError('Invalid source checkbox edit.')
        if kind == 'boolean':
            raise ResultingSalesforceError('Checkbox requires True or False.')
        if kind in ('string', 'textarea'):
            limit = int(field.get('length') or 3000)
            if len(value) > min(limit, 3000):
                raise ResultingSalesforceError('Checkbox text exceeds the Salesforce field limit.')
        return cls._value(field, value)

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

    def _existing_product_results(self, lead_id, work_order_id, *, rows=None):
        fields = 'Id,' + PR['product'] + ',' + PR_ISSUED_COUNT + ',' + PR_APPOINTMENT_DATE
        if rows is None:
            rows = self._query(
                'SELECT ' + fields + ' FROM ' + PRODUCT_RESULT
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
            issued = row.get(PR_ISSUED_COUNT)
            day = row.get(PR_APPOINTMENT_DATE)
            if issued is not None and type(issued) is not bool:
                raise ResultingSalesforceError('Salesforce issued-lead flag is invalid.')
            if day:
                if not isinstance(day, str):
                    raise ResultingSalesforceError('Salesforce result appointment date is invalid.')
                try:
                    date.fromisoformat(day)
                except ValueError as exc:
                    raise ResultingSalesforceError(
                        'Salesforce result appointment date is invalid.'
                    ) from exc
            result[key] = {
                'id': ident,
                'issued': issued is True,
                'appointment_date': day or '',
            }
        return result

    def lead_appointment_dates(self, lead_ids):
        """Read current Lead dates for the Flow's branch decisions, in batches.

        A separate, replaceable source lookup keeps this Salesforce field out
        of the shared MOD sheet contract and Gallery. Never derive the date
        from a Work Order's scheduled start or from a stale local draft.
        """
        if isinstance(lead_ids, str):
            raise ResultingSalesforceError('Lead date lookup requires record identities.')
        lead_ids = tuple(lead_ids)
        requested = {}
        for raw in lead_ids:
            ident = _require_id(raw)
            requested.setdefault(ident[:15], ident)
        if not requested:
            return {}

        dates = {}
        keys = list(requested)
        for offset in range(0, len(keys), 40):
            batch = keys[offset:offset + 40]
            query = (
                'SELECT Id,Appointment_Date__c FROM ' + LEAD
                + ' WHERE Id IN ('
                + ','.join(_soql(requested[key]) for key in batch)
                + ') ORDER BY Id LIMIT 2000'
            )
            for row in self._query(query):
                ident = _require_id(str(row.get('Id') or ''))[:15]
                if ident not in batch or ident in dates:
                    raise ResultingSalesforceError(
                        'Lead appointment date lookup returned unexpected records.'
                    )
                value = row.get('Appointment_Date__c')
                if value is not None and not isinstance(value, str):
                    raise ResultingSalesforceError('Salesforce Lead appointment date is invalid.')
                dates[ident] = value or ''
            if any(key not in dates for key in batch):
                raise ResultingSalesforceError(
                    'A Lead is unavailable for appointment date lookup.'
                )
        return {raw: dates[_require_id(raw)[:15]] for raw in lead_ids}

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

    def _flow_pir_create_values(self, lead_id, lead_schema, pir_schema, result, comment,
                                *, source_row=None):
        """Resolve v30 PIR creation-only fields from their actual Lead sources.

        Never copy MOD notes into a PIR comment or overwrite existing PIR
        attribution during Override. Every required mapping is preflighted.
        """
        source_fields = sorted(set(PIR_LEAD_COPY.values()))
        # Describe both sides to fail before any live Salesforce updates.
        destination_fields = {
            dest: self._field(pir_schema, dest, update=False, create=True)
            for dest in PIR_LEAD_COPY
        }
        for name in ('Original_Disposition__c', 'Comment__c'):
            destination_fields[name] = self._field(
                pir_schema, name, update=False, create=True
            )
        for name in source_fields:
            self._field(lead_schema, name, update=False)
        if source_row is None:
            rows = self._query(
                'SELECT Id,' + ','.join(source_fields) + ' FROM ' + LEAD
                + ' WHERE Id = ' + _soql(lead_id) + ' LIMIT 2'
            )
            if len(rows) != 1:
                raise ResultingSalesforceError(
                    'Lead attribution is unavailable for Flow v30 PIR creation.')
            source_row = rows[0]
        if _require_id(str(source_row.get('Id') or ''))[:15] != lead_id[:15]:
            raise ResultingSalesforceError(
                'Lead attribution identity does not match the submitted Lead.')
        row = source_row
        result_fields = {}
        for dest, source in PIR_LEAD_COPY.items():
            if source not in row:
                raise ResultingSalesforceError('Missing Lead Flow source: ' + source)
            result_fields[dest] = self._value(destination_fields[dest], row[source])
        result_fields['Original_Disposition__c'] = self._value(
            destination_fields['Original_Disposition__c'], result
        )
        result_fields['Comment__c'] = self._value(
            destination_fields['Comment__c'], comment
        )
        return result_fields

    def _product_operations(self, payload, schema, lead_schema=None,
                            *, existing_rows=None, attribution_row=None):
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
        # These two fields were read-only in Phase 2. Verify their metadata
        # before planning any writes; a missing or read-only field aborts
        # preflight rather than silently losing Flow parity.
        issued_field = self._field(
            schema, PR_ISSUED_COUNT, types=('boolean',)
        )
        appointment_field = self._field(
            schema, PR_APPOINTMENT_DATE, types=('date',)
        )
        context = payload.get('product_result_context')
        if not isinstance(context, dict) or set(context) != {
                item['product'] for item in payload['product_results']}:
            raise ResultingSalesforceError('Product result context is incomplete.')
        primary = [product for product, planned in context.items()
                   if planned.get('role') == 'primary']
        if len(primary) > 1:
            raise ResultingSalesforceError('Multiple primary product results are not valid.')

        existing = self._existing_product_results(
            payload['lead_id'], payload['work_order_id'], rows=existing_rows
        )
        lead_schema = lead_schema or self._describe(LEAD)

        operations, included = [], set()
        flow_create_cache = None
        for entry in payload['product_results']:
            product = self._choice(product_field, entry['product'])
            key = str(product).casefold()
            planned = context[entry['product']]
            if planned.get('role') not in ('primary', 'additional'):
                raise ResultingSalesforceError('Primary product cannot be resolved.')
            if type(planned.get('counts_as_issued_lead')) is not bool:
                raise ResultingSalesforceError('Issued-lead eligibility is unresolved.')
            old = existing.get(key)
            old_id = old['id'] if old else None
            source = planned.get('appointment_date_source')
            appointment_day = planned.get('appointment_date')
            if source == 'existing_result_input':
                # Flow's future input can reference an existing PIR. For a
                # genuinely new PIR there is no prior input, so use the
                # selected SA's saved date (the approved End-of-Day fallback).
                appointment_day = (old['appointment_date'] if old else
                                   planned.get('fallback_appointment_date', ''))
            elif source not in ('today', 'lead', 'work_order_appointment'):
                raise ResultingSalesforceError('Result appointment date is unresolved.')
            if not appointment_day or not isinstance(appointment_day, str):
                raise ResultingSalesforceError(
                    'Result appointment date is unavailable; no Salesforce writes were made.'
                )
            try:
                date.fromisoformat(appointment_day)
            except ValueError as exc:
                raise ResultingSalesforceError('Result appointment date is invalid.') from exc
            if not old:
                self._field(schema, PR_ISSUED_COUNT, create=True, types=('boolean',))
                self._field(schema, PR_APPOINTMENT_DATE, create=True, types=('date',))
            result = self._choice(
                result_field, PRODUCT_RESULT_VALUE[entry['result']]
            )
            detail = (
                self._choice(detail_field, entry['detail'])
                if entry.get('detail') else None
            )
            fields = {
                PR['result']: result,
                PR_ISSUED_COUNT: self._value(
                    issued_field, planned['counts_as_issued_lead']),
                PR_APPOINTMENT_DATE: self._value(
                    appointment_field, appointment_day),
            }
            raw_checks = payload['draft'].get('checkbox_values') or {}
            for name, field in (
                ('one_leg', one_leg_field),
                ('free_lead', free_field),
                ('cxl_at_lead', cxl_field),
            ):
                value = raw_checks.get(name)
                # An unchanged existing product's checkboxes are authoritative.
                if old_id and value is not None and not value['edited']:
                    continue
                entered = (value['value'] if value is not None and value['edited']
                           else payload['draft'][name])
                fields[PR[name]] = self._value(field, entered)
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
            elif old_id:
                fields[PR['price']] = None

            if old_id:
                operations.append(('update', PRODUCT_RESULT, old_id, fields))
            else:
                # Only new PIRs receive v30 creation-time attribution.
                # Existing Override fields are intentionally preserved.
                if flow_create_cache is None:
                    flow_create_cache = self._flow_pir_create_values(
                        payload['lead_id'], lead_schema, schema, result,
                        entry.get('comment'), source_row=attribution_row,
                    )
                flow_values = dict(flow_create_cache)
                # Original disposition and PIR comment are per-product.
                original = self._field(
                    schema, 'Original_Disposition__c', update=False, create=True
                )
                comment = self._field(
                    schema, 'Comment__c', update=False, create=True
                )
                flow_values['Original_Disposition__c'] = self._value(original, result)
                flow_values['Comment__c'] = self._value(comment, entry.get('comment'))
                fields.update(flow_values)
                fields.update({
                    PR['lead']: self._value(lead_field, payload['lead_id']),
                    PR['work_order']: self._value(wo_field, payload['work_order_id']),
                    PR['product']: product,
                })
                operations.append(('create', PRODUCT_RESULT, '', fields))
            included.add(key)

        # An older primary can be outside the newly selected products (a sale
        # pivot). Clear only its issued flag; do not invent a result for it.
        if context:
            for key, old in existing.items():
                if key not in included and old['issued']:
                    operations.append(('update', PRODUCT_RESULT, old['id'], {
                        PR_ISSUED_COUNT: self._value(issued_field, False),
                    }))
        return operations

    def _historical_by_lead(self, payloads):
        """Read same-batch Lead history together, with bounded keyset pages."""
        leads = list(dict.fromkeys(
            _require_id(payload['lead_id']) for payload in payloads))
        history = {lead: [] for lead in leads}
        seen = set()
        for offset in range(0, len(leads), 40):
            group = leads[offset:offset + 40]
            canonical = {ident[:15]: ident for ident in group}
            cursor = ''
            while True:
                where = WO_LEAD + ' IN (' + ','.join(_soql(lead) for lead in group) + ')'
                if cursor:
                    where += ' AND Id > ' + _soql(cursor)
                rows = self._query(
                    'SELECT Id,' + WO_LEAD + ',' + WO['dispo']
                    + ',' + WO_APPOINTMENT_DATETIME + ',' + WO_APPOINTMENT_DATE
                    + ' FROM ' + WORK_ORDER + ' WHERE ' + where
                    + ' ORDER BY Id LIMIT 2000'
                )
                for row in rows:
                    ident = _require_id(str(row.get('Id') or ''))
                    lead_id = _require_id(str(row.get(WO_LEAD) or ''))
                    lead = canonical.get(lead_id[:15])
                    if lead is None or ident in seen or (cursor and ident <= cursor):
                        raise ResultingSalesforceError(
                            'Historical Work Order identity or paging is invalid.')
                    seen.add(ident)
                    history[lead].append(row)
                if len(rows) < 2000:
                    break
                cursor = _require_id(str(rows[-1].get('Id') or ''))
        return history

    def _appointments_for_batch(self, payloads):
        """Resolve all same-day Service Appointment IDs in grouped reads."""
        groups = {}
        for payload in payloads:
            day = str(payload['day'])
            groups.setdefault(day, []).append(_require_id(payload['work_order_id']))
        appointments = {key: [] for ids in groups.values() for key in ids}
        seen = set()
        for day, ids in groups.items():
            start = datetime.combine(date.fromisoformat(day), time.min, tzinfo=self.zone)
            end = start + timedelta(days=1)
            lo = start.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            hi = end.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            for offset in range(0, len(ids), 40):
                chunk = ids[offset:offset + 40]
                canonical = {ident[:15]: ident for ident in chunk}
                cursor = ''
                while True:
                    where = (SA_PARENT + ' IN ('
                             + ','.join(_soql(key) for key in chunk) + ')'
                             + " AND Status IN ('Scheduled','Dispatched')"
                             + ' AND SchedStartTime >= ' + lo
                             + ' AND SchedStartTime < ' + hi)
                    if cursor:
                        where += ' AND Id > ' + _soql(cursor)
                    rows = self._query(
                        'SELECT Id,' + SA_PARENT + ' FROM '
                        + SERVICE_APPOINTMENT + ' WHERE ' + where
                        + ' ORDER BY Id LIMIT 2000')
                    for row in rows:
                        ident = _require_id(str(row.get('Id') or ''))
                        source_id = _require_id(str(row.get(SA_PARENT) or ''))
                        work_order = canonical.get(source_id[:15])
                        if work_order is None or ident in seen or (
                                cursor and ident <= cursor):
                            raise ResultingSalesforceError(
                                'Service Appointment identity or paging is invalid.')
                        seen.add(ident)
                        appointments[work_order].append(ident)
                    if len(rows) < 2000:
                        break
                    cursor = _require_id(str(rows[-1].get('Id') or ''))
        if any(not values or len(values) > 2000 for values in appointments.values()):
            raise ResultingSalesforceError(
                'No unique same-day Service Appointments for Work Order.')
        return appointments

    def _product_rows_for_batch(self, payloads):
        """Read existing PIR identities, dates and issued flags by Work Order."""
        expected = {
            _require_id(payload['work_order_id']): _require_id(payload['lead_id'])
            for payload in payloads
        }
        by_work = {key: [] for key in expected}
        seen = set()
        ids = list(expected)
        for offset in range(0, len(ids), 40):
            chunk = ids[offset:offset + 40]
            canonical = {ident[:15]: ident for ident in chunk}
            cursor = ''
            while True:
                where = PR['work_order'] + ' IN (' + ','.join(
                    _soql(ident) for ident in chunk) + ')'
                if cursor:
                    where += ' AND Id > ' + _soql(cursor)
                rows = self._query(
                    'SELECT Id,' + PR['work_order'] + ',' + PR['lead']
                    + ',' + PR['product'] + ',' + PR_ISSUED_COUNT
                    + ',' + PR_APPOINTMENT_DATE
                    + ' FROM ' + PRODUCT_RESULT + ' WHERE ' + where
                    + ' ORDER BY Id LIMIT 2000')
                for row in rows:
                    ident = _require_id(str(row.get('Id') or ''))
                    source_id = _require_id(str(row.get(PR['work_order']) or ''))
                    work_id = canonical.get(source_id[:15])
                    lead_id = _require_id(str(row.get(PR['lead']) or ''))
                    if (work_id is None or
                            expected[work_id][:15] != lead_id[:15] or
                            ident in seen or (cursor and ident <= cursor)):
                        raise ResultingSalesforceError(
                            'Product Interest Result identity or paging is invalid.')
                    seen.add(ident)
                    by_work[work_id].append(row)
                if len(rows) < 2000:
                    break
                cursor = _require_id(str(rows[-1].get('Id') or ''))
        return by_work

    def _lead_rows_for_batch(self, payloads, product_rows_by_work):
        """Load Lead attribution only for new PIRs; interests only for sales."""
        needs_attribution, needs_interest = set(), set()
        for payload in payloads:
            lead_id = _require_id(payload['lead_id'])
            work_id = _require_id(payload['work_order_id'])
            existing = {
                str(row.get(PR['product']) or '').casefold()
                for row in product_rows_by_work[work_id]
            }
            if any(str(item['product']).casefold() not in existing
                   for item in payload['product_results']):
                needs_attribution.add(lead_id)
            if any(item['result'] == 'sale' for item in payload['product_results']):
                needs_interest.add(lead_id)
        rows_by_lead = {}
        for leads, fields in (
            (sorted(needs_attribution),
             sorted(set(PIR_LEAD_COPY.values())) + [LEAD_FIELDS['product_interest']]),
            (sorted(needs_interest - needs_attribution),
             [LEAD_FIELDS['product_interest']]),
        ):
            for offset in range(0, len(leads), 40):
                chunk = leads[offset:offset + 40]
                canonical = {ident[:15]: ident for ident in chunk}
                found = self._query(
                    'SELECT Id,' + ','.join(fields) + ' FROM ' + LEAD
                    + ' WHERE Id IN (' + ','.join(_soql(key) for key in chunk)
                    + ') ORDER BY Id LIMIT 2000')
                for row in found:
                    source_id = _require_id(str(row.get('Id') or ''))
                    ident = canonical.get(source_id[:15])
                    if ident is None or ident in rows_by_lead:
                        raise ResultingSalesforceError(
                            'Lead preflight returned unexpected identities.')
                    rows_by_lead[ident] = row
                if any(key not in rows_by_lead for key in chunk):
                    raise ResultingSalesforceError(
                        'Lead preflight is incomplete; no writes were performed.')
        return rows_by_lead

    def _verify_flow_kill_switch(self):
        """Block writes unless the org's Result Appointment Flow is enabled.

        Flow v30 continues only when $Setup.trac_killswitch__c.trac_flows__c
        is false. Hierarchy overrides are not available in the normalized
        Stats contract; conservatively block if any returned scope is on or
        the effective setting cannot be established. Never guess it is off.
        """
        rows = self._query(
            'SELECT SetupOwnerId,trac_flows__c FROM trac_killswitch__c LIMIT 2000'
        )
        if (not rows or len(rows) == 2000 or
                any(type(row.get('trac_flows__c')) is not bool for row in rows)):
            raise ResultingSalesforceError(
                'Result Appointment Flow kill switch could not be verified; '
                'no Salesforce writes were made.')
        if any(row['trac_flows__c'] for row in rows):
            raise ResultingSalesforceError(
                'Result Appointment Flow kill switch is enabled; '
                'no Salesforce writes were made.')

    def prepare(self, payloads):
        """Preflight the complete batch before any live Salesforce write."""
        self._verify_flow_kill_switch()
        wo_schema = self._describe(WORK_ORDER)
        lead_schema = self._describe(LEAD)
        sa_schema = self._describe(SERVICE_APPOINTMENT)
        pr_schema = self._describe(PRODUCT_RESULT)

        sa_status = self._field(sa_schema, SA['status'], types=('picklist',))
        sa_work_order = self._field(
            sa_schema, SA_PARENT, update=False, types=('reference',)
        )
        if WORK_ORDER not in (sa_work_order.get('referenceTo') or []):
            raise ResultingSalesforceError(
                SERVICE_APPOINTMENT + '.' + SA_PARENT
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
            'promotion': ('boolean', 'string', 'textarea', 'picklist'),
            'start_price': ('currency', 'double', 'int', 'long'),
            'final_price': ('currency', 'double', 'int', 'long'),
            # WorkOrder.Deposit_Payment__c stores e.g. 500/159.50.
            'deposit': ('string', 'textarea'),
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
        history_by_lead = self._historical_by_lead(payloads)
        pending_dispositions = {
            _require_id(payload['work_order_id']): WORK_ORDER_DISPO[payload['dispo']]
            for payload in payloads
        }

        appointment_ids_by_work = self._appointments_for_batch(payloads)
        product_rows_by_work = self._product_rows_for_batch(payloads)
        lead_rows = self._lead_rows_for_batch(payloads, product_rows_by_work)
        operations = []
        # Different Work Orders can refer to the same Lead. Accumulate pivot
        # additions across the whole End of Day batch; never overwrite a pivot
        # added by an earlier Work Order in this same batch.
        lead_interest_in_batch = {}
        for payload in payloads:
            work_order_id = _require_id(payload['work_order_id'])
            lead_id = _require_id(payload['lead_id'])
            mod_id = _require_id(payload['mod_id'])
            appointment_ids = appointment_ids_by_work[work_order_id]

            appointment_status = self._choice(
                sa_status, payload['fields']['appointment_status']
            )
            # Flow v30 writes Product Interest Results before Service
            # Appointments and Work Orders. Resolve the complete plan during
            # read-only preflight, then submit all steps atomically.
            plan = self._product_operations(
                payload, pr_schema, lead_schema,
                existing_rows=product_rows_by_work[work_order_id],
                attribution_row=lead_rows.get(lead_id))
            plan.extend(
                ('update', SERVICE_APPOINTMENT, ident, {
                    SA['status']: appointment_status,
                }) for ident in appointment_ids
            )

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
                WO['need']: self._value(wo_fields['need'], payload['draft']['need']),
                WO['want']: self._value(wo_fields['want'], payload['draft']['want']),
            }
            source_values = payload['draft'].get('checkbox_values') or {}
            for key in ('docs', 'ninety_min', 'promotion'):
                entry = source_values.get(key)
                if entry is not None:
                    # An unchanged source value is deliberately omitted: do
                    # not replace a text "Completed" with a guessed "Yes".
                    if entry['edited']:
                        wo_values[WO[key]] = self._source_checkbox_value(
                            wo_fields[key], entry['value']
                        )
                elif key == 'promotion':
                    # Legacy boolean settings retain their original behavior.
                    # Never coerce an unchecked text/picklist to the string
                    # "False"; an explicit popup edit can clear/set it.
                    if wo_fields[key].get('type') == 'boolean':
                        wo_values[WO[key]] = payload['draft'][key]
                    elif payload['draft'][key]:
                        wo_values[WO[key]] = self._checked_yes(wo_fields[key])
                elif payload['draft'][key]:
                    wo_values[WO[key]] = self._checked_yes(wo_fields[key])
            review_source = source_values.get('review')
            if review_source is not None:
                if review_source['edited']:
                    review = self._field(
                        wo_schema, REVIEW_FIELD,
                        types=('boolean', 'string', 'textarea', 'picklist')
                    )
                    wo_values[REVIEW_FIELD] = self._source_checkbox_value(
                        review, review_source['value']
                    )
            elif payload['draft']['review']:
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
                # The Flow updates Price__c in a separate WorkOrder DML step
                # before its main WorkOrder update. Do not send it twice.
                plan.append(('update', WORK_ORDER, work_order_id, {
                    WO['final_price']: self._value(
                        wo_fields['final_price'], payload['fields']['price']['lowest'])
                }))
            if payload['deposit_payment'] != '':
                wo_values[WO['deposit']] = self._value(
                    wo_fields['deposit'], payload['deposit_payment']
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
            }
            for key in ('dnr', 'one_leg'):
                entry = source_values.get(key)
                if entry is not None:
                    if entry['edited']:
                        lead_values[LEAD_FIELDS[key]] = self._source_checkbox_value(
                            lead_fields[key], entry['value']
                        )
                else:
                    lead_values[LEAD_FIELDS[key]] = self._value(
                        lead_fields[key], payload['draft'][key]
                    )
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
                    current = str(
                        lead_rows[lead_id].get(LEAD_FIELDS['product_interest']) or '')
                merged, changed = self._merge_products(current, sold)
                lead_interest_in_batch[lead_id] = merged
                if changed:
                    lead_values[LEAD_FIELDS['product_interest']] = self._choice(
                        lead_fields['product_interest'], merged
                    ) if lead_fields['product_interest'].get('type') == 'multipicklist' else merged
            plan.append(('update', LEAD, lead_id, lead_values))
            operations.append(plan)
        # Reject an oversized Work Order before submitting any earlier
        # Work Orders from this End-of-Day batch. The ordered Composite API
        # supports at most 25 subrequests per atomic transaction.
        if any(len(plan) > 25 for plan in operations):
            raise ResultingSalesforceError(
                'A Work Order exceeds the Salesforce Composite 25-step limit.')
        return operations

    @staticmethod
    def _rest_error(body):
        """Extract a Salesforce subrequest failure without leaking credentials."""
        errors = body if isinstance(body, list) else (
            body.get('errors', [body]) if isinstance(body, dict) else [body]
        )
        details = []
        for item in errors:
            if isinstance(item, dict):
                code = str(item.get('errorCode') or item.get('name') or '').strip()
                reason = str(item.get('message') or '').strip()
                fields = item.get('fields') or ()
                field_names = ', '.join(str(v) for v in fields) if isinstance(
                    fields, list) else ''
                detail = (code + ': ' if code and reason else code) + reason
                if field_names:
                    detail += ' (' + field_names + ')'
            else:
                detail = str(item or '').strip()
            if detail:
                details.append(detail)
        result = '; '.join(details) or 'No Salesforce error details returned.'
        result = re.sub(r'(?i)\bBearer\s+[^\s,;]+', 'Bearer [REDACTED]', result)
        result = re.sub(
            r'(?i)\b(accessToken|sfdxAuthUrl|authorization)\s*[:=]\s*\S+',
            r'\1=[REDACTED]', result)
        return result[:380]

    def _rest_values(self, object_name, values):
        """Use Salesforce field types to serialize an existing preflight plan."""
        schema = self._describes.get(object_name)
        if not isinstance(schema, dict) or not isinstance(values, dict):
            raise ResultingSalesforceError(
                'Salesforce metadata is unavailable for the planned update.'
            )
        types = {
            field.get('name'): field.get('type')
            for field in schema.get('fields', [])
            if isinstance(field, dict)
        }
        result = {}
        for field, value in values.items():
            if not NAME_RE.fullmatch(field) or field not in types:
                raise ResultingSalesforceError(
                    'Unknown Salesforce write field on ' + object_name + '.')
            kind = types[field]
            if value is None:
                result[field] = None
            elif kind in ('currency', 'double', 'percent', 'int', 'long'):
                # The previous CLI path stringified numbers, but REST JSON
                # requires numeric types for currency and numeric fields.
                number = Decimal(str(value))
                if not number.is_finite():
                    raise ResultingSalesforceError('Invalid Salesforce amount.')
                if kind in ('int', 'long') and number != number.to_integral_value():
                    raise ResultingSalesforceError('Invalid integer amount.')
                result[field] = (
                    int(number) if number == number.to_integral_value()
                    else float(number)
                )
            else:
                result[field] = value
        return result

    def apply(self, operations):
        """Commit one Work Order atomically, in the existing plan order.

        Follow Flow v30: PIR -> SA -> optional WorkOrder price -> WorkOrder
        -> Lead. Composite allOrNone rolls back every operation if any step
        rejects the request. JSON preserves quoted/multiline MOD Notes.
        """
        if not operations or len(operations) > 25:
            raise ResultingSalesforceError(
                'Work Order requires between 1 and 25 Salesforce writes.'
            )
        version = '/services/data/v60.0'
        requests = []
        for index, (action, object_name, record_id, values) in enumerate(
                operations, 1):
            if object_name not in (
                    SERVICE_APPOINTMENT, WORK_ORDER, LEAD, PRODUCT_RESULT):
                raise ResultingSalesforceError('Unknown resulting object.')
            if action not in ('update', 'create'):
                raise ResultingSalesforceError('Unknown resulting operation.')
            if action == 'update':
                url = version + '/sobjects/' + object_name + '/' + _require_id(record_id)
            else:
                if record_id:
                    raise ResultingSalesforceError(
                        'A new Salesforce result cannot have an existing ID.')
                url = version + '/sobjects/' + object_name
            requests.append({
                'method': 'PATCH' if action == 'update' else 'POST',
                'url': url,
                'referenceId': 'step_' + str(index),
                'body': self._rest_values(object_name, values),
            })
        request_body = json.dumps({
            'allOrNone': True,
            'collateSubrequests': False,  # Preserve the existing Flow order.
            'compositeRequest': requests,
        }, ensure_ascii=False)
        response = self._run([
            'api', 'request', 'rest', version + '/composite',
            '--method', 'POST', '--body', '-',
            '--header', 'Content-Type: application/json',
        ], input_body=request_body, timeout=120)
        # sf api request rest --json returns the HTTP envelope inside its
        # CLI result: {statusCode, headers, body}. Salesforce puts
        # compositeResponse in that HTTP body, not at the result's top level.
        status_code = response.get('statusCode') if isinstance(response, dict) else None
        if type(status_code) is not int:
            raise ResultingSalesforceError(
                'Salesforce CLI returned an invalid Composite HTTP response; '
                'verify the Work Order before retrying.'
            )
        if status_code != 200:
            raise ResultingSalesforceError(
                'Salesforce Composite HTTP ' + str(status_code) + ': '
                + self._rest_error(response.get('body'))
            )
        body = response.get('body')
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except ValueError:
                body = None
        results = body.get('compositeResponse') if isinstance(body, dict) else None
        if not isinstance(results, list) or len(results) != len(requests):
            # Unknown transport outcome: the caller records an uncertain
            # receipt and must never blindly replay the Work Order.
            raise ResultingSalesforceError(
                'Salesforce Composite returned an incomplete response; '
                'verify the Work Order before retrying.'
            )
        by_ref = {}
        expected = {'step_' + str(i) for i in range(1, len(requests) + 1)}
        for item in results:
            if not isinstance(item, dict):
                raise ResultingSalesforceError(
                    'Salesforce Composite returned an invalid response.')
            reference = item.get('referenceId')
            if reference not in expected or reference in by_ref:
                raise ResultingSalesforceError(
                    'Salesforce Composite returned mismatched operations.')
            by_ref[reference] = item

        failures = []
        for index, step in enumerate(operations, 1):
            item = by_ref['step_' + str(index)]
            status = item.get('httpStatusCode')
            if type(status) is not int or not 200 <= status < 300:
                detail = self._rest_error(item.get('body'))
                failures.append((step, detail))
        if failures:
            # In an allOrNone rollback Salesforce can report a generic
            # ALL_OR_NONE_OPERATION_ROLLED_BACK/PROCESSING_HALTED for other
            # steps. Prefer the concrete root rejection if one exists.
            actual = next(
                ((step, detail) for step, detail in failures
                 if not any(code in detail for code in (
                     'ALL_OR_NONE_OPERATION_ROLLED_BACK',
                     'PROCESSING_HALTED'))),
                failures[0],
            )
            step, detail = actual
            raise ResultingSalesforceError(
                step[1] + ' ' + step[0] + ' rejected: ' + detail
            )
        # No success receipt can be issued until every expected subrequest
        # succeeds and Salesforce's response is complete.
