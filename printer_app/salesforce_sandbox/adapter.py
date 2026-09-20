"""Replaceable Salesforce CLI adapter for the MOD-sheet sandbox.

Only this module knows Salesforce object names, relationship paths, SOQL, or the
`sf` command. Downstream code receives normalized MOD records only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import getpass
import json
import re
import shlex
import subprocess
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..mod_sheet_contract import ModSheetRecord, SourceStatus


class SalesforceAdapterError(RuntimeError):
    pass


SOURCE_TYPE_ALL = (
    'Canvass',
    'Flyer',
    'Internet',
    'Other',
    'Previous Customer',
    'Referral',
    'Self Generated Lead',
    'Telemarketing',
    'Shows',
)

PRODUCT_CATEGORY_OPTIONS = (
    'Roofing',
    'Siding',
    'Bath',
    'Gutters',
    'Windows',
    'Doors',
    'Other',
    'Walk-In Tubs',
    'Solar',
)

PORTAL_FIELDS = {
    'market_segment': ('Market Segment', 'FSSK__FSK_Work_Order__r.Lead__r.Market__c'),
    'product_category': ('Product Category', 'FSSK__FSK_Work_Order__r.Product_Interest__c'),
    'source_type': ('Source Type', 'FSSK__FSK_Work_Order__r.Lead__r.LeadSource'),
}


def _safe_cli_detail(value):
    """Return the useful Node/Salesforce error without leaking credential values."""
    text = str(value or '')
    text = re.sub(
        r'(?i)(accessToken|sfdxAuthUrl|authorization|bearer)\s*[:=]\s*[^\s,;]+',
        r'\1=[REDACTED]',
        text,
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    useful = []
    for line in lines:
        lower = line.lower()
        if lower.startswith('node:events:') or line in ('^', "throw er; // Unhandled 'error' event"):
            continue
        if lower.startswith('at ') or lower.startswith("emitted 'error' event"):
            continue
        if (line.startswith('Error:') or 'code:' in line or 'syscall:' in line
                or 'path:' in line or 'errno:' in line):
            useful.append(line)
    if not useful:
        useful = [line for line in lines if not line.startswith('at ')][:3]
    return ' | '.join(useful[:4])[:700]


@dataclass(frozen=True)
class PortalField:
    label: str
    path: str
    values: tuple[str, ...]


def _nested(record, path):
    value = record
    for part in path.split('.'):
        if not isinstance(value, dict):
            return ''
        value = value.get(part)
    return '' if value is None else str(value)


def _address(work_order):
    # Match the Visualforce output literally: Street, City, State, PostalCode.
    return ', '.join([
        _nested(work_order, 'Street').strip(),
        _nested(work_order, 'City').strip(),
        _nested(work_order, 'State').strip(),
        _nested(work_order, 'PostalCode').strip(),
    ])


def _trace_command(parts):
    return ' '.join(shlex.quote(str(part)) for part in parts)


def _trace_note(trace, input_line, result, ok=True):
    if trace is not None:
        trace.append({
            'input': str(input_line),
            'result': str(result),
            'ok': bool(ok),
        })


def _soql_literal(value):
    value = str(value or '').replace('\\', '\\\\').replace("'", "\\'")
    return "'" + value + "'"


def _sf_datetime(value):
    value = str(value or '').strip()
    if not value:
        return None
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'
    elif re.search(r'[+-]\d{4}$', value):
        value = value[:-5] + value[-5:-2] + ':' + value[-2:]
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class SalesforceCliAdapter:
    """Read-only Salesforce source using the Pi user's existing sf CLI login."""

    def __init__(self, runner=subprocess.run, executable='/usr/bin/sf', target_org='work'):
        self._runner = runner
        self._executable = str(executable or '/usr/bin/sf')
        self.target_org = str(target_org or '').strip()
        if not self.target_org:
            raise ValueError('Salesforce target org alias is required.')
        self._portal_fields_cache = {}
        self._username = ''
        self._timezone = None

    def _run(self, args, timeout=30, trace=None):
        executable = self._executable
        command_parts = [executable, *args, '--json']
        trace_entry = None
        if trace is not None:
            trace_entry = {
                'input': _trace_command(command_parts),
                'result': 'running…',
                'ok': True,
            }
            trace.append(trace_entry)
        try:
            result = self._runner(
                command_parts,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            user = getpass.getuser() or 'unknown'
            message = f'Could not run {executable} as Linux user {user}: {exc}'
            if trace_entry is not None:
                trace_entry['result'] = message
                trace_entry['ok'] = False
            raise SalesforceAdapterError(message) from exc

        try:
            payload = json.loads(result.stdout or '{}')
        except json.JSONDecodeError as exc:
            detail = _safe_cli_detail(getattr(result, 'stderr', ''))
            user = getpass.getuser() or 'unknown'
            message = (
                f'Salesforce CLI failed for Linux user {user}: '
                + (detail or 'CLI returned non-JSON output')
            )
            if trace_entry is not None:
                trace_entry['result'] = message
                trace_entry['ok'] = False
            raise SalesforceAdapterError(message) from exc

        if result.returncode or payload.get('status') not in (0, None):
            message = str(payload.get('message') or '').strip()
            if not message and isinstance(payload.get('result'), dict):
                message = str(payload['result'].get('message') or '').strip()
            detail = _safe_cli_detail(getattr(result, 'stderr', ''))
            if not message or message.lower().startswith('node:events:'):
                message = detail
            else:
                message = _safe_cli_detail(message) or detail
            user = getpass.getuser() or 'unknown'
            command = ' '.join(str(part) for part in args[:2])
            full_message = (
                f'Salesforce CLI {command} failed for Linux user {user}: '
                + (message or 'no authenticated org was available')
            )
            if trace_entry is not None:
                trace_entry['result'] = full_message
                trace_entry['ok'] = False
            raise SalesforceAdapterError(full_message)
        if trace_entry is not None:
            trace_entry['result'] = 'status 0'
        return payload.get('result') or {}

    def _target_args(self):
        return ['--target-org', self.target_org]

    def status(self, trace=None):
        result = self._run(
            ['org', 'display', *self._target_args()],
            timeout=20,
            trace=trace,
        )
        username = str(result.get('username') or '')
        alias = str(result.get('alias') or '')
        instance = str(result.get('instanceUrl') or '')
        org_id = str(result.get('id') or '')
        self._username = username
        if trace:
            trace[-1]['result'] = json.dumps({
                'connectedStatus': str(result.get('connectedStatus') or 'Connected'),
                'username': username,
                'alias': alias,
                'instanceUrl': instance,
            }, separators=(',', ':'))
        return SourceStatus(
            connected=True,
            username=username,
            alias=alias,
            instance_url=instance,
            detail=('Org ' + org_id[-8:]) if org_id else 'Authenticated through Salesforce CLI',
        )

    def _salesforce_timezone(self):
        if self._timezone is not None:
            return self._timezone
        if not self._username:
            self.status()
        query = (
            'SELECT TimeZoneSidKey FROM User WHERE Username = '
            + _soql_literal(self._username)
            + ' LIMIT 1'
        )
        result = self._run(
            ['data', 'query', '--query', query, *self._target_args()],
            timeout=30,
        )
        records = result.get('records', []) if isinstance(result, dict) else []
        zone_name = str(records[0].get('TimeZoneSidKey') or '') if records else ''
        if not zone_name:
            raise SalesforceAdapterError('Salesforce user timezone could not be resolved.')
        try:
            self._timezone = ZoneInfo(zone_name)
        except ZoneInfoNotFoundError as exc:
            raise SalesforceAdapterError(
                f'Salesforce user timezone is not available on this device: {zone_name}'
            ) from exc
        return self._timezone

    def _distinct_values(self, path, trace=None):
        query = (
            f'SELECT {path} FROM ServiceAppointment '
            "WHERE WorkType.Name LIKE '%Sales%' "
            'LIMIT 1000'
        )
        try:
            result = self._run(
                ['data', 'query', '--query', query, *self._target_args()],
                timeout=45,
                trace=trace,
            )
        except SalesforceAdapterError:
            return ()
        values = []
        for row in result.get('records', []) if isinstance(result, dict) else []:
            raw = _nested(row, path).strip()
            for value in (part.strip() for part in raw.split(';')):
                if value and value not in values:
                    values.append(value)
        values.sort(key=str.casefold)
        if trace:
            trace[-1]['result'] = 'status 0 · values ' + json.dumps(values)
        return tuple(values)

    def portal_field(self, key, trace=None):
        if key not in PORTAL_FIELDS:
            raise SalesforceAdapterError(f'Unknown Salesforce portal field: {key}')
        cached = self._portal_fields_cache.get(key)
        if cached is not None:
            _trace_note(trace, f'# cached field {cached.label}', 'cache hit')
            return cached

        label, path = PORTAL_FIELDS[key]
        if key == 'source_type':
            values = SOURCE_TYPE_ALL
        elif key == 'product_category':
            values = PRODUCT_CATEGORY_OPTIONS
        else:
            values = self._distinct_values(path, trace)
        resolved = PortalField(label, path, tuple(values))
        self._portal_fields_cache[key] = resolved
        _trace_note(
            trace,
            f'# resolve {resolved.label}',
            f'{resolved.path} · ' + json.dumps(list(resolved.values)),
            ok=True,
        )
        return resolved

    def portal_fields(self):
        return {
            key: self.portal_field(key)
            for key in ('market_segment', 'product_category', 'source_type')
        }

    @staticmethod
    def _parse_date(value):
        value = str(value or '').strip()
        for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d'):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                pass
        raise SalesforceAdapterError('Use dates in M/D/YYYY format.')

    def mod_sheets(
        self,
        *,
        start_date='',
        end_date='',
        market_segment='',
        product_category='',
        source_type='',
        remove_canceled=True,
        remove_unconfirmed=True,
        limit=1000,
    ):
        start = self._parse_date(start_date)
        end = self._parse_date(end_date)
        if end < start:
            raise SalesforceAdapterError('End Date must be on or after Start Date.')
        limit = max(1, min(int(limit), 1000))
        user_zone = self._salesforce_timezone()

        select_fields = [
            'Id',
            'FSSK__FSK_Work_Order__r.WorkOrderNumber',
            'FSSK__FSK_Work_Order__r.Address',
            'Local_Scheduled_Start_Time__c',
            'FSSK__FSK_Work_Order__r.City',
            'FSSK__FSK_Work_Order__r.Street',
            'FSSK__FSK_Work_Order__r.State',
            'FSSK__FSK_Work_Order__r.PostalCode',
            'FSSK__FSK_Work_Order__r.Lead__r.Name',
            'FSSK__FSK_Work_Order__r.Lead__r.Phone',
            'FSSK__FSK_Work_Order__r.Lead__r.Phone_3__c',
            'SchedStartTime',
            'SchedEndTime',
            'CreatedDate',
            'FSSK__FSK_Work_Order__c',
            'FSSK__FSK_Work_Order__r.Product_Interest__c',
            'FSSK__FSK_Assigned_Service_Resource__r.Name',
            'FSSK__FSK_Work_Order__r.Lead__r.LeadSource',
            'FSSK__FSK_Work_Order__r.Lead__r.Sub_Source__c',
            'FSSK__FSK_Work_Order__r.Lead__r.Set_By__r.Name',
            'FSSK__FSK_Work_Order__r.WorkType.Name',
            'FSSK__FSK_Work_Order__r.Lead__r.Description',
            'FSSK__FSK_Work_Order__r.Lead__r.Canvass_Set_By__r.Name',
        ]

        query_start = start - timedelta(days=1)
        query_end = end + timedelta(days=2)
        conditions = [
            "WorkType.Name LIKE '%Sales%'",
            f'SchedStartTime >= {query_start.isoformat()}T00:00:00Z',
            f'SchedStartTime < {query_end.isoformat()}T00:00:00Z',
        ]

        market_segment = str(market_segment or '').strip()
        product_category = str(product_category or '').strip()
        source_type = str(source_type or '').strip()

        if product_category and product_category.casefold() != 'all':
            conditions.append(
                'FSSK__FSK_Work_Order__r.Product_Interest__c INCLUDES '
                f'({_soql_literal(product_category)})'
            )
        if market_segment:
            conditions.append(
                'FSSK__FSK_Work_Order__r.Lead__r.Market__c = '
                + _soql_literal(market_segment)
            )
        if source_type:
            if source_type.casefold() == 'all':
                allowed = ', '.join(_soql_literal(value) for value in SOURCE_TYPE_ALL)
                conditions.append(
                    'FSSK__FSK_Work_Order__r.Lead__r.LeadSource IN (' + allowed + ')'
                )
            else:
                conditions.append(
                    'FSSK__FSK_Work_Order__r.Lead__r.LeadSource = '
                    + _soql_literal(source_type)
                )
        if remove_canceled:
            conditions.append("FSSK__FSK_Work_Order__r.Lead__r.Status != 'Canceled'")
        if remove_unconfirmed:
            conditions.append('FSSK__FSK_Work_Order__r.Lead__r.LastModifiedDate != null')

        query = (
            'SELECT ' + ', '.join(select_fields)
            + ' FROM ServiceAppointment WHERE '
            + ' AND '.join(conditions)
            + ' ORDER BY SchedStartTime, FSSK__FSK_Work_Order__r.Lead__r.Name ASC'
            + f' LIMIT {limit}'
        )
        result = self._run(
            ['data', 'query', '--query', query, *self._target_args()],
            timeout=60,
        )
        records = result.get('records', []) if isinstance(result, dict) else []
        if not records:
            raise SalesforceAdapterError('No Records Found for Selected Criteria')

        start_local = datetime.combine(start, time.min, tzinfo=user_zone)
        end_local = datetime.combine(end, time(23, 59), tzinfo=user_zone)
        grouped = {}
        order = []

        for item in records:
            scheduled = _sf_datetime(item.get('SchedStartTime'))
            if scheduled is None:
                continue
            local_start = scheduled.astimezone(user_zone)
            if not (start_local <= local_start <= end_local):
                continue

            work_order_id = str(item.get('FSSK__FSK_Work_Order__c') or '').strip()
            if not work_order_id:
                continue
            resource = _nested(item, 'FSSK__FSK_Assigned_Service_Resource__r.Name').strip()
            created = _sf_datetime(item.get('CreatedDate')) or datetime.max.replace(tzinfo=timezone.utc)

            current = grouped.get(work_order_id)
            if current is None:
                order.append(work_order_id)
                grouped[work_order_id] = {
                    'item': item,
                    'created': created,
                    'local_start': local_start,
                    'resources': [resource] if resource else [],
                }
                continue

            if resource and resource not in current['resources']:
                current['resources'].append(resource)
            if created < current['created']:
                current['item'] = item
                current['created'] = created
                current['local_start'] = local_start

        if not grouped:
            raise SalesforceAdapterError('No Records Found for Selected Criteria')

        normalized = []
        for work_order_id in order:
            grouped_item = grouped[work_order_id]
            item = grouped_item['item']
            work_order = item.get('FSSK__FSK_Work_Order__r') or {}
            lead = work_order.get('Lead__r') or {} if isinstance(work_order, dict) else {}
            normalized.append(ModSheetRecord(
                source_id=work_order_id,
                work_order_number=_nested(work_order, 'WorkOrderNumber'),
                local_scheduled_start_time=str(item.get('Local_Scheduled_Start_Time__c') or ''),
                canvass_set_by=_nested(lead, 'Canvass_Set_By__r.Name'),
                lead_name=_nested(lead, 'Name'),
                address=_address(work_order),
                phone=_nested(lead, 'Phone'),
                scheduled_start=grouped_item['local_start'].strftime('%Y.%m.%d ; %I:%M:%S %p'),
                assigned_service_resources=tuple(grouped_item['resources']),
                set_by=_nested(lead, 'Set_By__r.Name'),
                work_type=_nested(work_order, 'WorkType.Name'),
                product_interest=_nested(work_order, 'Product_Interest__c'),
                source=_nested(lead, 'LeadSource'),
                sub_source=_nested(lead, 'Sub_Source__c'),
                lead_description=_nested(lead, 'Description'),
            ))
        return normalized
