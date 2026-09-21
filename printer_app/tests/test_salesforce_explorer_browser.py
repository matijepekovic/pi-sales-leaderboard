"""A person explores only the Salesforce records they explicitly request."""
import os
import threading
from copy import deepcopy

import pytest

from printer_app.app import create_app
from printer_app.config import Config
from printer_app.salesforce_sandbox.adapter import SalesforceAdapterError
from printer_app.tests.auth_helpers import browser_login


pytestmark = pytest.mark.skipif(
    os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies')

WORK_ORDER = '0WO000000000001AAA'
LEAD = '00Q000000000001AAA'
APPOINTMENT = '08p000000000001AAA'
SOURCE_TEXT = '<img src=x onerror="window.sfUnsafeSource=true">Sold after appointment'


def field(name, label, kind='string', *, operators=('eq', 'contains'), **extra):
    return dict(name=name, label=label, type=kind, filterable=True, sortable=True,
                reference_to=[], picklist_values=[], operators=list(operators), **extra)


class ExplorerSource:
    """A bounded source which records the actual adapter boundary, not DOM events."""

    def __init__(self):
        self.calls = []
        self.objects = [
            dict(name='WorkOrder', label='Work Orders', custom=False),
            dict(name='Lead', label='Leads', custom=False),
            dict(name='ServiceAppointment', label='Service Appointments', custom=False),
            dict(name='Slow__c', label='Slow Example', custom=True),
        ]
        reference = field('Lead__c', 'Lead', 'reference', operators=('eq',))
        reference['reference_to'] = ['Lead']
        status = field('Status', 'Status', 'picklist', operators=('eq',))
        status['picklist_values'] = [dict(label='Open', value='Open'), dict(label='Sold', value='Sold')]
        self.fields = {
            'WorkOrder': [
                field('Id', 'Record ID', 'id', operators=('eq',)),
                field('WorkOrderNumber', 'Work Order Number'), status,
                field('Sold_On__c', 'Sold On', 'date', operators=('eq', 'between')),
                reference, field('Description', 'Description', 'textarea'),
            ],
            'Lead': [field('Id', 'Record ID', 'id', operators=('eq',)),
                     field('Name', 'Lead Name'), field('Status', 'Lead Status')],
            'ServiceAppointment': [field('Id', 'Record ID', 'id', operators=('eq',)),
                                   field('AppointmentNumber', 'Appointment Number'),
                                   field('Status', 'Status')],
            'Slow__c': [field('Id', 'Record ID', 'id', operators=('eq',)),
                        field('Name', 'Slow Name')],
        }
        self.relationships = [
            dict(name='Appointments', label='Appointments', object='ServiceAppointment', field='ParentRecordId'),
            dict(name='OtherRecords', label='Other Records', object='Slow__c', field='WorkOrder__c'),
        ]

    def object_info(self, name):
        return {**next(value for value in self.objects if value['name'] == name), 'queryable': True}

    def explorer_objects(self):
        self.calls.append(('objects',))
        return dict(objects=deepcopy(self.objects))

    def explorer_object(self, name):
        self.calls.append(('object', name))
        return dict(object=self.object_info(name), fields=deepcopy(self.fields[name]),
                    relationships=deepcopy(self.relationships) if name == 'WorkOrder' else [],
                    default_columns=[value['name'] for value in self.fields[name][:3]])

    def explorer_search(self, name, columns=None, filters=None, match='all', after=''):
        self.calls.append(('search', name, deepcopy(columns), deepcopy(filters), match, after))
        assert name == 'WorkOrder'
        numbers = range(1, 51) if not after else range(51, 52)
        return dict(object=self.object_info(name),
                    columns=[deepcopy(value) for value in self.fields[name] if value['name'] in columns],
                    records=[dict(Id=f'0WO{number:012d}AAA', WorkOrderNumber=f'000123-{number:02d}',
                                  Status='Sold', Sold_On__c='2026-09-20') for number in numbers],
                    next_after='0WO000000000050AAA' if not after else '', page_size=50)

    def explorer_record(self, name, record_id):
        self.calls.append(('record', name, record_id))
        records = {
            'WorkOrder': dict(Id=WORK_ORDER, WorkOrderNumber='000123-01', Status='Sold',
                              Sold_On__c='2026-09-20', Lead__c=LEAD, Description=SOURCE_TEXT),
            'Lead': dict(Id=LEAD, Name='Jordan Example', Status='Converted'),
            'ServiceAppointment': dict(Id=APPOINTMENT, AppointmentNumber='SA-123', Status='Canceled'),
        }
        return dict(object=self.object_info(name), record=deepcopy(records[name]),
                    fields=deepcopy(self.fields[name]),
                    relationships=deepcopy(self.relationships) if name == 'WorkOrder' else [])

    def explorer_related(self, name, record_id, relationship, after=''):
        self.calls.append(('related', name, record_id, relationship, after))
        assert (name, record_id, relationship) == ('WorkOrder', WORK_ORDER, 'Appointments')
        return dict(object=self.object_info('ServiceAppointment'),
                    relationship=deepcopy(self.relationships[0]),
                    columns=deepcopy(self.fields['ServiceAppointment']),
                    records=[dict(Id=APPOINTMENT if not after else '08p000000000002AAA',
                                  AppointmentNumber='SA-123' if not after else 'SA-124',
                                  Status='Canceled' if not after else 'Scheduled')],
                    next_after=APPOINTMENT if not after else '', page_size=50)


@pytest.fixture(params=['chromium', 'webkit'])
def explorer(tmp_path, request):
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server

    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path / 'data', env_file=env,
                            secret_key='s' * 64, email_enabled=False))
    app.testing = True
    source = ExplorerSource()
    app.extensions['salesforce_sandbox'].adapter = source
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser = getattr(pw, request.param).launch(headless=True)
            context = browser.new_context(viewport={'width': 1200, 'height': 900})
            try:
                context.add_init_script("""
                  Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{
                    writeText:async text => {window.sfCopiedText = text;}
                  }});
                """)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                sandbox_requests = []
                page.on('request', lambda outgoing: sandbox_requests.append(outgoing.url)
                        if '/salesforce-sandbox/api/' in outgoing.url else None)
                browser_login(page, app, origin)
                assert page.goto(origin + '/salesforce-sandbox/explorer').status == 200
                expect(page.locator('#sfObjects [data-object]')).to_have_count(4)
                yield page, source, sandbox_requests
                assert not errors
                db = app.extensions['printer_db']
                for table in ('jobs', 'print_attempts', 'commands', 'print_queue_releases'):
                    assert db.rows('SELECT * FROM ' + table) == []
            finally:
                context.close()
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def choose_object(page, name):
    from playwright.sync_api import expect

    page.locator(f'#sfObjects [data-object="{name}"]').click()
    expect(page.locator('#sfObjectApiName')).to_have_text(name)
    expect(page.locator('#sfRunSearch')).to_be_enabled()


