"""The object explorer stays lazy, bounded, typed, and read-only at its source boundary."""
import json
import re
from types import SimpleNamespace

import pytest

from printer_app.salesforce_sandbox.adapter import SalesforceAdapterError, SalesforceCliAdapter


RECORD_ID = '0WO000000000001AAA'
LEAD_ID = '00Q000000000002AAA'


def field(name, kind='string', **extra):
    return dict(name=name, label=name, type=kind, filterable=True, sortable=True,
                referenceTo=[], picklistValues=[], **extra)


def schema(name='WorkOrder'):
    result = {
        'name': name, 'label': 'Work Orders', 'queryable': True,
        'fields': [
            field('Id', 'id'), field('Name', nameField=True),
            field('Status', 'picklist'), field('SoldOn__c', 'date'),
            field('SoldAt__c', 'datetime'), field('Amount__c', 'currency'),
            field('Count__c', 'int'), field('Sold__c', 'boolean'),
            field('Tags__c', 'multipicklist'), field('Lead__c', 'reference'),
            field('OwnerId', 'reference'), field('Description', 'textarea'),
            field('CreatedDate', 'datetime'), field('Location__c', 'location'),
        ],
        'childRelationships': [
            {'relationshipName': 'Appointments', 'childSObject': 'ServiceAppointment', 'field': 'ParentRecordId'},
            {'relationshipName': None, 'childSObject': 'OtherObject', 'field': 'ParentId'},
        ],
    }
    result['fields'][2]['picklistValues'] = [
        {'label': 'Sold', 'value': 'Closed Won', 'active': True},
        {'label': 'Old sold label', 'value': 'Legacy sold', 'active': False},
    ]
    result['fields'][9]['referenceTo'] = ['Lead']
    result['fields'][10]['referenceTo'] = ['User', 'Group']
    result['fields'][11]['filterable'] = False
    return result


class Runner:
    def __init__(self, *, objects=None, schemas=None, rows=None, record=None):
        self.calls = []
        self.objects = objects if objects is not None else ['WorkOrder', 'Lead', 'Invoice__c']
        self.schemas = schemas or {'WorkOrder': schema()}
        self.rows = rows if rows is not None else [{'Id': RECORD_ID, 'Name': 'Example job'}]
        self.record = record if record is not None else {
            'attributes': {'type': 'WorkOrder'}, 'Id': RECORD_ID,
            'Name': 'Example job', 'Lead__c': LEAD_ID, 'Description': 'Opened only on demand',
        }

    def __call__(self, command, **options):
        self.calls.append(command)
        assert options['check'] is False and options['capture_output'] is True
        assert command[-3:] == ['--target-org', 'work', '--json']
        if command[1:3] == ['sobject', 'list']:
            assert command[3:5] == ['--sobject', 'all']
            result = self.objects
        elif command[1:3] == ['sobject', 'describe']:
            result = self.schemas[command[command.index('--sobject') + 1]]
        elif command[1:3] == ['data', 'query']:
            query = command[command.index('--query') + 1]
            result = self.rows(query) if callable(self.rows) else {'records': self.rows}
        elif command[1:4] == ['data', 'get', 'record']:
            result = self.record
        else:
            raise AssertionError(f'Unexpected or non-read-only command: {command}')
        return SimpleNamespace(returncode=0, stdout=json.dumps({'status': 0, 'result': result}), stderr='')

    @property
    def queries(self):
        return [call[call.index('--query') + 1] for call in self.calls if '--query' in call]


def adapter_for(**kwargs):
    runner = Runner(**kwargs)
    return SalesforceCliAdapter(runner=runner), runner


def test_opening_explorer_only_loads_names_in_one_read_only_command():
    adapter, runner = adapter_for()
    assert adapter.explorer_objects() == {'objects': [
        {'name': 'Invoice__c', 'label': 'Invoice__c', 'custom': True},
        {'name': 'Lead', 'label': 'Lead', 'custom': False},
        {'name': 'WorkOrder', 'label': 'WorkOrder', 'custom': False},
    ]}
    assert len(runner.calls) == 1
    assert runner.calls[0][1:3] == ['sobject', 'list']


