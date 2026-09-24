"""Saved names-only rep options are independent of live MOD generation."""
import inspect
from contextlib import contextmanager
import sqlite3
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_sheets.rep_repository import ModSheetRepRepository, REP_NAMES_KEY, REP_TOTALS_KEY
from printer_app.db import Database
from printer_app.salesforce_sandbox.adapter import SalesforceCliAdapter
from printer_app.salesforce_sandbox.service import SalesforceSandboxService
from test_salesforce_sandbox import _appointment

RESOURCE = 'assigned_service_resource'
MARKET = 'FSSK__FSK_Work_Order__r.Lead__r.Market__c'
ASSIGNMENT = 'FSSK__FSK_Assigned_Service_Resource__r.Name'
PROJECTION = 'SELECT Id, FSSK__FSK_Work_Order__c, SchedStartTime, ' + ASSIGNMENT
DAY = '2026-09-19'
SCOPE = dict(start_date=DAY, end_date=DAY, market_segment='Olympia')
RUNTIME = Path(__file__).resolve().parents[1] / 'static/mod_sheets/runtime.js'


def appointment(index, name, **kwargs):
    kwargs.setdefault('work_order_id', f'0WO{index:012d}AAA')
    return _appointment(f'08p{index:012d}AAA', resource=name, **kwargs)


