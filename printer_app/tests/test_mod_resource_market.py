"""Rep choices/filtering share the PDF records, date scope, and normalized boundary."""
import inspect
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.salesforce_sandbox.adapter import SalesforceCliAdapter
from printer_app.salesforce_sandbox.service import SalesforceSandboxService
from test_salesforce_sandbox import _appointment

RESOURCE = 'assigned_service_resource'
MARKET = 'FSSK__FSK_Work_Order__r.Lead__r.Market__c'
ASSIGNMENT = 'FSSK__FSK_Assigned_Service_Resource__r.Name'
DAY = '2026-09-19'
SCOPE = dict(start_date=DAY, end_date=DAY, market_segment='Olympia')
RUNTIME = Path(__file__).resolve().parents[1] / 'static/mod_sheets/runtime.js'


def appointment(index, name, **kwargs):
    kwargs.setdefault('work_order_id', f'0WO{index:012d}AAA')
    return _appointment(f'08p{index:012d}AAA', resource=name, **kwargs)


def source_pages(pages):
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
    return SalesforceSandboxService(adapter), queries


@pytest.mark.parametrize('market', ['Olympia', 'Federal Way', 'Seattle', "King's & North"])
def test_options_use_the_pdf_assignment_and_selected_dates_and_filters(market):
    service, queries = source_pages([[appointment(1, 'Assigned Rep')], []])
    result = service.field(RESOURCE, **dict(SCOPE, market_segment=market),
                           product_category='Windows', source_type='Canvass',
                           remove_canceled=True, remove_unconfirmed=True)
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
        assert "Status != 'Canceled'" in query
        assert 'LastModifiedDate != null' in query
        assert ASSIGNMENT in query.split(' FROM ')[0]
        assert ASSIGNMENT not in query.split(' WHERE ')[1]
        assert all(term not in query for term in ('ServiceResource WHERE', 'Service_Territory', 'GROUP BY'))


def test_resource_options_read_beyond_first_1000_appointments():
    first = [appointment(index, f'Rep {index:04}') for index in range(1000)]
    second = [appointment(1000, 'Rep 1000'), appointment(1001, 'Rep 1001')]
    service, queries = source_pages([{'records': first, 'done': True}, second, []])
    result = service.field(RESOURCE, **SCOPE)
    assert not result.error
    assert result.field.values == tuple(f'Rep {index:04}' for index in range(1002))
    assert len(queries) == 3
    assert f"Id > '{first[-1]['Id']}'" in queries[1]
    assert f"Id > '{second[-1]['Id']}'" in queries[2]


def test_changed_assignments_are_read_fresh_and_all_market_has_no_market_predicate():
    service, queries = source_pages([
        [appointment(1, 'Before Reassignment')], [],
        [appointment(1, 'After Reassignment')], [],
        [appointment(2, 'Seattle Rep')], [],
    ])
    assert service.field(RESOURCE, **SCOPE).field.values == ('Before Reassignment',)
    assert service.field(RESOURCE, **SCOPE).field.values == ('After Reassignment',)
    assert service.field(RESOURCE, **dict(SCOPE, market_segment='')).field.values == ('Seattle Rep',)
    assert len(queries) == 6
    assert all('Market__c =' not in query for query in queries[4:])


def test_no_appointments_is_successful_empty_options_not_unavailable():
    service, _ = source_pages([[]])
    result = service.field(RESOURCE, **SCOPE)
    assert not result.error
    assert result.field.values == ()


@pytest.mark.parametrize('metadata', [{'done': False}, {'done': True, 'totalSize': 3}])
def test_names_are_distinct_whole_names_and_all_short_pages_are_read(metadata):
    service, queries = source_pages([
        {'records': [appointment(1, "O'Neil; Alex")], **metadata},
        [appointment(2, "O'Neil; Alex"), appointment(3, 'Another Rep')], [],
    ])
    result = service.field(RESOURCE, **dict(SCOPE, market_segment="King's \\ North"))
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
    failed = service.field(RESOURCE, **SCOPE)
    assert failed.error and failed.field is None
    retried = service.field(RESOURCE, **SCOPE)
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
    assert service.field(RESOURCE, **scope).error
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