def test_empty_object_list_is_valid_and_not_converted_to_a_dictionary():
    adapter, _ = adapter_for(objects=[])
    assert adapter.explorer_objects() == {'objects': []}


def test_object_click_describes_only_the_selected_object_and_exposes_links_without_loading_them():
    adapter, runner = adapter_for()
    result = adapter.explorer_object('WorkOrder')
    assert result['object'] == {'name': 'WorkOrder', 'label': 'Work Orders', 'queryable': True}
    fields = {item['name']: item for item in result['fields']}
    assert fields['Lead__c']['reference_to'] == ['Lead']
    assert fields['OwnerId']['reference_to'] == ['User', 'Group']
    assert fields['Status']['picklist_values'] == [
        {'label': 'Sold', 'value': 'Closed Won'}, {'label': 'Old sold label', 'value': 'Legacy sold'},
    ]
    assert fields['Tags__c']['operators'] == ['includes', 'excludes', 'is_empty', 'not_empty']
    assert fields['Description']['operators'] == []
    assert fields['Location__c']['operators'] == []
    assert result['relationships'] == [
        {'name': 'Appointments', 'label': 'Appointments', 'object': 'ServiceAppointment', 'field': 'ParentRecordId'},
    ]
    assert len(runner.calls) == 1
    assert runner.calls[0][1:5] == ['sobject', 'describe', '--sobject', 'WorkOrder']


