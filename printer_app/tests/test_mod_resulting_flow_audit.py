"""Read-only verification invariants: Flow v30, SQLite and Salesforce CLI."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from printer_app.db import Database
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting import flow_audit
from printer_app.mod_resulting.repository import ResultingRepository
from printer_app.mod_resulting.salesforce_adapter import (
    ResultingSalesforceAdapter, ResultingSalesforceError,
    readonly_resulting_runner, PR_APPOINTMENT_DATE, PR_ISSUED_COUNT,
)


def _flow(tmp_path, version=30):
    record = {
        'status': 0,
        'result': {
            'Id': '301000000000001AAA',
            'MasterLabel': 'Result Appointment',
            'Status': 'Active',
            'VersionNumber': version,
            'Metadata': {
                'start': {'connector': {'targetReference': 'Check_Disposition'}},
                'decisions': [{
                    'name': 'Check_Disposition',
                    'rules': [
                        {'name': 'Sold',
                         'connector': {'targetReference': 'Write_Result'}},
                    ],
                    'defaultConnector': {'targetReference': 'Default_Result'},
                }],
                'recordUpdates': [{
                    'name': 'Write_Result',
                    'object': 'Product_Interest_Result__c',
                    'inputAssignments': [
                        {'field': 'PR_Appointment_Date__c',
                         'value': {'stringValue': 'private business value'}},
                        {'field': 'Include_in_Issued_Lead_Count__c'},
                    ],
                }],
            },
        },
    }
    path = tmp_path/'flow-v30.json'
    path.write_text(json.dumps(record), encoding='utf-8')
    return path


def test_flow_inventory_exact_version_and_no_flow_execution(tmp_path):
    data = flow_audit.inspect_flow(_flow(tmp_path))
    assert data['version'] == 30 and data['status'] == 'Active'
    assert data['start'] == 'Check_Disposition'
    assert data['element_counts'] == {'decisions':1,'recordUpdates':1}
    update = next(row for row in data['elements'] if row['kind'] == 'recordUpdates')
    assert update['object'] == 'Product_Interest_Result__c'
    assert update['fields'] == [
        'Include_in_Issued_Lead_Count__c', 'PR_Appointment_Date__c',
    ]
    assert 'private business value' not in json.dumps(data)
    assert {'PR_Appointment_Date__c', 'Include_in_Issued_Lead_Count__c'} <= set(
        data['referenced_custom_fields']
    )
    with pytest.raises(ValueError, match='Expected Flow version 30'):
        flow_audit.inspect_flow(_flow(tmp_path, version=31))


def test_flow_metadata_cannot_be_silently_missing(tmp_path):
    path = _flow(tmp_path)
    data = json.loads(path.read_text())
    data['result'].pop('Metadata')
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Metadata is missing'):
        flow_audit.inspect_flow(path)


def test_salesforce_describes_verify_new_fields_and_never_infer_types(tmp_path):
    from printer_app.mod_resulting.salesforce_adapter import (
        LEAD, LEAD_FIELDS, PR, PRODUCT_RESULT, SA, SERVICE_APPOINTMENT,
        WO, WORK_ORDER,
    )
    required = {
        WORK_ORDER: set(WO.values()),
        LEAD: set(LEAD_FIELDS.values()),
        SERVICE_APPOINTMENT: set(SA.values()),
        PRODUCT_RESULT: set(PR.values()) |
            {PR_ISSUED_COUNT, PR_APPOINTMENT_DATE},
    }
    for name, fields in required.items():
        data = {
            'status':0, 'result': {
                'name':name, 'fields': [
                    {'name':field, 'type':
                        'date' if field == PR_APPOINTMENT_DATE else
                        'boolean' if field == PR_ISSUED_COUNT else 'string',
                     'updateable':True, 'createable':True}
                    for field in fields
                ],
            },
        }
        (tmp_path/('describe-' + name + '.json')).write_text(json.dumps(data))
    result = flow_audit.inspect_schemas(tmp_path)
    assert not result['missing'] and not result['incompatible']
    assert len(result['fields']) == sum(len(fields) for fields in required.values())
    path = tmp_path/('describe-' + PRODUCT_RESULT + '.json')
    description = json.loads(path.read_text())
    next(field for field in description['result']['fields']
         if field['name'] == PR_APPOINTMENT_DATE)['updateable'] = False
    path.write_text(json.dumps(description))
    bad = flow_audit.inspect_schemas(tmp_path)
    assert any(PR_APPOINTMENT_DATE in issue for issue in bad['incompatible'])


def test_read_only_runner_cannot_send_mutations_or_non_select_queries(monkeypatch):
    calls = []
    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(stdout='{}', stderr='', returncode=0)
    import printer_app.mod_resulting.salesforce_adapter as sf
    monkeypatch.setattr(sf.subprocess, 'run', fake_run)

    readonly_resulting_runner(['sf','data','query','--query',
                              'SELECT Id FROM Lead'])
    readonly_resulting_runner(['sf','sobject','describe','--sobject','Lead'])
    assert len(calls) == 2
    for command in (
        ['sf','data','update','record','--sobject','Lead'],
        ['sf','data','create','record','--sobject','Lead'],
        ['sf','data','delete','record','--sobject','Lead'],
        ['sf','api','request','rest','--method','POST'],
        ['sf','data','query','--query','UPDATE Lead SET Status = X'],
        ['sf','data','query'],
    ):
        with pytest.raises(ResultingSalesforceError, match='Read-only audit'):
            readonly_resulting_runner(command)
    assert len(calls) == 2

    adapter = ResultingSalesforceAdapter(
        executable='sf', runner=readonly_resulting_runner)
    with pytest.raises(ResultingSalesforceError, match='Read-only audit'):
        adapter.apply([('update', 'Lead', '00Q000000000001AAA',
                        {'Status':'Nurturing'})])
    assert len(calls) == 2


def test_read_only_database_never_migrates_or_modifies_existing_state(tmp_path):
    path = tmp_path/'printer.db'
    with pytest.raises(FileNotFoundError):
        Database(path, read_only=True)
    writable = Database(path)
    writable.set('audit-unchanged','original')
    before = writable.one('SELECT value FROM meta WHERE key=?', ('audit-unchanged',))
    readonly = Database(path, read_only=True)
    assert readonly.get('audit-unchanged') == 'original'
    with pytest.raises(sqlite3.OperationalError):
        readonly.execute('UPDATE meta SET value=? WHERE key=?',
                         ('modified','audit-unchanged'))
    assert writable.one('SELECT value FROM meta WHERE key=?',
                        ('audit-unchanged',)) == before


def test_optional_local_preflight_uses_real_contract_but_read_only_runner(tmp_path, monkeypatch):
    day = '2026-10-29'
    db_path = tmp_path/'printer_app.db'
    repository = ResultingRepository(Database(db_path))
    source = ModSheetRecord(
        source_id='0WO000000000001AAA',
        lead_source_id='00Q000000000001AAA',
        work_order_number='00012345', product_interest='Roofing;Siding',
        work_type='Sales - Roofing',
    )
    repository.refresh(day, [source], {}, market_segment='Olympia')
    repository.select_mod(day, '005000000000001AAA', 'Test MOD')

    class SafeAdapter:
        def __init__(self, *args, **kwargs):
            assert kwargs['runner'] is readonly_resulting_runner

        def lead_appointment_dates(self, ids):
            assert ids == ['00Q000000000001AAA']
            return {'00Q000000000001AAA':day}

        def prepare(self, batch):
            assert len(batch) == 1
            assert batch[0]['product_results']
            return [[('update','WorkOrder','0WO000000000001AAA',
                      {'Dispo__c':'PNS'})]]

        def apply(self, *_args):
            raise AssertionError('Audit must not call apply')

    monkeypatch.setattr(flow_audit, 'ResultingSalesforceAdapter', SafeAdapter)
    result = flow_audit.preview_local_day(
        db_path, day=day, org='work', resulted_on=day)
    assert result['status'] == 'read_only'
    assert [item['scenario'] for item in result['scenarios']] == [
        'together-pns','together-cxl','single-sale',
        'multi-sale-second-first','result-individually',
    ]
    assert all(item['status'] == 'planned' for item in result['scenarios'])
    assert repository.day(day)['mod_user_id'] == '005000000000001AAA'
    # No submitted receipt or changed draft.
    assert repository.sheets(day)[0]['submitted_at'] is None
    assert repository.sheets(day)[0]['draft']['dispo'] == ''


def test_cli_offline_summary_never_initializes_salesforce(monkeypatch, tmp_path, capsys):
    path = _flow(tmp_path)
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Offline flow inspection must not open Salesforce')
    monkeypatch.setattr(flow_audit, 'ResultingSalesforceAdapter', forbidden)
    flow_audit.main(['--flow',str(path),'--skip-local-db'])
    printed = capsys.readouterr().out
    assert 'READ ONLY' in printed
    assert 'version 30' in printed
    assert 'No create/update/delete commands were executed.' in printed
    assert 'NOT proof' in printed


def test_export_script_only_uses_read_commands_and_syntax_is_valid():
    import subprocess
    script = Path(__file__).resolve().parents[2] / 'scripts' / 'mod-flow-v30-export.sh'
    assert subprocess.run(['bash', '-n', str(script)], capture_output=True).returncode == 0
    source = script.read_text(encoding='utf-8')
    assert 'sf data query --use-tooling-api' in source
    assert 'sf api request rest' in source and '--method GET' in source
    assert 'sf sobject describe' in source
    assert 'VersionNumber = 30' in source
    assert 'sf data update' not in source
    assert 'sf data create' not in source
    assert 'sf project deploy' not in source
    assert 'sf logic run' not in source