class MemoryDb:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)')

    @contextmanager
    def connect(self):
        with self.conn:
            yield self.conn

    def get(self, key):
        row = self.conn.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else None

    def set(self, key, value):
        with self.connect() as conn:
            conn.execute('INSERT INTO meta VALUES (?,?) '
                         'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))


def source_pages(pages, repository=None):
    pending = iter(pages)
    queries = []

    def runner(command, **kwargs):
        queries.append(command[command.index('--query') + 1])
        page = next(pending)
        if isinstance(page, Exception):
            raise page
        result = {'records': page} if isinstance(page, list) else page
        return SimpleNamespace(returncode=0, stdout=json.dumps({'status': 0, 'result': result}), stderr='')

    adapter = SalesforceCliAdapter(runner=runner)
    adapter._timezone = ZoneInfo('America/Los_Angeles')
    return SalesforceSandboxService(adapter, rep_repository=repository or ModSheetRepRepository(MemoryDb())), queries


@pytest.mark.parametrize('market', ['Olympia', 'Federal Way', 'Seattle', "King's & North"])
def test_options_use_the_pdf_assignment_and_selected_dates_and_filters(market):
    service, queries = source_pages([[appointment(1, 'Assigned Rep')], []])
    result = service.refresh_reps(**dict(SCOPE, market_segment=market),
                           product_category='Windows', source_type='Canvass')
    assert not result.error
    assert result.field.values == ('Assigned Rep',)
    assert result.field.path == 'assigned_service_resources'
    escaped = market.replace("'", "\\'")
    for query in queries:
        assert ' FROM ServiceAppointment WHERE ' in query
        assert f"{MARKET} = '{escaped}'" in query
        assert 'SchedStartTime >= 2026-09-19T07:00:00Z' in query
        assert 'SchedStartTime < 2026-09-20T07:00:00Z' in query
        assert "Product_Interest__c INCLUDES ('Windows')" in query
        assert "LeadSource = 'Canvass'" in query
        assert 'Status' not in query
        assert 'LastModifiedDate' not in query
        assert query.split(' FROM ')[0] == PROJECTION
        assert ASSIGNMENT not in query.split(' WHERE ')[1]
        assert all(term not in query for term in ('ServiceResource WHERE', 'Service_Territory', 'GROUP BY'))


def test_resource_options_read_beyond_first_1000_appointments():
    first = [appointment(index, f'Rep {index:04}') for index in range(1000)]
    second = [appointment(1000, 'Rep 1000'), appointment(1001, 'Rep 1001')]
    service, queries = source_pages([{'records': first, 'done': True}, second, []])
    result = service.refresh_reps(**SCOPE)
    assert not result.error
    assert result.field.values == tuple(f'Rep {index:04}' for index in range(1002))
    assert len(queries) == 3
    assert f"Id > '{first[-1]['Id']}'" in queries[1]
    assert f"Id > '{second[-1]['Id']}'" in queries[2]


def test_explicit_refresh_replaces_names_and_all_market_has_no_market_predicate():
    service, queries = source_pages([
        [appointment(1, 'Before Reassignment')], [],
        [appointment(1, 'After Reassignment')], [],
        [appointment(2, 'Seattle Rep')], [],
    ])
    assert service.refresh_reps(**SCOPE).field.values == ('Before Reassignment',)
    assert service.field(RESOURCE).field.values == ('Before Reassignment',)
    assert len(queries) == 2
    assert service.refresh_reps(**SCOPE).field.values == ('After Reassignment',)
    assert service.refresh_reps(**dict(SCOPE, market_segment='')).field.values == ('Seattle Rep',)
    assert len(queries) == 6
    assert all('Market__c =' not in query for query in queries[4:])


def test_no_appointments_is_successful_empty_options_not_unavailable():
    service, _ = source_pages([[]])
    result = service.refresh_reps(**SCOPE)
    assert not result.error
    assert result.field.values == ()


@pytest.mark.parametrize('metadata', [{'done': False}, {'done': True, 'totalSize': 3}])
def test_names_are_distinct_whole_names_and_all_short_pages_are_read(metadata):
    service, queries = source_pages([
        {'records': [appointment(1, "O'Neil; Alex")], **metadata},
        [appointment(2, "O'Neil; Alex"), appointment(3, 'Another Rep')], [],
    ])
    result = service.refresh_reps(**dict(SCOPE, market_segment="King's \\ North"))
    assert not result.error
    assert result.field.values == ('Another Rep', "O'Neil; Alex")
    assert "Market__c = 'King\\'s \\\\ North'" in queries[0]
    assert "Id > '08p000000000001AAA'" in queries[1]


@pytest.mark.parametrize('broken_page', [
    {}, {'records': [], 'done': False}, {'records': [], 'totalSize': 1},
    [appointment(1, 'Repeated')], [{'Name': 'No ID'}],
    [dict(appointment(2, 'Bad ID'), Id="bad' OR Id != null")],
    [appointment(2, 'Two'), appointment(2, 'Two')],
    [appointment(index, 'Too many') for index in range(1001)],
    OSError('source unavailable'), subprocess.TimeoutExpired('sf', 60),
])
def test_failed_pages_return_no_partial_options_and_retry_reads_fresh(broken_page):
    service, queries = source_pages([
        [appointment(1, 'Rep One')], broken_page,
        [appointment(1, 'Rep One'), appointment(2, 'Rep Two')], [],
    ])
    failed = service.refresh_reps(**SCOPE)
    assert failed.error and failed.field is None
    retried = service.refresh_reps(**SCOPE)
    assert not retried.error
    assert retried.field.values == ('Rep One', 'Rep Two')
    assert len(queries) == 4


@pytest.mark.parametrize('scope', [
    dict(SCOPE, market_segment=None), dict(SCOPE, market_segment=12),
    dict(SCOPE, market_segment='x' * 129), dict(SCOPE, market_segment='Olympia\nSeattle'),
    dict(SCOPE, start_date=''), dict(SCOPE, end_date='bad'),
    dict(SCOPE, end_date='2026-09-18'),
])
def test_invalid_scope_never_queries_unbounded_history(scope):
    service, queries = source_pages([])
    assert service.refresh_reps(**scope).error
    assert queries == []


@pytest.mark.parametrize('selected', ['Sam', 'sam'])
def test_selected_rep_keeps_all_coassignments_and_filters_after_grouping(selected):
    rows = [appointment(1, 'Alex', work_order_id='shared'),
            appointment(2, 'Sam', work_order_id='shared'), appointment(3, 'Other')]
    service, queries = source_pages([rows, []])
    result = service.generate(**SCOPE, assigned_service_resource=selected, limit=1000)
    assert not result.error
    assert len(result.records) == 1
    assert result.records[0].assigned_service_resources == ('Alex', 'Sam')
    # PDF receives the same complete normalized assignment, not a renamed/cut sheet.
    from printer_app.mod_sheets.pdf_renderer import _mod_table
    cell = _mod_table(result.records[0], False)._cellvalues[2][2]
    assert cell.value == 'Alex, Sam'
    assert all(ASSIGNMENT not in query.split(' WHERE ')[1] for query in queries)


def test_canceled_assignment_cannot_resurrect_after_rep_selection():
    rows = [appointment(1, 'Alex', work_order_id='shared'),
            appointment(2, 'Sam', work_order_id='shared', appointment_status='Canceled')]
    service, _ = source_pages([rows, []])
    result = service.generate(**SCOPE, assigned_service_resource='Sam', remove_canceled=False)
    assert result.error and result.records == ()


def test_selected_rep_beyond_first_page_is_found_before_display_limit():
    service, queries = source_pages([
        [appointment(index, 'Other') for index in range(1000)],
        [appointment(1000, 'Sam'), appointment(1001, 'Sam')], [],
    ])
    records = service.records(**SCOPE, assigned_service_resource='Sam', limit=1)
    assert len(records) == 1
    assert records[0].source_id == '0WO000000001000AAA'
    assert len(queries) == 3


def test_replacement_adapter_names_and_records_have_separate_responsibilities():
    shared = ModSheetRecord('shared', assigned_service_resources=('Alex', 'Sam'))
    calls = []
    class Adapter:
        def rep_assignments(self, **filters):
            calls.append(('names', filters))
            return (('Sam', 'Alex', 'Sam'), ('Alex',))
        def mod_sheets(self, **filters):
            calls.append(('records', filters))
            return (shared,)
    service = SalesforceSandboxService(Adapter(), rep_repository=ModSheetRepRepository(MemoryDb()))
    assert service.field(RESOURCE).field.values == ()
    assert not service.field(RESOURCE).saved
    assert calls == []
    assert service.refresh_reps(**SCOPE).field.values == ('Alex', 'Sam')
    assert service.field(RESOURCE).field.values == ('Alex', 'Sam')
    assert service.field(RESOURCE).totals == {'Alex': 1.5, 'Sam': 0.5}
    assert [kind for kind, _ in calls] == ['names']
    assert service.records(**SCOPE, assigned_service_resource='Sam') == (shared,)
    assert service.records(**SCOPE, assigned_service_resource='Nobody') == ()
    assert all(filters['limit'] is None for kind, filters in calls if kind == 'records')
    assert 'Service_Territory__c' not in inspect.getsource(SalesforceCliAdapter)
    assert '_assigned_resource_values' not in inspect.getsource(SalesforceCliAdapter)


def test_names_only_read_handles_appointments_without_customer_or_status_fields():
    rows = [{'Id': '08p000000000001AAA', 'FSSK__FSK_Work_Order__c': 'work-order',
             'SchedStartTime': '2026-09-19T17:30:00Z',
             'FSSK__FSK_Assigned_Service_Resource__r': {'Name': 'Saved Rep'}},
            {'Id': '08p000000000002AAA', 'FSSK__FSK_Assigned_Service_Resource__r': None}]
    service, queries = source_pages([rows, []])
    result = service.refresh_reps(**SCOPE)
    assert not result.error and result.field.values == ('Saved Rep',)
    assert all(query.startswith(PROJECTION + ' FROM ') for query in queries)
    assert all('Status' not in query and 'LastModifiedDate' not in query for query in queries)


def test_list_survives_restart_and_replaces_instead_of_appending(tmp_path):
    path = tmp_path / 'printer.db'
    repo = ModSheetRepRepository(Database(path))
    service, queries = source_pages([[appointment(1, 'Old Rep')], [],
                                     [appointment(2, 'New Rep')], [], []], repo)
    assert service.field(RESOURCE).saved is False and queries == []
    assert service.refresh_reps(**SCOPE).field.values == ('Old Rep',)
    restarted = SalesforceSandboxService(object(), rep_repository=ModSheetRepRepository(Database(path)))
    assert restarted.field(RESOURCE).field.values == ('Old Rep',)
    assert restarted.field(RESOURCE).saved
    assert service.refresh_reps(**dict(SCOPE, market_segment='Seattle')).field.values == ('New Rep',)
    assert restarted.field(RESOURCE).field.values == ('New Rep',)
    assert service.refresh_reps(**SCOPE).field.values == ()
    assert restarted.field(RESOURCE).saved and restarted.field(RESOURCE).field.values == ()
    assert len(queries) == 5


def test_failed_refresh_keeps_saved_names_and_generation_still_reads_live_records(tmp_path):
    repo = ModSheetRepRepository(Database(tmp_path / 'printer.db'))
    repo.replace(('Existing Rep',))
    service, queries = source_pages([[appointment(1, 'Partial')], OSError('failed'),
                                     [appointment(2, 'Live Rep')], []], repo)
    result = service.refresh_reps(**SCOPE)
    assert result.error
    assert service.field(RESOURCE).field.values == ('Existing Rep',)
    assert service.records(**SCOPE, assigned_service_resource='Live Rep')[0].assigned_service_resources == ('Live Rep',)
    assert service.field(RESOURCE).field.values == ('Existing Rep',)
    assert len(queries) == 4


def test_names_persistence_remains_a_repository_not_source_or_frontend_storage():
    root = RUNTIME.parents[2]
    repository = (root / 'mod_sheets/rep_repository.py').read_text()
    assert 'FSSK__' not in repository and 'salesforce' not in repository.lower()
    assert 'connect(' not in inspect.getsource(SalesforceSandboxService)
    assert 'localStorage' not in RUNTIME.read_text()
    assert 'self.mod_sheets(' not in inspect.getsource(SalesforceCliAdapter.rep_assignments)


def test_cached_get_never_queries_and_refresh_post_ignores_status_and_selected_rep():
    flask = pytest.importorskip('flask')
    from printer_app.salesforce_sandbox.web import blueprint
    service, queries = source_pages([[appointment(1, 'Market Rep')], []])
    app = flask.Flask(__name__)
    app.register_blueprint(blueprint(service))
    client = app.test_client()
    get = client.get('/salesforce-sandbox/api/field/assigned_service_resource',
                     query_string={'startdate': DAY, 'marketsegment': 'Seattle'})
    assert get.status_code == 200 and not get.json['saved'] and queries == []
    response = client.post('/salesforce-sandbox/api/reps/refresh', data=dict(
        startdate=DAY, enddate=DAY, marketsegment="King's Market", productCategory='Windows',
        sourceType='Internet', removeCanceled='true', removeUnconfirmed='true',
        assignedServiceResource='Other'))
    assert response.status_code == 200 and response.json['saved']
    assert response.json['field']['values'] == ['Market Rep']
    assert response.json['field']['totals'] == {'Market Rep': 1}
    assert "Market__c = 'King\\'s Market'" in queries[0]
    assert "LeadSource = 'Internet'" in queries[0]
    assert 'Status' not in queries[0] and 'LastModifiedDate' not in queries[0]
    assert 'Other' not in queries[0]
    assert client.get('/salesforce-sandbox/api/reps/refresh').status_code == 405
    assert client.get('/salesforce-sandbox/api/field/assigned_service_resource').json['field']['values'] == ['Market Rep']
    assert len(queries) == 2


def test_daily_refresh_uses_configured_local_today_not_old_browser_date(monkeypatch):
    flask = pytest.importorskip('flask')
    from datetime import datetime, timezone
    from printer_app.salesforce_sandbox import web
    from printer_app.salesforce_sandbox.service import FieldSnapshot
    from printer_app.salesforce_sandbox.adapter import PortalField
    captured = []
    class Clock:
        @staticmethod
        def now(zone):
            return datetime(2026, 9, 20, 1, tzinfo=timezone.utc).astimezone(zone)
    class Service:
        def refresh_reps(self, **scope):
            captured.append(scope)
            return FieldSnapshot(RESOURCE, PortalField('Reps', 'assigned_service_resources', ()), saved=True)
    monkeypatch.setattr(web, 'datetime', Clock)
    app = flask.Flask(__name__)
    @app.before_request
    def config():
        flask.g.printer_config = SimpleNamespace(timezone='America/Los_Angeles')
    app.register_blueprint(web.blueprint(Service()))
    response = app.test_client().post('/salesforce-sandbox/api/reps/refresh',
        data=dict(dateScope='today', startdate='2000-01-01', enddate='2000-01-01'))
    assert response.status_code == 200
    assert captured[0]['start_date'] == captured[0]['end_date'] == DAY


BROWSER = r'''
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
class Element extends EventTarget {
  constructor(value='') { super(); this.value=value; this.textContent=''; this.disabled=false;
    this.hidden=false; this.dataset={selected:value}; this.options=[]; }
  replaceChildren() { this.options=[]; this.value=''; }
  appendChild(option) { this.options.push(option); }
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const reply=(values,saved=true,totals={})=>({ok:true,json:async()=>({ok:true,saved,field:{values,totals}})});
const ids={};
for (const id of ['modSourceStatus','modSourceUser','modSourceError','modSourceRetry','modSubmit',
    'modTestPrint','modSourceLog','modSourceClear','modSheetForm','modRefreshReps','modRepsStatus',
    'marketSegment','productCategory','srcType','assignedServiceResource',
    'startDate','endDate','canceled','unconfirmed','colorCode']) ids[id]=new Element();
ids.startDate.value=ids.endDate.value='9/19/2026';
ids.canceled.checked=ids.unconfirmed.checked=true;
ids.productCategory.value=ids.productCategory.dataset.selected='All';
ids.srcType.value=ids.srcType.dataset.selected='All';
const market=ids.marketSegment, rep=ids.assignedServiceResource, form=ids.modSheetForm;
const settings=process.argv[3]==='settings';
form.dataset={mode:settings?'settings':'manual',requireConnection:settings?'false':'true'};
market.value=market.dataset.selected='Olympia'; rep.value=rep.dataset.selected='Shared Rep';
const state={dataset:{connectionUrl:'/connection',fieldUrl:'/field/__FIELD__',repsRefreshUrl:'/reps/refresh',csrf:'TOKEN'}};
globalThis.document={querySelector:()=>state,getElementById:id=>ids[id],createElement:()=>new Element()};
globalThis.window={location:{href:'https://stats.test/mod'}};
globalThis.FormData=class {constructor(form){} entries(){return [['marketsegment',market.value],['assignedServiceResource',rep.value]];}};
const requests=[];
let releaseMarkets, releaseSaved, cachedReads=0;
const marketPromise=new Promise(resolve=>releaseMarkets=resolve);
globalThis.fetch=async (input,options={})=>{
  const url=new URL(input,window.location.href);
  if(url.pathname==='/connection') return {ok:true,json:async()=>({ok:true,username:'test'})};
  if(url.pathname==='/field/market_segment') return marketPromise;
  if(url.pathname==='/field/assigned_service_resource') {
    cachedReads++; return new Promise(resolve=>releaseSaved=resolve);
  }
  if(url.pathname==='/reps/refresh') return new Promise((resolve,reject)=>{
    assert.equal(options.method,'POST');
    requests.push({params:Object.fromEntries(options.body),resolve:(values,totals)=>resolve(reply(values,true,totals)),reject});
  });
  return reply(['All']);
};
function change(value){market.value=value; market.dispatchEvent(new Event('change'));}
function choose(value){rep.value=value; rep.dispatchEvent(new Event('change'));}
function refresh(){ids.modRefreshReps.dispatchEvent(new Event('click'));}
function submit(){const e=new Event('submit',{cancelable:true});form.dispatchEvent(e);return !e.defaultPrevented;}
(0,eval)(readFileSync(process.argv[2],'utf8'));
await tick();
assert.equal(cachedReads,1);
assert.equal(requests.length,0,'Opening a page must not query reps from the source.');
assert.equal(submit(),false,'Cannot submit a disabled initial rep field as All.');
releaseSaved(reply(['Olympia Rep','Shared Rep'])); await tick();
assert.equal(rep.value,'Shared Rep');
assert.equal(rep.disabled,false,'Local saved reps load without waiting for source filters.');
assert.equal(ids.modTestPrint.disabled,true);
assert.equal(ids.modSubmit.disabled,!settings,'Manual generation waits for its report filters.');
releaseMarkets(reply(['Olympia','Seattle',"King's & North"])); await tick();
assert.equal(requests.length,0);
assert.equal(ids.modSubmit.disabled,false);
assert.equal(ids.modTestPrint.disabled,false);
assert.equal(ids.modRefreshReps.disabled,false);
assert.equal(submit(),true);
'''


def run_runtime(script, mode):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for MOD runtime tests.')
    result = subprocess.run([node, '--input-type=module', '-', str(RUNTIME), mode],
                            input=BROWSER + script, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('mode', ['manual', 'settings'])
def test_all_scope_edits_and_connection_retries_reuse_saved_list(mode):
    run_runtime(r'''
change('Seattle');
for (const id of ['startDate','endDate','productCategory','srcType','canceled','unconfirmed','colorCode']) {
  ids[id].value='changed'; ids[id].checked=false;
  ids[id].dispatchEvent(new Event('input')); ids[id].dispatchEvent(new Event('change'));
}
await tick();
assert.equal(requests.length,0);
assert.equal(cachedReads,1);
assert.equal(rep.value,'Shared Rep');
assert.equal(submit(),true);
ids.modSourceRetry.dispatchEvent(new Event('click')); await tick();
assert.equal(requests.length,0);
assert.equal(cachedReads,1,'Connection retry must not reread or refresh reps.');
assert.equal(rep.value,'Shared Rep');
assert.equal(submit(),true);
''', mode)


@pytest.mark.parametrize('mode', ['manual', 'settings'])
def test_refresh_posts_current_scope_only_and_replaces_list_not_appends(mode):
    run_runtime(r'''
change("King's & North");
ids.endDate.value='9/23/2026';
ids.productCategory.value='Windows'; ids.productCategory.dispatchEvent(new Event('change'));
ids.srcType.value='Canvass'; ids.srcType.dispatchEvent(new Event('change'));
refresh(); await tick();
assert.equal(requests.length,1);
assert.deepEqual(requests[0].params, {
  csrf:'TOKEN',marketsegment:"King's & North",startdate:'9/19/2026',enddate:'9/23/2026',
  productCategory:'Windows',sourceType:'Canvass',...(settings?{dateScope:'today'}:{}),
});
assert.equal(rep.value,'Shared Rep');
assert.equal(submit(),true,'The existing selection is still usable while refreshing.');
refresh(); await tick(); assert.equal(requests.length,1,'Ignore repeated clicks while busy.');
requests[0].resolve(['New Rep']); await tick();
assert.deepEqual(rep.options.map(o=>o.value),['','New Rep']);
assert.equal(rep.value,'');
assert.match(ids.modRepsStatus.textContent,/All selected/);
choose('New Rep'); refresh(); await tick();
requests[1].resolve([]); await tick();
assert.deepEqual(rep.options.map(o=>o.value),['']);
assert.equal(submit(),true);
''', mode)


@pytest.mark.parametrize('mode', ['manual', 'settings'])
def test_failed_refresh_preserves_old_list_and_selection_and_can_retry(mode):
    run_runtime(r'''
refresh(); await tick(); requests[0].reject(new Error('source unavailable')); await tick();
assert.equal(rep.value,'Shared Rep');
assert.deepEqual(rep.options.map(o=>o.value),['','Olympia Rep','Shared Rep']);
assert.equal(rep.disabled,false);
assert.equal(submit(),true);
assert.match(ids.modRepsStatus.textContent,/Existing reps kept/);
assert.equal(ids.modRefreshReps.disabled,false);
refresh(); await tick(); requests[1].resolve(['Shared Rep']); await tick();
assert.equal(rep.value,'Shared Rep');
assert.deepEqual(rep.options.map(o=>o.value),['','Shared Rep']);
''', mode)


@pytest.mark.parametrize('mode', ['manual', 'settings'])
def test_editing_scope_during_refresh_does_not_start_or_replace_explicit_request(mode):
    run_runtime(r'''
refresh(); await tick();
change('Seattle'); ids.endDate.value='9/30/2026'; ids.endDate.dispatchEvent(new Event('input'));
ids.canceled.checked=false; ids.canceled.dispatchEvent(new Event('change')); await tick();
assert.equal(requests.length,1);
assert.equal(requests[0].params.marketsegment,'Olympia');
requests[0].resolve(['Refreshed Rep']); await tick();
assert.deepEqual(rep.options.map(o=>o.value),['','Refreshed Rep']);
assert.equal(submit(),true);
''', mode)


@pytest.mark.parametrize('workflow', ['daily', 'test'])
def test_automatic_and_test_print_filter_whole_sheets_through_same_source(tmp_path, workflow):
    from datetime import datetime
    from printer_app.db import Database
    from printer_app.mod_sheets.policy import ModSheetAutomationSettings
    from printer_app.mod_sheets.repository import ModSheetAutomationRepository
    from printer_app.mod_sheets.service import DailyModSheetService, ModSheetTestPrintService
    from test_mod_sheet_automation import FakeQueue

    rows = [appointment(1, 'Alex', work_order_id='shared', scheduled='2026-09-21T17:00:00Z'),
            appointment(2, 'Sam', work_order_id='shared', scheduled='2026-09-21T17:00:00Z'),
            appointment(3, 'Other', scheduled='2026-09-21T18:00:00Z')]
    source, queries = source_pages([rows, []])
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    settings = ModSheetAutomationSettings(market_segment='Olympia', assigned_service_resource='Sam')
    repository.save_settings(settings)
    queue, rendered = FakeQueue(), []
    def renderer(records, color_code=False):
        rendered.extend(records)
        return b'%PDF-test'
    clock = lambda: datetime(2026, 9, 21, 7, tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
    if workflow == 'daily':
        service = DailyModSheetService(repository, source, queue, renderer, tmp_path,
                                       'America/Los_Angeles', clock=clock)
        result = service.run_due()
        assert len(queue.enqueued) == 1 and not queue.immediate
    else:
        service = ModSheetTestPrintService(repository, source, queue, renderer, tmp_path, clock=clock)
        result = service.run(settings, 'America/Los_Angeles', '0' * 32)
        assert len(queue.immediate) == 1 and not queue.enqueued
    assert result['status'] == 'queued'
    assert len(rendered) == 1
    assert rendered[0].assigned_service_resources == ('Alex', 'Sam')
    assert repository.settings() == settings
    assert all('2026-09-21T07:00:00Z' in query for query in queries)


@pytest.mark.parametrize('mode', ['manual', 'settings'])
def test_missing_or_empty_saved_list_never_automatically_fetches_reps(mode):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for MOD runtime tests.')
    for saved in (False, True):
        script = BROWSER.replace("releaseSaved(reply(['Olympia Rep','Shared Rep']))",
                                 'releaseSaved(reply([], ' + str(saved).lower() + '))')
        script = script.replace("assert.equal(rep.value,'Shared Rep');",
                                "assert.equal(rep.value,settings?'Shared Rep':'');")
        script += "assert.equal(requests.length,0);\nrefresh(); await tick(); assert.equal(requests.length,1); requests[0].resolve([]); await tick();"
        result = subprocess.run([node, '--input-type=module', '-', str(RUNTIME), mode],
                                input=script, text=True, capture_output=True, timeout=15)
        assert result.returncode == 0, result.stdout + result.stderr


def test_saved_names_load_when_source_is_offline():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for MOD runtime tests.')
    script = BROWSER[:BROWSER.index("releaseMarkets(reply(")]
    script = script.replace("return {ok:true,json:async()=>({ok:true,username:'test'})}",
                            "return {ok:false,json:async()=>({ok:false,error:'offline'})}")
    script += "assert.equal(rep.value,'Shared Rep'); assert.equal(requests.length,0); assert.equal(ids.modRefreshReps.disabled,true); assert.equal(ids.modSubmit.disabled,false);"
    result = subprocess.run([node, '--input-type=module', '-', str(RUNTIME), 'settings'],
                            input=script, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr



def test_only_one_weighted_total_per_rep_and_refresh_does_not_accumulate():
    rows = [appointment(i, 'Alex') for i in range(6)]
    for i in range(4):
        rows.extend([appointment(10 + i * 2, 'Alex', work_order_id=f'shared-{i}'),
                     appointment(11 + i * 2, 'Sam', work_order_id=f'shared-{i}')])
    service, _ = source_pages([rows, [], rows, []])
    first = service.refresh_reps(**SCOPE)
    assert first.field.values == ('Alex', 'Sam')
    assert first.totals == {'Alex': 8, 'Sam': 2}
    second = service.refresh_reps(**SCOPE)
    assert second.totals == first.totals
    assert service.field(RESOURCE).totals == first.totals


def test_counter_deduplicates_same_work_order_day_across_pages_and_uses_local_day():
    # Same lead has repeated assignment rows. The third name is not an extra lead.
    service, _ = source_pages([
        [appointment(1, 'Alex', work_order_id='shared', scheduled='2026-09-19T23:00:00Z')],
        [appointment(2, 'Sam', work_order_id='shared', scheduled='2026-09-20T01:00:00Z'),
         appointment(3, 'Alex', work_order_id='shared', scheduled='2026-09-20T01:00:00Z')],
        [appointment(4, 'Alex', work_order_id='shared', scheduled='2026-09-20T17:00:00Z')], [],
    ])
    result = service.refresh_reps(**dict(SCOPE, end_date='2026-09-20'))
    assert result.totals == {'Alex': 1.5, 'Sam': 0.5}


def test_shared_credit_is_half_even_with_three_reps_and_blank_names_do_not_count():
    service, _ = source_pages([[
        appointment(1, 'Alex', work_order_id='shared'),
        appointment(2, 'Sam', work_order_id='shared'),
        appointment(3, 'Jo', work_order_id='shared'),
        appointment(4, '', work_order_id='solo'),
        appointment(5, 'Solo', work_order_id='solo'),
        appointment(6, ' ', work_order_id='empty'),
    ], []])
    assert service.refresh_reps(**SCOPE).totals == {'Alex': 0.5, 'Jo': 0.5, 'Sam': 0.5, 'Solo': 1}


def test_counter_treats_duplicate_casing_as_one_rep_and_keeps_whole_names():
    service, _ = source_pages([[
        appointment(1, "O'Neil; Alex", work_order_id='solo'),
        appointment(2, " o'neil; alex ", work_order_id='solo'),
    ], []])
    result = service.refresh_reps(**SCOPE)
    assert result.field.values == ("O'Neil; Alex",)
    assert result.totals == {"O'Neil; Alex": 1}


def test_totals_and_legacy_names_survive_restart_without_source_queries(tmp_path):
    db = Database(tmp_path / 'printer.db')
    # Prior releases saved only a list. Do not make up totals or force a source read.
    db.set(REP_NAMES_KEY, ['Legacy Rep'])
    repository = ModSheetRepRepository(db)
    offline = SalesforceSandboxService(object(), rep_repository=repository)
    assert offline.field(RESOURCE).field.values == ('Legacy Rep',)
    assert offline.field(RESOURCE).totals == {}
    repository.replace(('Alex', 'Sam'), {'Alex': 8.5, 'Sam': 1})
    restarted = SalesforceSandboxService(object(), rep_repository=ModSheetRepRepository(Database(db.path)))
    assert restarted.field(RESOURCE).totals == {'Alex': 8.5, 'Sam': 1}
    assert db.get(REP_NAMES_KEY) == ['Alex', 'Sam']  # Existing data format unchanged.


def test_failed_refresh_keeps_total_and_empty_success_clears_it():
    repo = ModSheetRepRepository(MemoryDb())
    repo.replace(('Old Rep',), {'Old Rep': 8.5})
    service, _ = source_pages([[appointment(1, 'Partial')], OSError('failed'), []], repo)
    assert service.refresh_reps(**SCOPE).error
    saved = service.field(RESOURCE)
    assert saved.field.values == ('Old Rep',) and saved.totals == {'Old Rep': 8.5}
    empty = service.refresh_reps(**SCOPE)
    assert empty.field.values == () and empty.totals == {}
    assert service.field(RESOURCE).totals == {}


def test_names_and_totals_replace_in_one_transaction():
    db = MemoryDb()
    repo = ModSheetRepRepository(db)
    repo.replace(('Old Rep',), {'Old Rep': 2})
    # A storage failure between the two writes must roll back the names as well.
    db.conn.execute("CREATE TRIGGER fail_totals BEFORE UPDATE ON meta "
                    "WHEN NEW.key='mod_sheet_rep_totals' "
                    "BEGIN SELECT RAISE(ABORT, 'storage failed'); END")
    with pytest.raises(sqlite3.IntegrityError, match='storage failed'):
        repo.replace(('New Rep',), {'New Rep': 1})
    assert repo.snapshot() == (('Old Rep',), {'Old Rep': 2})


@pytest.mark.parametrize('missing', ['FSSK__FSK_Work_Order__c', 'SchedStartTime'])
def test_incomplete_assignment_does_not_replace_saved_total(missing):
    row = appointment(1, 'New Rep')
    del row[missing]
    repo = ModSheetRepRepository(MemoryDb())
    repo.replace(('Old Rep',), {'Old Rep': 3.5})
    service, _ = source_pages([[row]], repo)
    assert service.refresh_reps(**SCOPE).error
    assert service.field(RESOURCE).totals == {'Old Rep': 3.5}


@pytest.mark.parametrize('mode', ['manual', 'settings'])
def test_single_counter_labels_keep_plain_rep_values_and_refresh_behavior(mode):
    script = BROWSER.replace("reply(['Olympia Rep','Shared Rep'])",
                             "reply(['Olympia Rep','Shared Rep'],true,{'Olympia Rep':8.5,'Shared Rep':1})")
    script += r'''
assert.deepEqual(rep.options.map(o=>o.textContent),['All','Olympia Rep — 8.5','Shared Rep — 1']);
assert.equal(rep.value,'Shared Rep');
assert.equal(requests.length,0);
change('Seattle'); await tick();
assert.equal(requests.length,0,'Do not auto-query just to count.');
assert.equal(rep.value,'Shared Rep');
refresh(); await tick(); requests[0].reject(new Error('failed')); await tick();
assert.equal(rep.options[2].textContent,'Shared Rep — 1');
refresh(); await tick(); requests[1].resolve(['Shared Rep'],{'Shared Rep':2.5}); await tick();
assert.deepEqual(rep.options.map(o=>o.textContent),['All','Shared Rep — 2.5']);
assert.equal(rep.value,'Shared Rep','Counts must never become part of the report filter value.');
assert.equal(submit(),true);
assert.match(ids.modSourceLog.textContent,/"assignedServiceResource":"Shared Rep"/);
assert.doesNotMatch(ids.modSourceLog.textContent,/"assignedServiceResource":"Shared Rep —/);
'''
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for MOD runtime tests.')
    result = subprocess.run([node, '--input-type=module', '-', str(RUNTIME), mode],
                            input=script, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