def test_metadata_cache_expires_and_callers_cannot_change_its_allowlist(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr('printer_app.salesforce_sandbox.adapter.monotonic', lambda: clock[0])
    adapter, runner = adapter_for()
    first = adapter.explorer_object('WorkOrder')
    first['fields'][0]['name'] = 'unsafe.path'
    first['relationships'].clear()
    assert adapter.explorer_object('WorkOrder')['fields'][0]['name'] == 'Id'
    assert len(runner.calls) == 1
    clock[0] += 601
    assert adapter.explorer_object('WorkOrder')['relationships']
    assert len(runner.calls) == 2


def test_metadata_cache_has_a_fixed_size_and_evicts_the_least_recent_object():
    adapter, runner = adapter_for(schemas={f'Object{i}__c': schema(f'Object{i}__c') for i in range(33)})
    for i in range(32):
        adapter.explorer_object(f'Object{i}__c')
    adapter.explorer_object('Object0__c')
    adapter.explorer_object('Object32__c')
    adapter.explorer_object('Object0__c')
    assert len(runner.calls) == 33
    adapter.explorer_object('Object1__c')
    assert len(runner.calls) == 34


@pytest.mark.parametrize(('field_name', 'operator', 'value', 'value2', 'expected'), [
    ('Status', 'eq', 'Closed Won', None, "Status = 'Closed Won'"),
    ('Sold__c', 'eq', True, None, 'Sold__c = true'),
    ('Sold__c', 'ne', False, None, 'Sold__c != false'),
    ('Amount__c', 'gte', '-1200.50', None, 'Amount__c >= -1200.50'),
    ('Amount__c', 'lt', '1e3', None, 'Amount__c < 1000'),
    ('Count__c', 'gt', '2', None, 'Count__c > 2'),
    ('Amount__c', 'between', '1.20', '5.50', '(Amount__c >= 1.20 AND Amount__c <= 5.50)'),
    ('SoldOn__c', 'eq', '2026-09-21', None, 'SoldOn__c = 2026-09-21'),
    ('SoldOn__c', 'between', '2026-09-01', '2026-09-30', '(SoldOn__c >= 2026-09-01 AND SoldOn__c <= 2026-09-30)'),
    ('SoldAt__c', 'lte', '2026-09-21T01:30:00-07:00', None, 'SoldAt__c <= 2026-09-21T08:30:00Z'),
    ('SoldAt__c', 'eq', '2026-09-21T08:30:00.000Z', None, 'SoldAt__c = 2026-09-21T08:30:00Z'),
    ('Lead__c', 'eq', LEAD_ID, None, f"Lead__c = '{LEAD_ID}'"),
    ('Tags__c', 'includes', 'Windows', None, "Tags__c INCLUDES ('Windows')"),
    ('Tags__c', 'excludes', 'Roofing', None, "Tags__c EXCLUDES ('Roofing')"),
    ('Name', 'is_empty', None, None, 'Name = null'),
    ('Name', 'not_empty', None, None, 'Name != null'),
])
def test_filters_use_typed_literals(field_name, operator, value, value2, expected):
    adapter, runner = adapter_for()
    adapter.explorer_search('WorkOrder', columns=['Name'], filters=[{
        'field': field_name, 'operator': operator, 'value': value, 'value2': value2,
    }])
    assert runner.queries == [f'SELECT Id, Name FROM WorkOrder WHERE ({expected}) ORDER BY Id ASC LIMIT 51']


def test_string_filter_escapes_quotes_backslashes_control_characters_and_like_wildcards():
    adapter, runner = adapter_for()
    adapter.explorer_search('WorkOrder', filters=[{
        'field': 'Name', 'operator': 'eq', 'value': "x' OR Id != null OR Name = '\\folder\nnext",
    }])
    assert "Name = 'x\\' OR Id != null OR Name = \\'\\\\folder\\nnext'" in runner.queries[-1]
    adapter.explorer_search('WorkOrder', filters=[{'field': 'Name', 'operator': 'contains', 'value': '50%_off'}])
    assert r"Name LIKE '%50\%\_off%'" in runner.queries[-1]
    adapter.explorer_search('WorkOrder', filters=[{'field': 'Name', 'operator': 'starts_with', 'value': '50%_off'}])
    assert r"Name LIKE '50\%\_off%'" in runner.queries[-1]
    adapter.explorer_search('WorkOrder', filters=[{'field': 'Name', 'operator': 'contains', 'value': r'C:\50%'}])
    assert r"Name LIKE '%C:\\50\%%'" in runner.queries[-1]


def test_any_filters_are_grouped_before_pagination_constraint():
    adapter, runner = adapter_for(rows=[{'Id': '0WO000000000003AAA'}])
    adapter.explorer_search('WorkOrder', filters=[
        {'field': 'Name', 'operator': 'eq', 'value': 'Example'},
        {'field': 'Status', 'operator': 'eq', 'value': 'Sold'},
    ], match='any', after=RECORD_ID)
    assert f"WHERE (Name = 'Example' OR Status = 'Sold') AND Id > '{RECORD_ID}'" in runner.queries[0]


@pytest.mark.parametrize('kwargs', [
    {'columns': ['Name FROM User']}, {'columns': ['Lead__r.Name']}, {'columns': 'Name'},
    {'columns': ['Id'] * 21}, {'filters': [{}] * 11}, {'filters': 'Status=Sold'},
    {'filters': [{'field': 'Unknown', 'operator': 'eq', 'value': 'x'}]},
    {'filters': [{'field': ['Name'], 'operator': 'eq', 'value': 'x'}]},
    {'filters': [{'field': 'Name', 'operator': 'raw', 'value': 'x'}]},
    {'filters': [{'field': 'Description', 'operator': 'eq', 'value': 'x'}]},
    {'filters': [{'field': 'Status', 'operator': 'contains', 'value': 'x'}]},
    {'filters': [{'field': 'Sold__c', 'operator': 'eq', 'value': 'true'}]},
    {'filters': [{'field': 'Amount__c', 'operator': 'eq', 'value': '1 OR Id != null'}]},
    {'filters': [{'field': 'Amount__c', 'operator': 'eq', 'value': float('nan')}]},
    {'filters': [{'field': 'Amount__c', 'operator': 'eq', 'value': '1e999'}]},
    {'filters': [{'field': 'Count__c', 'operator': 'eq', 'value': '1.5'}]},
    {'filters': [{'field': 'SoldOn__c', 'operator': 'eq', 'value': '2026-02-30'}]},
    {'filters': [{'field': 'SoldOn__c', 'operator': 'eq', 'value': '2026-01-01 OR Id != null'}]},
    {'filters': [{'field': 'SoldAt__c', 'operator': 'eq', 'value': '2026-09-21T08:00:00'}]},
    {'filters': [{'field': 'SoldAt__c', 'operator': 'eq', 'value': '2026-09-21T08:00:00.123Z'}]},
    {'filters': [{'field': 'Lead__c', 'operator': 'eq', 'value': 'bad-id'}]},
    {'filters': [{'field': 'Tags__c', 'operator': 'includes', 'value': ['Windows']}]},
    {'filters': [{'field': 'Tags__c', 'operator': 'includes', 'value': 'Windows;Roofing'}]},
    {'filters': [{'field': 'Name', 'operator': 'eq', 'value': '\x00'}]},
    {'match': 'all OR 1=1'}, {'after': "x' OR Id != null"}, {'after': []}, {'after': None},
])
def test_invalid_search_inputs_never_reach_a_query(kwargs):
    adapter, runner = adapter_for()
    with pytest.raises(ValueError):
        adapter.explorer_search('WorkOrder', **kwargs)
    assert not runner.queries


@pytest.mark.parametrize('name', ['WorkOrder WHERE Id != null', 'Lead.Name', 'A;B', 'Ünicode', '', None])
def test_invalid_object_identifiers_do_not_run_any_command(name):
    adapter, runner = adapter_for()
    with pytest.raises(ValueError):
        adapter.explorer_object(name)
    assert runner.calls == []


@pytest.mark.parametrize('change', ['not_queryable', 'id_not_filterable', 'id_not_sortable', 'no_id'])
def test_unsupported_objects_fail_without_querying(change):
    source = schema()
    if change == 'not_queryable':
        source['queryable'] = False
    elif change == 'no_id':
        source['fields'] = source['fields'][1:]
    else:
        source['fields'][0]['filterable' if change == 'id_not_filterable' else 'sortable'] = False
    adapter, runner = adapter_for(schemas={'WorkOrder': source})
    assert adapter.explorer_object('WorkOrder')['fields']
    with pytest.raises(ValueError, match='does not support'):
        adapter.explorer_search('WorkOrder')
    assert not runner.queries


def test_pagination_loads_only_one_page_per_request_and_can_pass_two_thousand_records():
    rows = [{'Id': f'0WO{index:012d}AAA', 'Name': f'Job {index}'} for index in range(1, 2054)]

    def query_rows(query):
        after = re.search(r"Id > '([^']+)'", query)
        remaining = [row for row in rows if not after or row['Id'] > after.group(1)]
        assert query.endswith('ORDER BY Id ASC LIMIT 51')
        assert 'OFFSET' not in query
        return {'records': remaining[:51], 'done': True}

    adapter, runner = adapter_for(rows=query_rows)
    collected = []
    cursor = ''
    while True:
        calls_before = len(runner.queries)
        result = adapter.explorer_search('WorkOrder', columns=['Name'], after=cursor)
        assert len(runner.queries) == calls_before + 1
        assert len(result['records']) <= 50 and result['page_size'] == 50
        collected.extend(result['records'])
        cursor = result['next_after']
        if not cursor:
            break
        assert cursor == result['records'][-1]['Id']
    assert collected == rows
    assert len(runner.queries) == 42
    assert sum(call[1:3] == ['sobject', 'describe'] for call in runner.calls) == 1


@pytest.mark.parametrize('rows', [
    [{'Id': 'invalid'}], [None], [{'Id': RECORD_ID}, {'Id': RECORD_ID}],
    [{'Id': f'0WO{index:012d}AAA'} for index in range(52)],
])
def test_invalid_pages_are_rejected_instead_of_returning_misleading_results(rows):
    adapter, _ = adapter_for(rows=rows)
    with pytest.raises(SalesforceAdapterError):
        adapter.explorer_search('WorkOrder')


def test_repeated_cursor_and_truncated_pages_fail_clearly():
    adapter, _ = adapter_for()
    with pytest.raises(SalesforceAdapterError, match='advance'):
        adapter.explorer_search('WorkOrder', after=RECORD_ID)
    adapter, _ = adapter_for(rows=lambda query: {'records': [], 'done': False})
    with pytest.raises(SalesforceAdapterError, match='incomplete'):
        adapter.explorer_search('WorkOrder')


def test_open_record_fetches_all_its_values_once_without_following_links_or_children():
    adapter, runner = adapter_for()
    adapter.explorer_object('WorkOrder')
    result = adapter.explorer_record('WorkOrder', RECORD_ID)
    assert result['record']['Description'] == 'Opened only on demand'
    assert result['record']['Lead__c'] == LEAD_ID
    assert 'attributes' not in result['record']
    assert result['relationships'][0]['name'] == 'Appointments'
    assert len(runner.calls) == 2
    assert runner.calls[-1][1:8] == ['data', 'get', 'record', '--sobject', 'WorkOrder', '--record-id', RECORD_ID]
    assert '--values' not in runner.calls[-1]


def test_related_click_only_describes_its_child_then_fetches_a_locked_parent_page():
    child = schema('ServiceAppointment')
    child['fields'].append(field('ParentRecordId', 'reference'))
    child['fields'][-1]['referenceTo'] = ['WorkOrder', 'Account']
    adapter, runner = adapter_for(schemas={'WorkOrder': schema(), 'ServiceAppointment': child})
    adapter.explorer_object('WorkOrder')
    assert len(runner.calls) == 1
    result = adapter.explorer_related('WorkOrder', RECORD_ID, 'Appointments')
    assert len(runner.calls) == 3
    assert runner.calls[1][1:5] == ['sobject', 'describe', '--sobject', 'ServiceAppointment']
    assert f"FROM ServiceAppointment WHERE (ParentRecordId = '{RECORD_ID}')" in runner.queries[0]
    assert result['relationship']['name'] == 'Appointments'
    assert result['page_size'] == 50


@pytest.mark.parametrize('relationship', ['Unknown', 'Appointments WHERE Id != null', 'Appointments.Other'])
def test_unlisted_relationship_cannot_select_another_foreign_key(relationship):
    adapter, runner = adapter_for()
    with pytest.raises(ValueError):
        adapter.explorer_related('WorkOrder', RECORD_ID, relationship)
    assert not runner.queries
    assert not any('ServiceAppointment' in call for call in runner.calls)


def test_relation_with_mismatched_reference_target_fails_before_query():
    child = schema('ServiceAppointment')
    child['fields'].append(field('ParentRecordId', 'reference'))
    child['fields'][-1]['referenceTo'] = ['Account']
    adapter, runner = adapter_for(schemas={'WorkOrder': schema(), 'ServiceAppointment': child})
    with pytest.raises(ValueError, match='cannot be searched safely'):
        adapter.explorer_related('WorkOrder', RECORD_ID, 'Appointments')
    assert not runner.queries


@pytest.mark.parametrize('ident', ["x' OR Id != null", '１２３４５６７８９０１２３４５', '', None])
def test_invalid_record_ids_fail_before_any_source_read(ident):
    adapter, runner = adapter_for()
    with pytest.raises(ValueError):
        adapter.explorer_record('WorkOrder', ident)
    assert not runner.calls


def test_wrong_record_or_schema_from_source_is_not_displayed_as_requested_data():
    adapter, _ = adapter_for(record={'Id': LEAD_ID})
    with pytest.raises(SalesforceAdapterError, match='different record'):
        adapter.explorer_record('WorkOrder', RECORD_ID)
    adapter, _ = adapter_for(schemas={'WorkOrder': schema('Lead')})
    with pytest.raises(SalesforceAdapterError, match='different object'):
        adapter.explorer_object('WorkOrder')
