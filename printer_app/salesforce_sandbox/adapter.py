"""Replaceable Salesforce CLI adapter.

Only this module knows Salesforce object names, relationship paths, SOQL, or the
`sf` command. Access tokens are never returned to the application.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from ..mod_sheet_contract import ModSheetRecord, SourceStatus


class SalesforceAdapterError(RuntimeError):
    pass


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
        home / '.local/bin/sf',
        home / '.npm-global/bin/sf',
        Path('/usr/local/bin/sf'),
        Path('/usr/bin/sf'),
    ):
        if candidate.is_file():
            return str(candidate)
    return ''


class SalesforceCliAdapter:
    """Read-only Salesforce source using the Pi user's existing sf CLI login."""

    def __init__(self, runner=subprocess.run):
        self._runner = runner

    def _run(self, args, timeout=30):
        executable = _cli_path()
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
        instance = str(result.get('instanceUrl') or result.get('instanceUrl') or '')
        org_id = str(result.get('id') or '')
        return SourceStatus(
            connected=True,
            username=username,
            alias=alias,
            instance_url=instance,
            detail=('Org ' + org_id[-8:]) if org_id else 'Authenticated through Salesforce CLI',
        )

    def mod_sheets_today(self, target_org='', limit=100):
        limit = max(1, min(int(limit), 100))
        query = f"""SELECT
Id,
Local_Scheduled_Start_Time__c,
SchedStartTime,
FSSK__FSK_Work_Order__r.WorkOrderNumber,
FSSK__FSK_Work_Order__r.Street,
FSSK__FSK_Work_Order__r.City,
FSSK__FSK_Work_Order__r.State,
FSSK__FSK_Work_Order__r.PostalCode,
FSSK__FSK_Work_Order__r.WorkType.Name,
FSSK__FSK_Work_Order__r.Product_Interest__c,
FSSK__FSK_Work_Order__r.Lead__r.Name,
FSSK__FSK_Work_Order__r.Lead__r.Phone,
FSSK__FSK_Work_Order__r.Lead__r.Canvass_Set_By__r.Name,
FSSK__FSK_Work_Order__r.Lead__r.Set_By__r.Name,
FSSK__FSK_Work_Order__r.Lead__r.LeadSource,
FSSK__FSK_Work_Order__r.Lead__r.Sub_Source__c,
FSSK__FSK_Work_Order__r.Lead__r.Description
FROM ServiceAppointment
WHERE SchedStartTime = TODAY
ORDER BY SchedStartTime ASC
LIMIT {limit}"""
        result = self._run(
            ['data', 'query', '--query', query, *self._target_args(target_org)],
            timeout=45,
        )
        records = result.get('records', []) if isinstance(result, dict) else []
        appointment_ids = [str(item.get('Id') or '') for item in records if item.get('Id')]
        resources = self._assigned_resources(appointment_ids, target_org)

        normalized = []
        for item in records:
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