def test_explorer_fetches_only_opened_objects_search_pages_and_record_relationships(explorer):
    from playwright.sync_api import expect

    page, source, requests = explorer
    assert source.calls == [('objects',)]
    assert len(requests) == 1
    assert requests[0].endswith('/salesforce-sandbox/api/explorer/objects')
    page.locator('#sfObjectSearch').fill('work')
    expect(page.locator('#sfObjects [data-object]:visible')).to_have_count(1)
    assert source.calls == [('objects',)]
    choose_object(page, 'WorkOrder')
    assert source.calls == [('objects',), ('object', 'WorkOrder')]
    expect(page.locator('#sfResults tbody tr')).to_have_count(0)

    page.locator('#sfFieldSearch').fill('sold')
    expect(page.locator('#sfColumns input[value="Sold_On__c"]')).to_be_visible()
    page.locator('#sfColumns input[value="Sold_On__c"]').check()
    page.locator('#sfFieldSearch').fill('')
    for name, operator, value, second in [
        ('WorkOrderNumber', 'contains', '123', None),
        ('Sold_On__c', 'between', '2026-09-01', '2026-09-30'),
    ]:
        page.locator('#sfAddFilter').click()
        row = page.locator('#sfFilters [data-filter]').last
        row.locator('[name="field"]').select_option(name)
        row.locator('[name="operator"]').select_option(operator)
        row.locator('[name="value"]').fill(value)
        if second:
            row.locator('[name="value2"]').fill(second)
    page.locator('#sfMatch').select_option('all')
    assert source.calls == [('objects',), ('object', 'WorkOrder')]

    page.locator('#sfRunSearch').click()
    expect(page.locator('#sfResults tbody tr')).to_have_count(50)
    query = source.calls[-1]
    assert query[:2] == ('search', 'WorkOrder')
    assert 'Sold_On__c' in query[2]
    assert [(item['field'], item['operator'], item['value']) for item in query[3]] == [
        ('WorkOrderNumber', 'contains', '123'), ('Sold_On__c', 'between', '2026-09-01')]
    assert query[3][1]['value2'] == '2026-09-30'
    assert query[4:] == ('all', '')
    page.locator('#sfMore').click()
    expect(page.locator('#sfResults tbody tr')).to_have_count(51)
    assert source.calls[-1] == (*query[:5], '0WO000000000050AAA')
    expect(page.locator('#sfMore')).not_to_be_visible()
    assert not any(call[0] in ('record', 'related') for call in source.calls)

    page.locator(f'#sfResults [data-record="{WORK_ORDER}"]').first.click()
    expect(page.locator('#sfRecordFields')).to_contain_text(SOURCE_TEXT)
    expect(page.locator('#sfRecordIdentity')).to_contain_text(WORK_ORDER)
    assert source.calls[-1] == ('record', 'WorkOrder', WORK_ORDER)
    assert not any(call[0] == 'related' for call in source.calls)
    expect(page.locator('#sfRecordFields img')).to_have_count(0)
    assert not page.evaluate('() => Boolean(window.sfUnsafeSource)')
    page.locator('#sfCopy').click()
    page.wait_for_function('() => Boolean(window.sfCopiedText)')
    copied = page.evaluate('() => window.sfCopiedText')
    for value in ('WorkOrder', WORK_ORDER, 'Sold_On__c', '2026-09-20'):
        assert value in copied

    page.locator('#sfRelated [data-relationship="Appointments"]').click()
    related = page.locator('[data-relationship-panel="Appointments"]')
    expect(related).to_contain_text('SA-123')
    expect(related).to_contain_text('Canceled')
    assert source.calls[-1] == ('related', 'WorkOrder', WORK_ORDER, 'Appointments', '')
    related.locator('[data-related-more="Appointments"]').click()
    expect(related).to_contain_text('SA-124')
    assert source.calls[-1] == ('related', 'WorkOrder', WORK_ORDER, 'Appointments', APPOINTMENT)
    assert not any(call[0] == 'related' and call[3] == 'OtherRecords' for call in source.calls)

    before_parent = list(source.calls)
    page.locator(f'[data-reference-object="Lead"][data-reference-id="{LEAD}"]').click()
    expect(page.locator('#sfRecordFields')).to_contain_text('Jordan Example')
    assert source.calls[len(before_parent):] == [('record', 'Lead', LEAD)]
    before_back = list(source.calls)
    page.locator('#sfBack').click()
    expect(page.locator('#sfRecordFields')).to_contain_text(SOURCE_TEXT)
    expect(page.locator('[data-relationship-panel="Appointments"]')).to_contain_text('SA-124')
    assert source.calls == before_back
    page.locator('#sfBack').click()
    expect(page.locator('#sfResults tbody tr')).to_have_count(51)
    expect(page.locator('#sfFilters [name="value"]').first).to_have_value('123')
    assert source.calls == before_back
    assert all('/api/explorer/' in url for url in requests)


