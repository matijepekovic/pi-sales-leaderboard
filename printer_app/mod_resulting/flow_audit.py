"""Read-only Flow v30 audit of the existing MOD resulting contract.

This command never submits, enqueues, refreshes or updates an appointment.
Salesforce calls are restricted to describe/SELECT by the adapter-owned runner;
SQLite is opened without migrations and with query_only enabled. A report is
not an assertion that downstream Salesforce automation matches the Flow.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
import json
import os
from pathlib import Path
import re
import shutil
from zoneinfo import ZoneInfo

from ..config import environment_file, parse_env
from ..db import Database
from .contract import clean_draft
from .repository import ResultingRepository
from .salesforce_adapter import (
    LEAD, LEAD_FIELDS, PR, PR_APPOINTMENT_DATE, PR_ISSUED_COUNT,
    PRODUCT_RESULT, SA, SERVICE_APPOINTMENT, WO, WORK_ORDER,
    ResultingSalesforceAdapter, readonly_resulting_runner,
)
from .service import ResultingService

FLOW_VERSION = 30
FLOW_ELEMENTS = (
    'actionCalls', 'assignments', 'collectionProcessors', 'decisions',
    'loops', 'recordCreates', 'recordDeletes', 'recordLookups', 'recordUpdates',
    'screens', 'subflows', 'transforms', 'waits',
)
FLOW_FIELDS = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*__c\b')


def _unwrap(value):
    if not isinstance(value, dict):
        raise ValueError('Expected a Salesforce JSON object.')
    if 'result' in value and isinstance(value['result'], dict):
        if value.get('status') not in (0, None):
            raise ValueError('The Salesforce CLI request did not succeed.')
        return value['result']
    return value


def inspect_flow(path):
    """Inventory exact version and graph elements without invoking any Flow."""
    record = _unwrap(json.loads(Path(path).read_text(encoding='utf-8')))
    version = record.get('VersionNumber', record.get('versionNumber'))
    try:
        version = int(version)
    except (TypeError, ValueError) as exc:
        raise ValueError('Flow version is missing: cannot verify version 30.') from exc
    if version != FLOW_VERSION:
        raise ValueError(f'Expected Flow version 30, got {version}.')
    metadata = record.get('Metadata', record.get('metadata'))
    if not isinstance(metadata, dict):
        raise ValueError('Flow v30 Metadata is missing; a list query is not enough.')
    if not metadata:
        raise ValueError('Flow v30 Metadata is empty.')
    elements = []
    for kind in FLOW_ELEMENTS:
        nodes = metadata.get(kind) or []
        if isinstance(nodes, dict):
            nodes = [nodes]
        if not isinstance(nodes, list):
            raise ValueError('Invalid Flow element collection: ' + kind)
        for node in nodes:
            if not isinstance(node, dict):
                raise ValueError('Invalid Flow element: ' + kind)
            # These are field API identifiers and graph names, never literal
            # customer data or hardcoded Flow input values.
            fields = set()
            for key in ('inputAssignments', 'filters', 'assignmentItems'):
                items = node.get(key) or []
                if isinstance(items, dict):
                    items = [items]
                for entry in items if isinstance(items, list) else []:
                    if isinstance(entry, dict):
                        for attribute in ('field', 'assignToReference'):
                            value = entry.get(attribute)
                            if isinstance(value, str):
                                fields.add(value)
            connectors = set()
            def collect_connectors(value):
                if isinstance(value, dict):
                    target = value.get('targetReference')
                    if isinstance(target, str):
                        connectors.add(target)
                    for nested in value.values():
                        collect_connectors(nested)
                elif isinstance(value, list):
                    for nested in value:
                        collect_connectors(nested)
            for name in ('connector', 'defaultConnector', 'rules',
                         'nextValueConnector', 'noMoreValuesConnector'):
                collect_connectors(node.get(name))
            rule_names = [
                rule['name'] for rule in (node.get('rules') or [])
                if isinstance(rule, dict) and isinstance(rule.get('name'), str)
            ] if isinstance(node.get('rules'), list) else []
            elements.append({
                'kind': kind,
                'name': str(node.get('name', '')),
                'object': str(node.get('object') or ''),
                'fields': sorted(fields),
                'targets': sorted(connectors),
                'rules': rule_names,
            })
    raw = json.dumps(metadata, ensure_ascii=True)
    flow_fields = sorted(set(FLOW_FIELDS.findall(raw)))
    return {
        'label': str(record.get('MasterLabel', record.get('masterLabel', ''))),
        'version': version,
        'status': str(record.get('Status', record.get('status', ''))),
        'start': (metadata.get('start') or {}).get('connector', {}).get(
            'targetReference', '') if isinstance(metadata.get('start'), dict) else '',
        'elements': elements,
        'referenced_custom_fields': flow_fields,
        'element_counts': dict(sorted(Counter(
            item['kind'] for item in elements).items())),
    }


def inspect_schemas(directory):
    """Check exact current Stats adapter field names against org describes."""
    required = {
        WORK_ORDER: set(WO.values()),
        LEAD: set(LEAD_FIELDS.values()),
        SERVICE_APPOINTMENT: set(SA.values()),
        PRODUCT_RESULT: set(PR.values()) |
            {PR_ISSUED_COUNT, PR_APPOINTMENT_DATE},
    }
    found, missing, unreadable = {}, [], []
    for object_name, api_fields in required.items():
        source = Path(directory) / ('describe-' + object_name + '.json')
        if not source.is_file():
            missing.append('Missing schema export: ' + object_name)
            continue
        schema = _unwrap(json.loads(source.read_text(encoding='utf-8')))
        if schema.get('name') != object_name or not isinstance(schema.get('fields'), list):
            raise ValueError('Unexpected Salesforce describe response: ' + object_name)
        members = {
            field['name']: field for field in schema['fields']
            if isinstance(field, dict) and isinstance(field.get('name'), str)
        }
        for field in sorted(api_fields):
            entry = members.get(field)
            if entry is None:
                missing.append(object_name + '.' + field)
                continue
            result = {
                'type': entry.get('type'),
                'updateable': entry.get('updateable') is True,
                'createable': entry.get('createable') is True,
            }
            found[object_name + '.' + field] = result
            if object_name == PRODUCT_RESULT and field == PR_ISSUED_COUNT:
                if result['type'] != 'boolean' or not result['updateable']:
                    unreadable.append(object_name + '.' + field
                                      + ' must be an editable boolean.')
            if object_name == PRODUCT_RESULT and field == PR_APPOINTMENT_DATE:
                if result['type'] != 'date' or not result['updateable']:
                    unreadable.append(object_name + '.' + field
                                      + ' must be an editable date.')
    return {'fields': found, 'missing': missing,
            'incompatible': unreadable, 'objects_checked': sorted(required)}


def _local_db_path():
    environment = environment_file()
    env = parse_env(environment.read_text(encoding='utf-8')) if environment.is_file() else {}
    value = os.environ.get('PRINTER_DATA_DIR', env.get(
        'PRINTER_DATA_DIR', '~/.local/share/printer-app'))
    return Path(value).expanduser() / 'printer_app.db'


def _samples(row):
    """Temporary scenario inputs, not changes to the saved MOD draft."""
    raw = row['snapshot'].get('product_interest') or ''
    products = list(dict.fromkeys(part.strip() for part in raw.split(';') if part.strip()))
    if not products:
        return ()
    cases = [('together-pns', {'dispo': 'pns'}),
             ('together-cxl', {'dispo': 'cxl'})]
    first = products[0]
    cases.append(('single-sale', {
        'dispo': 'sale',
        'sale_products': {first: {'price': '1000', 'deposit': '0'}},
        'sale_selection_order': [first],
    }))
    if len(products) > 1:
        second = products[1]
        cases.append(('multi-sale-second-first', {
            'dispo': 'sale',
            'sale_products': {
                first: {'price': '1000', 'deposit': '0'},
                second: {'price': '2000', 'deposit': '0'},
            },
            'sale_selection_order': [second, first],
        }))
        cases.append(('result-individually', {
            'dispo': 'pns', 'additional_products': True,
            'primary_product': second,
            'product_results': {first: {
                'result': 'np', 'detail': '', 'price': '', 'deposit': '',
            }},
        }))
    return [(name, clean_draft(draft)) for name, draft in cases]


def preview_local_day(db_path, *, org='work', day='', max_work_orders=1,
                      resulted_on=None, executable=None):
    """Preflight example submissions; the injected runner cannot execute writes."""
    repo = ResultingRepository(Database(Path(db_path), read_only=True))
    day = day or repo.latest_day()
    if not day:
        return {'status': 'skipped', 'reason': 'No imported MOD day was found.'}
    state = repo.day(day)
    if not state or not state.get('mod_user_id'):
        return {'status': 'skipped', 'day': day,
                'reason': 'No MOD selected for the imported day.'}
    eligible = [
        row for row in repo.sheets(day)
        if row['snapshot'].get('lead_source_id')
        and row['snapshot'].get('product_interest')
    ][:max_work_orders]
    if not eligible:
        return {'status': 'skipped', 'day': day,
                'reason': 'No imported sheets have a Lead and Product Interest.'}
    command = executable or shutil.which('sf') or '/usr/bin/sf'
    adapter = ResultingSalesforceAdapter(
        executable=command, target_org=org, runner=readonly_resulting_runner)
    ids = list(dict.fromkeys(row['snapshot']['lead_source_id'] for row in eligible))
    lead_dates = adapter.lead_appointment_dates(ids)
    resulted_on = resulted_on or datetime.now(
        ZoneInfo('America/Los_Angeles')).date().isoformat()
    date.fromisoformat(resulted_on)
    examples = []
    for row in eligible:
        for label, draft in _samples(row):
            try:
                payload = ResultingService.submission_payload(
                    dict(row, day=day, draft=draft), state['mod_user_id'],
                    resulted_on=resulted_on,
                    lead_appointment_date=lead_dates.get(
                        row['snapshot']['lead_source_id'], ''),
                )
                plan = adapter.prepare([payload])[0]
                examples.append({
                    'scenario': label,
                    'status': 'planned',
                    'operations': [
                        {'action': action, 'object': obj,
                         'fields': sorted(fields)}
                        for action, obj, _ident, fields in plan
                    ],
                })
            except (ValueError, RuntimeError, KeyError) as exc:
                examples.append({
                    'scenario': label, 'status': 'blocked',
                    'reason': str(exc)[:240],
                })
    return {'status': 'read_only', 'day': day,
            'records_examined': len(eligible), 'scenarios': examples}


def build_report(flow_path, *, schema_dir=None, db_path=None, org='work',
                 day='', max_work_orders=1):
    flow = inspect_flow(flow_path)
    schema = inspect_schemas(schema_dir or Path(flow_path).parent)
    report = {'mode': 'READ_ONLY_NO_SALESFORCE_WRITES',
              'flow': flow, 'schema': schema}
    if db_path:
        try:
            report['dry_run'] = preview_local_day(
                db_path, org=org, day=day, max_work_orders=max_work_orders)
        except (ValueError, RuntimeError, OSError) as exc:
            report['dry_run'] = {'status': 'blocked', 'reason': str(exc)[:240]}
    else:
        report['dry_run'] = {
            'status': 'skipped',
            'reason': 'Local printer database unavailable; Flow/schema audit is still valid.',
        }
    return report


def _format_report(report):
    flow, schema, sample = report['flow'], report['schema'], report['dry_run']
    out = [
        'Stats MOD Resulting / Flow v30 — READ ONLY',
        f"Flow: {flow['label']} / version {flow['version']} / {flow['status']}",
        'Graph: ' + (', '.join(
            f'{kind}={count}' for kind, count in flow['element_counts'].items())
            or 'no mapped graph elements'),
        'Flow custom fields referenced: ' +
            (', '.join(flow['referenced_custom_fields']) or '(none)'),
        f"Adapter field metadata present: {len(schema['fields'])}; "
        f"missing: {len(schema['missing'])}; incompatible: {len(schema['incompatible'])}",
    ]
    for issue in schema['missing'] + schema['incompatible']:
        out.append('  CHECK: ' + issue)
    out.append('Dry run: ' + sample['status'])
    if sample.get('reason'):
        out.append('  ' + sample['reason'])
    for scenario in sample.get('scenarios', ()):
        if scenario['status'] == 'blocked':
            out.append(f"  {scenario['scenario']}: BLOCKED — {scenario['reason']}")
        else:
            counts = Counter(
                (operation['action'], operation['object'])
                for operation in scenario['operations'])
            out.append(
                f"  {scenario['scenario']}: "
                + ', '.join(f'{n} {kind} {obj}' for (kind, obj), n in
                            sorted(counts.items()))
            )
    out.append('No create/update/delete commands were executed.')
    out.append('This inventory is NOT proof of complete Flow v30 parity.')
    return '\n'.join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Audit Flow v30 metadata and optionally preflight Stats '
                    'MOD Resulting without Salesforce writes.')
    parser.add_argument('--flow', type=Path, required=True,
                        help='Saved Tooling API Flow record, exact version 30')
    parser.add_argument('--schema-dir', type=Path,
                        help='Directory of Salesforce sobject describe JSON exports')
    parser.add_argument('--db', type=Path, help='Optional existing printer_app.db (read only)')
    parser.add_argument('--skip-local-db', action='store_true')
    parser.add_argument('--org', default='work')
    parser.add_argument('--day', default='')
    parser.add_argument('--max-work-orders', type=int, default=1)
    parser.add_argument('--json-report', type=Path,
                        help='Optional private JSON report destination')
    args = parser.parse_args(argv)
    if not 1 <= args.max_work_orders <= 3:
        parser.error('--max-work-orders must be between 1 and 3.')
    db_path = None if args.skip_local_db else (args.db or _local_db_path())
    if db_path and not db_path.is_file():
        db_path = None
    try:
        report = build_report(
            args.flow, schema_dir=args.schema_dir, db_path=db_path,
            org=args.org, day=args.day, max_work_orders=args.max_work_orders)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(_format_report(report))
    if args.json_report:
        # The report contains field paths and anonymous operation types only.
        # A private file is still preferable for internal Flow metadata.
        dest = args.json_report
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(report, file, indent=2)
            file.write('\n')


if __name__ == '__main__':
    main()
