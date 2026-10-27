"""Salesforce CLI adapter for MOD resulting.

The reader stays read-only. This independent writer discovers real field
metadata and refuses ambiguous mappings before any write is attempted.
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
            # Deliberately do not surface CLI output, which may contain credentials.
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

    def mod_users(self):
        rows = self._query(
            "SELECT Id,Name FROM User WHERE IsActive = true ORDER BY Name LIMIT 2000"
        )
        users = []
        for item in rows:
            ident = str(item.get('Id') or '')
            name = str(item.get('Name') or '').strip()
            if ID_RE.fullmatch(ident) and name:
                users.append({'id': ident, 'name': name})
        return users

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
    def _field(schema, label, *, required=True):
        fields = schema.get('fields', [])
        matches = [field for field in fields
                   if (field.get('label', '').casefold().strip() == label.casefold()
                       or field.get('name', '').casefold() == label.casefold())
                   and field.get('updateable') is True]
        if len(matches) != 1:
            if required:
                raise ResultingSalesforceError(
                    'Cannot uniquely map writable Salesforce field: ' + label
                    + ' on ' + str(schema.get('name', '?')) + '.')
            return None
        return matches[0]

    @staticmethod
    def _picklist(field, value):
        if not value:
            return ''
        if field.get('type') not in ('picklist', 'multipicklist'):
            return value
        options = {str(p.get('value', '')).casefold():p['value']
                   for p in field.get('picklistValues', [])
                   if isinstance(p, dict) and p.get('active', True) and p.get('value')}
        found = options.get(str(value).casefold())
        if found is None:
            raise ResultingSalesforceError(
                'Salesforce does not allow ' + str(value) + ' for ' + field['label'] + '.')
        return found

    @classmethod
    def _mapped(cls, schema, values, *, required=True):
        output = {}
        for label, value in values.items():
            if value is None:
                continue
            field = cls._field(schema, label, required=required)
            if field is None:
                continue
            kind = field.get('type')
            if kind == 'boolean':
                if type(value) is not bool:
                    raise ResultingSalesforceError(label + ' must be a checkbox.')
                value = value
            elif kind == 'reference':
                value = _require_id(value)
            elif kind in ('picklist','multipicklist'):
                value = cls._picklist(field, value)
            elif kind in ('currency','double','int','long'):
                if not re.fullmatch(r'\d+(?:\.\d{1,2})?', str(value)):
                    raise ResultingSalesforceError('Invalid numeric value for ' + label + '.')
            elif kind not in ('textarea','string','date','datetime','time','phone'):
                raise ResultingSalesforceError('Unsupported Salesforce type for ' + label + '.')
            output[field['name']] = value
        return output

    def _time_value(self, day, entered, field):
        if not entered:
            return None
        stamp = datetime.strptime(day + ' ' + entered, '%Y-%m-%d %I:%M %p')
        kind = field['type']
        if kind == 'datetime':
            return stamp.replace(tzinfo=self.zone).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        if kind == 'time':
            return stamp.strftime('%H:%M:%S.000Z')
        if kind in ('string','textarea'):
            return entered
        raise ResultingSalesforceError('Call time field type cannot be mapped safely.')

    def _appointment_ids(self, work_order_id, day):
        start = datetime.combine(date.fromisoformat(day), time.min, tzinfo=self.zone)
        end = start + timedelta(days=1)
        lo = start.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        hi = end.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        rows = self._query(
            'SELECT Id FROM ServiceAppointment WHERE '
            + 'FSSK__FSK_Work_Order__c = ' + _soql(work_order_id)
            + ' AND SchedStartTime >= ' + lo
            + ' AND SchedStartTime < ' + hi
            + ' ORDER BY Id LIMIT 2000')
        ids = [_require_id(str(row.get('Id') or '')) for row in rows]
        if not ids or len(set(ids)) != len(ids):
            raise ResultingSalesforceError('No unique same-day Service Appointments for Work Order.')
        return ids

    def _result_schema(self, wo_object):
        """Locate Product Interest Results using Salesforce metadata, never names guessed in core."""
        names = self._run(['sobject', 'list', '--sobject', 'all'])
        if not isinstance(names, list):
            raise ResultingSalesforceError('Salesforce did not list its result objects.')
        matches = []
        for name in names:
            if not isinstance(name, str) or not NAME_RE.fullmatch(name):
                continue
            normalized = re.sub(r'[^a-z]', '', name.casefold())
            if 'product' not in normalized or 'result' not in normalized:
                continue
            described = self._describe(name)
            label = str(described.get('label') or '').casefold()
            if 'product' in label and 'result' in label:
                matches.append(described)
        if len(matches) != 1:
            raise ResultingSalesforceError(
                'Product Interest Result object is not uniquely identified by Salesforce metadata.')
        schema = matches[0]
        lookup = [f for f in schema.get('fields', [])
                  if f.get('type') == 'reference' and wo_object in (f.get('referenceTo') or [])
                  and f.get('updateable') is True]
        if len(lookup) != 1:
            raise ResultingSalesforceError('Product results lack a unique Work Order relationship.')
        return schema, lookup[0]['name']

    def _product_operations(self, payload, schema, relation):
        product = self._field(schema, 'Product Interest')
        result_field = self._field(schema, 'Result')
        detail_field = self._field(schema, 'Result Detail', required=False)
        price_field = self._field(schema, 'Price Given', required=False)
        comment_field = self._field(schema, 'Comment', required=False)
        extra = {}
        for label,key in (('1 Leg Appointment','one_leg'),('Free Product Lead','free_lead'),
                          ('CXL At Lead','cxl_at_lead')):
            f = self._field(schema, label, required=False)
            if f:
                extra[f['name']] = payload['draft'][key]
            elif payload['draft'][key]:
                raise ResultingSalesforceError(
                    'Checked Salesforce field is not mapped: ' + label)
        if payload['draft']['notes'] and not comment_field:
            raise ResultingSalesforceError('Cannot map Product Result Comment.')
        if any(entry['result'] == 'sale' for entry in payload['product_results']):
            if not price_field:
                raise ResultingSalesforceError('Cannot map Product Result Price Given.')
            if not payload['fields']['price']['lowest']:
                raise ResultingSalesforceError('Sale requires a numeric Price Given.')
        existing = self._query('SELECT Id,'+product['name']+' FROM '+schema['name']+
            ' WHERE '+relation+' = '+_soql(payload['work_order_id'])+' LIMIT 2000')
        by_product = {}
        for record in existing:
            value = str(record.get(product['name']) or '').strip()
            if value in by_product:
                raise ResultingSalesforceError('Ambiguous existing result for product ' + value)
            by_product[value] = _require_id(str(record.get('Id') or ''))
        operations = []
        for entry in payload['product_results']:
            disposition = {'sale':'Sale','pns':'Pitch No Sale','np':'No Pitch',
                           'cxl':'Canceled','nra':'No Rep Available','oos':'Canceled'}[entry['result']]
            fields = {relation:payload['work_order_id'],
                      product['name']:self._picklist(product,entry['product']),
                      result_field['name']:self._picklist(result_field,disposition)}
            if entry['detail'] and detail_field:
                fields[detail_field['name']] = self._picklist(detail_field,entry['detail'])
            if entry['detail'] and not detail_field:
                raise ResultingSalesforceError('Result Detail cannot be mapped to Product Result.')
            if price_field and entry['result'] == 'sale':
                fields[price_field['name']] = payload['fields']['price']['lowest']
            if comment_field and payload['draft']['notes']:
                fields[comment_field['name']] = payload['draft']['notes']
            fields.update(extra)
            old_id = by_product.get(entry['product'])
            if old_id:
                fields.pop(relation, None)
                operations.append(('update',schema['name'],old_id,fields))
            else:
                for f in schema.get('fields', []):
                    if f['name'] in fields and not f.get('createable', False):
                        raise ResultingSalesforceError('Product Result cannot be created safely.')
                operations.append(('create',schema['name'],'',fields))
        return operations

    def prepare(self, payloads):
        """Preflight all records and metadata before permitting any write."""
        sa = self._describe('ServiceAppointment')
        ref = next((field for field in sa.get('fields', [])
                    if field.get('name') == 'FSSK__FSK_Work_Order__c'), None)
        if (not ref or ref.get('type') != 'reference' or
                len(ref.get('referenceTo') or []) != 1):
            raise ResultingSalesforceError('Cannot confirm Work Order object.')
        wo_name = ref['referenceTo'][0]
        wo = self._describe(wo_name)
        lead = self._describe('Lead')
        product, relation = self._result_schema(wo_name)
        operations = []
        for payload in payloads:
            work_order_id = _require_id(payload['work_order_id'])
            lead_id = _require_id(payload['lead_id'])
            user_id = _require_id(payload['mod_id'])
            sa_ids = self._appointment_ids(work_order_id,payload['day'])
            appointment = self._mapped(sa, {'Status':payload['fields']['appointment_status']})
            if len(appointment) != 1:
                raise ResultingSalesforceError('Service Appointment Status mapping failed.')
            op = [('update','ServiceAppointment',ident,appointment) for ident in sa_ids]

            if not payload['fields']['work_order_status']:
                raise ResultingSalesforceError('Work Order Status for this disposition is unresolved.')
            work_order_fields = self._mapped(wo, {
                'Status':payload['fields']['work_order_status'],
                'MOD':user_id,
                'MOD Notes': ('\n'.join(part for part in (
                    payload['draft']['numbers'], payload['draft']['notes'],
                    payload['final_redlines']) if part)).strip(),
            })
            # Additional MOD fields remain mapped by their exact Salesforce labels.
            for label,key in [('Need','need'),('Want','want')]:
                if payload['draft'][key]:
                    work_order_fields.update(self._mapped(wo,{label:payload['draft'][key]}))
            if payload['final_redlines']:
                review = self._field(wo, 'Review', required=False)
                if review:
                    work_order_fields.update(self._mapped(
                        wo, {'Review':payload['final_redlines']}))
            for label,key in [('Docs','docs'),('Promotion','promotion'),
                              ('Bid Sheet Submitted','bid_sheets'),
                              ('Pictures','pictures'),('Power Questions','power_questions'),
                              ('T Close','t_close'),('90 Min','ninety_min')]:
                field = self._field(wo,label,required=False)
                if field:
                    work_order_fields.update(self._mapped(wo,{label:payload['draft'][key]}))
                elif payload['draft'][key]:
                    raise ResultingSalesforceError('Checkbox field is not mapped: '+label)

            for label,key in [('Call 1','call_1'),('Call 2','call_2')]:
                if payload['draft'][key]:
                    f = self._field(wo,label)
                    work_order_fields[f['name']] = self._time_value(payload['day'],payload['draft'][key],f)
            if payload['fields']['price']['highest']:
                work_order_fields.update(self._mapped(
                    wo, {'Start Price':payload['fields']['price']['highest'],
                         'Final Price':payload['fields']['price']['lowest']}))
            # Existing Work Order/Lead binding is checked against stored snapshot.
            linked = self._query('SELECT Id,Lead__c FROM '+wo_name+
                                 ' WHERE Id = '+_soql(work_order_id)+' LIMIT 2')
            if len(linked) != 1 or str(linked[0].get('Lead__c') or '') != lead_id:
                raise ResultingSalesforceError('Work Order Lead changed; refresh before submitting.')
            op.append(('update',wo_name,work_order_id,work_order_fields))

            lead_fields = self._mapped(lead,{'Status':payload['fields']['lead_status']})
            if payload['fields']['previous_result']:
                lead_fields.update(self._mapped(
                    lead,{'Previous Result':payload['fields']['previous_result']}))
            if payload['draft']['dnr']:
                lead_fields.update(self._mapped(lead,{'DNR - Do Not Reset':True,
                                                     'DNR Reason':'DNR - '+payload['draft']['dnr_reason']}))
            op.append(('update','Lead',lead_id,lead_fields))
            op.extend(self._product_operations(payload,product,relation))
            operations.append(op)
        return operations

    def apply(self, operations):
        """Idempotent field updates; new product rows are rechecked on retry."""
        for action, object_name, record_id, values in operations:
            # Values are individual argv, never interpolated into a shell command.
            pairs = ' '.join(key+'='+shlex.quote('true' if value is True
                else 'false' if value is False else str(value))
                for key,value in values.items())
            if action == 'update':
                self._run(['data','update','record','--sobject',object_name,
                           '--record-id',_require_id(record_id),'--values',pairs])
            elif action == 'create':
                self._run(['data','create','record','--sobject',object_name,'--values',pairs])
            else:
                raise ResultingSalesforceError('Unknown resulting operation.')