def test_record_workflow_can_use_a_replacement_adapter_with_only_normalized_records():
    shared = ModSheetRecord('shared', assigned_service_resources=('Alex', 'Sam'))
    other = ModSheetRecord('other', assigned_service_resources=('Other',))
    calls = []
    class Adapter:
        def mod_sheets(self, **filters):
            calls.append(filters)
            return (shared, other)
    service = SalesforceSandboxService(Adapter())
    assert service.field(RESOURCE, **SCOPE).field.values == ('Alex', 'Other', 'Sam')
    assert service.records(**SCOPE, assigned_service_resource='Sam') == (shared,)
    assert service.records(**SCOPE, assigned_service_resource='Nobody') == ()
    assert all(call['limit'] is None and 'assigned_service_resource' not in call for call in calls)
    assert 'Service_Territory__c' not in inspect.getsource(SalesforceCliAdapter)
    assert '_assigned_resource_values' not in inspect.getsource(SalesforceCliAdapter)


def test_field_endpoint_passes_the_same_scope_as_generate_but_never_selected_rep():
    flask = pytest.importorskip('flask')
    from printer_app.salesforce_sandbox.web import blueprint
    service, queries = source_pages([[appointment(1, 'Market Rep')], []])
    app = flask.Flask(__name__)
    app.register_blueprint(blueprint(service))
    response = app.test_client().get('/salesforce-sandbox/api/field/assigned_service_resource',
        query_string=dict(startdate=DAY, enddate=DAY, marketsegment="King's Market",
                          productCategory='Windows', sourceType='Internet',
                          removeCanceled='true', removeUnconfirmed='false', assignedServiceResource='Other'))
    assert response.status_code == 200
    assert response.json['field']['values'] == ['Market Rep']
    assert "Market__c = 'King\\'s Market'" in queries[0]
    assert "LeadSource = 'Internet'" in queries[0]
    assert 'LastModifiedDate != null' not in queries[0]
    assert 'Other' not in queries[0]