def test_switching_objects_ignores_an_earlier_delayed_describe(explorer):
    from playwright.sync_api import expect

    page, source, _ = explorer
    page.evaluate("""() => {
      const actual = window.fetch.bind(window);
      let release;
      const pending = new Promise(resolve => {release = resolve;});
      window.sfReleaseDescribe = release;
      window.fetch = async (...args) => {
        const response = await actual(...args);
        const input = args[0];
        const url = typeof input === 'string' ? input : input.url;
        if (url.includes('/objects/Slow__c')) {
          window.sfHeldDescribe = true;
          await pending;
        }
        return response;
      };
    }""")
    try:
        page.locator('#sfObjects [data-object="Slow__c"]').click()
        page.wait_for_function('() => window.sfHeldDescribe === true')
        choose_object(page, 'Lead')
        expect(page.locator('#sfColumns input[value="Name"]')).to_be_visible()
    finally:
        page.evaluate('() => window.sfReleaseDescribe()')
    # Drain the released response and a rendering frame without an arbitrary delay.
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    expect(page.locator('#sfObjectApiName')).to_have_text('Lead')
    expect(page.locator('#sfColumns')).to_contain_text('Lead Name')
    expect(page.locator('#sfColumns')).not_to_contain_text('Slow Name')
    expect(page.locator('#sfMessage')).not_to_be_visible()
    assert source.calls == [('objects',), ('object', 'Slow__c'), ('object', 'Lead')]


