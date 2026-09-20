"""Replaceable Salesforce CLI adapter for the MOD-sheet sandbox.

Only this module knows Salesforce object names, relationship paths, SOQL, or the
`sf` command. Access tokens are never returned to the application.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import getpass
import re
import shlex
import subprocess

from ..mod_sheet_contract import ModSheetRecord, SourceStatus


class SalesforceAdapterError(RuntimeError):
    pass


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
    parts = [
        _nested(work_order, 'Street'),
        _nested(work_order, 'City'),
        _nested(work_order, 'State'),
        _nested(work_order, 'PostalCode'),
    ]
    return ', '.join(part.strip() for part in parts if part and part.strip())


def _trace_command(parts):
    return ' '.join(shlex.quote(str(part)) for part in parts)


def _trace_note(trace, input_line, result, ok=True):
    if trace is not None:
        trace.append({
            'input': str(input_line),
            'result': str(result),
            'ok': bool(ok),
        })


class SalesforceCliAdapter:
    """Read-only Salesforce source using the Pi user's existing sf CLI login."""

    def __init__(self, runner=subprocess.run, executable='/usr/bin/sf', target_org='work'):
        self._runner = runner
        self._executable = str(executable or '/usr/bin/sf')
        self.target_org = str(target_org or '').strip()
        if not self.target_org:
            raise ValueError('Salesforce target org alias is required.')
        self._portal_fields_cache = {}

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
            # "node:events:NNN" is only Node's generic crash header; the useful
            # cause is normally on the following Error/code/syscall lines.
            if not message or message.lower().startswith('node:events:'):
                message = detail
            else:
                message = _safe_cli_detail(message) or detail
            user = getpass.getuser() or 'unknown'
            command = ' '.join(str(part) for part in args[:2])
            full_message = (
                f'Salesforce CLI {command} failed for Linux user {user}: '
                + (message or 'no authenticated/default org was available')
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
        # sf org display includes accessToken in JSON. Deliberately copy only
        # non-secret connection metadata into the application contract.
        username = str(result.get('username') or '')
        alias = str(result.get('alias') or '')
        instance = str(result.get('instanceUrl') or '')
        org_id = str(result.get('id') or '')
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

    def _distinct_values(self, path, trace=None):
        if not path:
            return ()
        query = f'SELECT {path} FROM ServiceAppointment LIMIT 1000'
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
        """Return one MOD portal filter using the Salesforce fields used by the Apex report."""
        contracts = {
            'market_segment': PortalField(
                'Market Segment',
                'FSSK__FSK_Work_Order__r.Lead__r.Market__c',
                (),
            ),
            'product_category': PortalField(
                'Product Category',
                'FSSK__FSK_Work_Order__r.Product_Interest__c',
                (),
            ),
            'source_type': PortalField(
                'Source Type',
                'FSSK__FSK_Work_Order__r.Lead__r.LeadSource',
                (
                    'Canvass',
                    'Flyer',
                    'Internet',
                    'Other',
                    'Previous Customer',
                    'Referral',
                    'Self Generated Lead',
                    'Telemarketing',
                    'Shows',
                ),
            ),
        }
        if key not in contracts:
            raise SalesforceAdapterError(f'Unknown Salesforce portal field: {key}')
        cached = self._portal_fields_cache.get(key)
        if cached is not None:
            _trace_note(trace, f'# cached field {cached.label}', 'cache hit')
            return cached

        contract = contracts[key]
        values = contract.values or self._distinct_values(contract.path, trace=trace)
        resolved = PortalField(contract.label, contract.path, tuple(values))
        self._portal_fields_cache[key] = resolved
        _trace_note(
            trace,
            f'# resolve {resolved.label}',
            f'{resolved.path} · ' + json.dumps(list(resolved.values)),
            ok=True,
        )
        return resolved

    def portal_fields(self):
        """Resolve all portal controls for PDF generation, reusing the same cache."""
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
        if (end - start).days > 366:
            raise SalesforceAdapterError('Choose a date range of 367 days or less.')
        limit = max(1, min(int(limit), 1000))
        portal_fields = self.portal_fields()

        dynamic_paths = [
            portal_fields[key].path
            for key in ('market_segment', 'product_category', 'source_type')
            if portal_fields[key].path
        ]
        select_fields = [
            'Id',
            'Status',
            'Local_Scheduled_Start_Time__c',
            'SchedStartTime',
            'FSSK__FSK_Work_Order__r.WorkOrderNumber',
            'FSSK__FSK_Work_Order__r.Street',
            'FSSK__FSK_Work_Order__r.City',
            'FSSK__FSK_Work_Order__r.State',
            'FSSK__FSK_Work_Order__r.PostalCode',
            'FSSK__FSK_Work_Order__r.WorkType.Name',
            'FSSK__FSK_Work_Order__r.Product_Interest__c',
            'FSSK__FSK_Work_Order__r.Lead__r.Name',
            'FSSK__FSK_Work_Order__r.Lead__r.Phone',
            'FSSK__FSK_Work_Order__r.Lead__r.Canvass_Set_By__r.Name',
            'FSSK__FSK_Work_Order__r.Lead__r.Set_By__r.Name',
            'FSSK__FSK_Work_Order__r.Lead__r.LeadSource',
            'FSSK__FSK_Work_Order__r.Lead__r.Sub_Source__c',
            'FSSK__FSK_Work_Order__r.Lead__r.Description',
        ]
        for path in dynamic_paths:
            if path not in select_fields:
                select_fields.append(path)

        # Query one extra local-calendar day on each side, then apply the final
        # local date boundary below. This avoids silently dropping edge appointments
        # when the Salesforce org/user timezone differs from UTC.
        query_start = start - timedelta(days=1)
        query_end = end + timedelta(days=2)
        query = (
            'SELECT ' + ', '.join(select_fields)
            + ' FROM ServiceAppointment'
            + f' WHERE SchedStartTime >= {query_start.isoformat()}T00:00:00Z'
            + f' AND SchedStartTime < {query_end.isoformat()}T00:00:00Z'
            + ' ORDER BY SchedStartTime ASC'
            + ' LIMIT 2000'
        )
        result = self._run(
            ['data', 'query', '--query', query, *self._target_args()],
            timeout=60,
        )
        records = result.get('records', []) if isinstance(result, dict) else []

        selected = {
            'market_segment': str(market_segment or '').strip(),
            'product_category': str(product_category or '').strip(),
            'source_type': str(source_type or '').strip(),
        }
        filtered = []
        for item in records:
            status = str(item.get('Status') or '').casefold()
            if remove_canceled and 'cancel' in status:
                continue
            if remove_unconfirmed and 'unconfirm' in status:
                continue

            scheduled = str(item.get('SchedStartTime') or '')
            try:
                scheduled_date = date.fromisoformat(scheduled[:10])
            except ValueError:
                scheduled_date = None
            if scheduled_date and not (start <= scheduled_date <= end):
                continue

            rejected = False
            for key, wanted in selected.items():
                if not wanted:
                    continue
                path = portal_fields[key].path
                actual = _nested(item, path)
                if key == 'product_category':
                    choices = [part.strip().casefold() for part in actual.split(';') if part.strip()]
                    matched = wanted.casefold() in choices
                else:
                    matched = actual.casefold() == wanted.casefold()
                if not path or not matched:
                    rejected = True
                    break
            if rejected:
                continue
            filtered.append(item)
            if len(filtered) >= limit:
                break

        appointment_ids = [str(item.get('Id') or '') for item in filtered if item.get('Id')]
        resources = self._assigned_resources(appointment_ids)

        normalized = []
        for item in filtered:
            work_order = item.get('FSSK__FSK_Work_Order__r') or {}
            lead = work_order.get('Lead__r') or {} if isinstance(work_order, dict) else {}
            appointment_id = str(item.get('Id') or '')
            normalized.append(ModSheetRecord(
                source_id=appointment_id,
                work_order_number=_nested(work_order, 'WorkOrderNumber'),
                local_scheduled_start_time=str(item.get('Local_Scheduled_Start_Time__c') or ''),
                canvass_set_by=_nested(lead, 'Canvass_Set_By__r.Name'),
                lead_name=_nested(lead, 'Name'),
                address=_address(work_order),
                phone=_nested(lead, 'Phone'),
                scheduled_start=str(item.get('SchedStartTime') or ''),
                assigned_service_resources=tuple(resources.get(appointment_id, ())),
                set_by=_nested(lead, 'Set_By__r.Name'),
                work_type=_nested(work_order, 'WorkType.Name'),
                product_interest=_nested(work_order, 'Product_Interest__c'),
                source=_nested(lead, 'LeadSource'),
                sub_source=_nested(lead, 'Sub_Source__c'),
                lead_description=_nested(lead, 'Description'),
            ))
        return normalized

    def _assigned_resources(self, appointment_ids):
        if not appointment_ids:
            return {}
        safe_ids = [value for value in appointment_ids
                    if value and len(value) <= 20 and value.replace('_', '').isalnum()]
        if not safe_ids:
            return {}
        ids = ','.join("'" + value + "'" for value in safe_ids)
        query = f"""SELECT ServiceAppointmentId, ServiceResource.Name
FROM AssignedResource
WHERE ServiceAppointmentId IN ({ids})
ORDER BY ServiceAppointmentId, CreatedDate"""
        result = self._run(
            ['data', 'query', '--query', query, *self._target_args()],
            timeout=45,
        )
        output = {}
        for item in result.get('records', []) if isinstance(result, dict) else []:
            appointment_id = str(item.get('ServiceAppointmentId') or '')
            name = _nested(item, 'ServiceResource.Name').strip()
            if appointment_id and name:
                output.setdefault(appointment_id, []).append(name)
        return output