def test_daily_option_dates_use_configured_local_today_not_an_old_browser_date(monkeypatch):
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
        def field(self, key, **scope):
            captured.append(scope)
            return FieldSnapshot(key, PortalField('Reps', 'assigned_service_resources', ()))
    monkeypatch.setattr(web, 'datetime', Clock)
    app = flask.Flask(__name__)
    @app.before_request
    def config():
        flask.g.printer_config = SimpleNamespace(timezone='America/Los_Angeles')
    app.register_blueprint(web.blueprint(Service()))
    response = app.test_client().get('/salesforce-sandbox/api/field/assigned_service_resource',
        query_string=dict(dateScope='today', startdate='2000-01-01', enddate='2000-01-01'))
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
const reply=values=>({ok:true,json:async()=>({ok:true,field:{values}})});
const ids={};
for (const id of ['modSourceStatus','modSourceUser','modSourceError','modSourceRetry','modSubmit',
    'modTestPrint','modSourceLog','modSourceClear','modSheetForm',
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
const state={dataset:{connectionUrl:'/connection',fieldUrl:'/field/__FIELD__'}};
globalThis.document={querySelector:()=>state,getElementById:id=>ids[id],createElement:()=>new Element()};
globalThis.window={location:{href:'https://stats.test/mod'}};
globalThis.FormData=class {constructor(form){} entries(){return [['marketsegment',market.value],['assignedServiceResource',rep.value]];}};
const requests=[];
let releaseMarkets;
const marketPromise=new Promise(resolve=>releaseMarkets=resolve);
globalThis.fetch=async input=>{
  const url=new URL(input,window.location.href);
  if(url.pathname==='/connection') return {ok:true,json:async()=>({ok:true,username:'test'})};
  if(url.pathname==='/field/market_segment') return marketPromise;
  if(url.pathname==='/field/assigned_service_resource') return new Promise((resolve,reject)=>{
    requests.push({params:Object.fromEntries(url.searchParams),market:url.searchParams.get('marketsegment'),resolve:values=>resolve(reply(values)),reject});
  });
  return reply(['All']);
};
function change(value){market.value=value; market.dispatchEvent(new Event('change'));}
function choose(value){rep.value=value; rep.dispatchEvent(new Event('change'));}
function submit(){const e=new Event('submit',{cancelable:true});form.dispatchEvent(e);return !e.defaultPrevented;}
(0,eval)(readFileSync(process.argv[2],'utf8'));
await tick();
assert.equal(requests.length,0,'Rep lookup must wait for the selected market to be restored.');
releaseMarkets(reply(['Olympia','Seattle',"King's & North"]));
await tick();
assert.deepEqual(requests.map(r=>r.market),['Olympia']);
assert.equal(rep.disabled,true);
assert.equal(ids.modSubmit.disabled,true);
assert.equal(ids.modTestPrint.disabled,true);
assert.equal(submit(),false,'Cannot accidentally submit All while rep options are loading.');
requests[0].resolve(['Olympia Rep','Shared Rep']); await tick();
assert.equal(rep.value,'Shared Rep','Keep a valid saved selection in either form.');
assert.equal(ids.modSubmit.disabled,false);
assert.equal(ids.modTestPrint.disabled,false);
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
def test_market_changes_replace_rep_list_and_reset_only_invalid_selection(mode):
    run_runtime(r'''
change('Seattle'); await tick();
assert.equal(requests[1].market,'Seattle');
requests[1].resolve(['Seattle Rep','Shared Rep']); await tick();
assert.equal(rep.value,'Shared Rep');
choose('Seattle Rep');
change('Olympia'); await tick();
requests[2].resolve(['Olympia Rep']); await tick();
assert.deepEqual(rep.options.map(o=>o.value),['','Olympia Rep']);
assert.equal(rep.value,'','Do not reinsert a saved rep from the previous market.');
assert.equal(rep.dataset.selected,'');
change(''); await tick();
assert.equal(requests[3].market,'');
requests[3].resolve(['Olympia Rep','Seattle Rep']); await tick();
assert.deepEqual(rep.options.map(o=>o.value),['','Olympia Rep','Seattle Rep']);
change("King's & North"); await tick();
assert.equal(requests[4].market,"King's & North");
requests[4].resolve([]); await tick();
assert.deepEqual(rep.options.map(o=>o.value),['']);
assert.equal(submit(),true);
''', mode)


@pytest.mark.parametrize('mode', ['manual', 'settings'])
@pytest.mark.parametrize('late_failure', [False, True])
def test_slow_response_from_previous_market_cannot_overwrite_newer_selection(mode, late_failure):
    script = r'''
change('Seattle'); await tick();
change('Olympia'); await tick();
assert.equal(requests[1].market,'Seattle');
assert.equal(requests[2].market,'Olympia');
requests[2].resolve(['Olympia Rep']); await tick();
choose('Olympia Rep');
'''
    script += "requests[1].reject(new Error('old response'));\n" if late_failure else "requests[1].resolve(['Seattle Rep']);\n"
    run_runtime(script + r'''
await tick();
assert.deepEqual(rep.options.map(o=>o.value),['','Olympia Rep']);
assert.equal(rep.value,'Olympia Rep');
assert.equal(ids.modSourceError.hidden,true);
assert.equal(ids.modSubmit.disabled,false);
''', mode)


@pytest.mark.parametrize('mode', ['manual', 'settings'])
def test_failed_new_market_lookup_does_not_submit_old_rep_or_silent_all(mode):
    run_runtime(r'''
change('Seattle'); await tick();
requests[1].reject(new Error('source unavailable')); await tick();
assert.equal(rep.disabled,true);
assert.equal(ids.modSubmit.disabled,true);
assert.equal(ids.modTestPrint.disabled,true);
assert.equal(ids.modSourceError.hidden,false);
assert.equal(submit(),false);
change('Olympia'); await tick();
requests[2].resolve(['Olympia Rep']); await tick();
assert.equal(rep.disabled,false);
assert.equal(ids.modSubmit.disabled,false);
assert.equal(submit(),true);
''', mode)


@pytest.mark.parametrize('mode', ['manual', 'settings'])
def test_retry_does_not_temporarily_submit_a_disabled_rep_field(mode):
    run_runtime(r'''
change('Seattle'); await tick();
requests[1].reject(new Error('resource lookup failed')); await tick();
const originalFetch=globalThis.fetch;
let reconnect;
globalThis.fetch=input=>new URL(input,window.location.href).pathname==='/connection'
  ? new Promise(resolve=>reconnect=resolve) : originalFetch(input);
ids.modSourceRetry.dispatchEvent(new Event('click')); await tick();
assert.equal(rep.disabled,true);
assert.equal(ids.modSubmit.disabled,true,'Retry must not silently clear the selected rep.');
assert.equal(submit(),false);
reconnect({ok:false,json:async()=>({ok:false,error:'disconnected'})}); await tick();
assert.equal(ids.modSubmit.disabled,true);
assert.equal(submit(),false);
globalThis.fetch=originalFetch;
ids.modSourceRetry.dispatchEvent(new Event('click')); await tick();
assert.equal(requests[2].market,'Seattle');
requests[2].resolve(['Seattle Rep']); await tick();
assert.equal(rep.disabled,false);
assert.equal(ids.modSubmit.disabled,false);
assert.equal(submit(),true);
''', mode)


@pytest.mark.parametrize('mode', ['manual', 'settings'])
def test_option_requests_follow_dates_products_sources_and_status_flags(mode):
    run_runtime(r'''
assert.equal(requests[0].params.startdate,'9/19/2026');
assert.equal(requests[0].params.enddate,'9/19/2026');
assert.equal(requests[0].params.dateScope,settings?'today':undefined);
assert.equal(requests[0].params.removeCanceled,'true');
assert.equal(requests[0].params.assignedServiceResource,undefined);
ids.productCategory.value='Windows'; ids.productCategory.dispatchEvent(new Event('change')); await tick();
assert.equal(requests[1].params.productCategory,'Windows');
requests[1].resolve(['Shared Rep']); await tick();
ids.srcType.value='Canvass'; ids.srcType.dispatchEvent(new Event('change')); await tick();
assert.equal(requests[2].params.sourceType,'Canvass');
requests[2].resolve(['Shared Rep']); await tick();
ids.canceled.checked=false; ids.canceled.dispatchEvent(new Event('change')); await tick();
assert.equal(requests[3].params.removeCanceled,'false');
requests[3].resolve(['Shared Rep']); await tick();
ids.unconfirmed.checked=false; ids.unconfirmed.dispatchEvent(new Event('change')); await tick();
assert.equal(requests[4].params.removeUnconfirmed,'false');
requests[4].resolve(['Shared Rep']); await tick();
ids.endDate.value='9/20/2026'; ids.endDate.dispatchEvent(new Event('input')); await tick();
assert.equal(submit(),false);
ids.endDate.dispatchEvent(new Event('change')); await tick();
assert.equal(requests[5].params.enddate,'9/20/2026');
requests[5].resolve(['New Day Rep']); await tick();
assert.equal(submit(),true);
choose('New Day Rep'); await tick();
ids.colorCode.dispatchEvent(new Event('change')); await tick();
assert.equal(requests.length,6,'Rep or color selection must not reload/restrict the options.');
''', mode)


def test_saved_daily_rep_is_not_erased_just_because_they_have_no_appointments_today():
    run_runtime(r'''
ids.modSourceRetry.dispatchEvent(new Event('click')); await tick();
requests[1].resolve([]); await tick();
assert.equal(rep.value,'Shared Rep');
assert.equal(submit(),true);
change('Seattle'); await tick();
requests[2].resolve([]); await tick();
assert.equal(rep.value,'','An explicit market change resets an invalid selection.');
''', 'settings')


@pytest.mark.parametrize('mode', ['manual', 'settings'])
def test_date_edit_immediately_invalidates_inflight_old_scope(mode):
    run_runtime(r'''
change('Seattle'); await tick();
ids.endDate.value='9/21/2026'; ids.endDate.dispatchEvent(new Event('input'));
requests[1].resolve(['Old Day Rep']); await tick();
assert.equal(submit(),false);
assert.equal(rep.disabled,true);
ids.endDate.dispatchEvent(new Event('change')); await tick();
requests[2].resolve(['New Day Rep']); await tick();
assert.deepEqual(rep.options.map(o=>o.value),['','New Day Rep']);
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