def test_mobile_explorer_retries_one_object_and_offers_copy_when_clipboard_is_unavailable(explorer):
    from playwright.sync_api import expect

    page, source, requests = explorer
    page.set_viewport_size({'width': 390, 'height': 844})
    describe = source.explorer_object
    attempts = 0

    def temporarily_unavailable(name):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            source.calls.append(('object', name))
            raise SalesforceAdapterError('Salesforce is temporarily unavailable. Try again.')
        return describe(name)

    source.explorer_object = temporarily_unavailable
    page.evaluate("""() => {
      navigator.clipboard.writeText = async () => {
        throw new Error('Clipboard requires a secure connection');
      };
    }""")

    def assert_mobile_width():
        assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth + 1')
        # Tables may scroll inside their own containers; these primary controls
        # must remain within the screen without horizontal page scrolling.
        outside = page.evaluate("""() => [...document.querySelectorAll(
          '#sfObjectSearch, #sfFieldSearch, #sfAddFilter, #sfRunSearch, #sfCopy, #sfCopyText, #sfFilters input, #sfFilters select'
        )].filter(control => control.getClientRects().length).filter(control => {
          const box = control.getBoundingClientRect();
          return box.left < -1 || box.right > innerWidth + 1;
        }).map(control => control.id || control.name)""")
        assert outside == []

    page.locator('#sfObjects [data-object="WorkOrder"]').click()
    expect(page.locator('#sfMessage')).to_contain_text('temporarily unavailable')
    expect(page.locator('#sfRetryObject')).to_be_visible()
    assert source.calls == [('objects',), ('object', 'WorkOrder')]
    assert_mobile_width()
    page.locator('#sfRetryObject').click()
    expect(page.locator('#sfRunSearch')).to_be_enabled()
    expect(page.locator('#sfMessage')).not_to_be_visible()
    assert source.calls == [('objects',), ('object', 'WorkOrder'), ('object', 'WorkOrder')]

    page.locator('#sfAddFilter').click()
    row = page.locator('#sfFilters [data-filter]')
    row.locator('[name="field"]').select_option('Status')
    row.locator('[name="value"]').select_option('Sold')
    assert_mobile_width()
    page.locator('#sfRunSearch').click()
    expect(page.locator('#sfResults tbody tr')).to_have_count(50)
    assert source.calls[-1][0:2] == ('search', 'WorkOrder')
    assert source.calls[-1][3] == [dict(field='Status', operator='eq', value='Sold')]
    assert_mobile_width()
    page.locator(f'#sfResults [data-record="{WORK_ORDER}"]').first.click()
    expect(page.locator('#sfRecordIdentity')).to_contain_text(WORK_ORDER)
    expect(page.locator('#sfCopy')).to_be_enabled()
    page.locator('#sfCopy').click()
    expect(page.locator('#sfCopyFallback')).to_be_visible()
    text = page.locator('#sfCopyText').input_value()
    for value in ('WorkOrder', WORK_ORDER, 'Sold_On__c', '2026-09-20'):
        assert value in text
    assert page.locator('#sfCopyText').evaluate('(control) => control.readOnly')
    expect(page.locator('#sfMessage')).to_contain_text('Select and copy')
    assert_mobile_width()
    assert [call[0] for call in source.calls] == ['objects', 'object', 'object', 'search', 'record']
    assert all('/api/explorer/' in url for url in requests)
