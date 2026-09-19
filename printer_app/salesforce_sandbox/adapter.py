"""Replaceable Salesforce CLI adapter for the MOD-sheet sandbox.

Only this module knows Salesforce object names, relationship paths, SOQL, or the
`sf` command. Access tokens are never returned to the application.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import shutil
import subprocess

from ..mod_sheet_contract import ModSheetRecord, SourceStatus


class SalesforceAdapterError(RuntimeError):
    pass


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


def _cli_path():
    found = shutil.which('sf')
    if found:
        return found
    home = Path.home()
    for candidate in (
        home / 'sf/bin/sf',
        home / '.local/bin/sf',
        home / '.local/share/sf/client/bin/sf',
        home / '.npm-global/bin/sf',
        Path('/usr/local/bin/sf'),
        Path('/usr/bin/sf'),
    ):
        if candidate.is_file():
            return str(candidate)
    return ''


class SalesforceCliAdapter:
    """Read-only Salesforce source using the Pi user's existing sf CLI login."""

    def __init__(self, runner=subprocess.run, executable=''):
        self._runner = runner
        self._executable = str(executable or '')

    def _run(self, args, timeout=30):
        executable = self._executable or _cli_path()
        if not executable:
            raise SalesforceAdapterError(
                'Salesforce CLI is not available to the printer web service user.'
            )
        try:
            result = self._runner(
                [executable, *args, '--json'],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SalesforceAdapterError('Salesforce CLI could not be started.') from exc

        try:
            payload = json.loads(result.stdout or '{}')
        except json.JSONDecodeError as exc:
            raise SalesforceAdapterError('Salesforce CLI returned an unreadable response.') from exc

        if result.returncode or payload.get('status') not in (0, None):
            message = payload.get('message')
            if not message and isinstance(payload.get('result'), dict):
                message = payload['result'].get('message')
            raise SalesforceAdapterError(str(message or 'Salesforce CLI request failed.')[:500])
        return payload.get('result') or {}

    @staticmethod
    def _target_args(target_org):
        target = str(target_org or '').strip()
        if not target:
            return []
        if len(target) > 254 or any(not c.isprintable() for c in target):
            raise SalesforceAdapterError('Invalid Salesforce org selection.')
        return ['--target-org', target]

    def orgs(self):
        """Return connected org choices without exposing tokens or auth material."""
        try:
            result = self._run(['org', 'list'], timeout=20)
        except SalesforceAdapterError:
            return []
        orgs = []
        for group in ('nonScratchOrgs', 'scratchOrgs', 'sandboxes', 'devHubs'):
            for item in result.get(group, []) if isinstance(result, dict) else []:
                if not isinstance(item, dict):
                    continue
                if str(item.get('connectedStatus', '')).lower() not in ('connected', ''):
                    continue
                username = str(item.get('username') or '')
                alias = str(item.get('alias') or '')
                key = alias or username
                if key and not any(row['value'] == key for row in orgs):
                    orgs.append({
                        'value': key,
                        'label': alias + (' — ' + username if username and alias else '') or username,
                        'default': bool(item.get('isDefaultUsername')),
                    })
        orgs.sort(key=lambda item: (not item['default'], item['label'].casefold()))
        return orgs

    def status(self, target_org=''):
        result = self._run(['org', 'display', *self._target_args(target_org)], timeout=20)
        # sf org display includes accessToken in JSON. Deliberately copy only
        # non-secret connection metadata into the application contract.
        username = str(result.get('username') or '')
        alias = str(result.get('alias') or '')
        instance = str(result.get('instanceUrl') or '')
        org_id = str(result.get('id') or '')
        return SourceStatus(
            connected=True,
            username=username,
            alias=alias,
            instance_url=instance,
            detail=('Org ' + org_id[-8:]) if org_id else 'Authenticated through Salesforce CLI',
        )

    def _describe(self, sobject, target_org=''):
        return self._run(
            ['sobject', 'describe', '--sobject', sobject, *self._target_args(target_org)],
            timeout=30,
        )

    @staticmethod
    def _field_by_label(description, label):
        wanted = label.casefold()
        for field in description.get('fields', []) if isinstance(description, dict) else []:
            if str(field.get('label') or '').casefold() == wanted:
                return field
        return None

    def _distinct_values(self, path, target_org=''):
        if not path:
            return ()
        query = (
            f'SELECT {path} FROM ServiceAppointment'
            f' WHERE {path} != null GROUP BY {path} ORDER BY {path} LIMIT 200'
        )
        try:
            result = self._run(
                ['data', 'query', '--query', query, *self._target_args(target_org)],
                timeout=45,
            )
        except SalesforceAdapterError:
            return ()
        values = []
        for row in result.get('records', []) if isinstance(result, dict) else []:
            value = _nested(row, path).strip()
            if value and value not in values:
                values.append(value)
        return tuple(values)

    def _portal_field(self, label, target_org=''):
        """Find the exact Salesforce field by its UI label, without hard-coding API names."""
        scopes = (
            ('ServiceAppointment', ''),
            ('WorkOrder', 'FSSK__FSK_Work_Order__r.'),
            ('Lead', 'FSSK__FSK_Work_Order__r.Lead__r.'),
        )
        for sobject, prefix in scopes:
            try:
                description = self._describe(sobject, target_org)
            except SalesforceAdapterError:
                continue
            field = self._field_by_label(description, label)
            if not field:
                continue
            path = prefix + str(field.get('name') or '')
            values = []
            for option in field.get('picklistValues', []) or []:
                if option.get('active', True):
                    value = str(option.get('value') or option.get('label') or '').strip()
                    if value and value not in values:
                        values.append(value)
            if not values:
                values.extend(self._distinct_values(path, target_org))
            return PortalField(label, path, tuple(values))
        return PortalField(label, '', ())

    def portal_fields(self, target_org=''):
        """Resolve the three controls shown by trac_MODSheetPortalController."""
        return {
            'market_segment': self._portal_field('Market Segment', target_org),
            'product_category': self._portal_field('Product Category', target_org),
            'source_type': self._portal_field('Source Type', target_org),
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
        target_org='',
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
        portal_fields = self.portal_fields(target_org)

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
            ['data', 'query', '--query', query, *self._target_args(target_org)],
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
                if not path or _nested(item, path).casefold() != wanted.casefold():
                    rejected = True
                    break
            if rejected:
                continue
            filtered.append(item)
            if len(filtered) >= limit:
                break

        appointment_ids = [str(item.get('Id') or '') for item in filtered if item.get('Id')]
        resources = self._assigned_resources(appointment_ids, target_org)

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

    def _assigned_resources(self, appointment_ids, target_org=''):
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
            ['data', 'query', '--query', query, *self._target_args(target_org)],
            timeout=45,
        )
        output = {}
        for item in result.get('records', []) if isinstance(result, dict) else []:
            appointment_id = str(item.get('ServiceAppointmentId') or '')
            name = _nested(item, 'ServiceResource.Name').strip()
            if appointment_id and name:
                output.setdefault(appointment_id, []).append(name)
        return output
