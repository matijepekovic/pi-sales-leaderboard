"""Market-dependent MOD resource options, complete source reads and browser races."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from printer_app.salesforce_sandbox.adapter import SalesforceCliAdapter
from printer_app.salesforce_sandbox.service import SalesforceSandboxService


RESOURCE = 'assigned_service_resource'
TERRITORY = 'Service_Territory__c'
RUNTIME = Path(__file__).resolve().parents[1] / 'static/mod_sheets/runtime.js'


def resource(index, name):
    return {'Id': f'0Hn{index:012d}AAA', 'Name': name}


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

    return SalesforceSandboxService(SalesforceCliAdapter(runner=runner)), queries


@pytest.mark.parametrize('market', ['Olympia', 'Federal Way', 'Seattle', 'King\'s & North'])
def test_every_selected_market_uses_its_sales_territory_not_appointment_history(market):
    service, queries = source_pages([{'records': [resource(1, 'Territory Rep')], 'done': True}])

    result = service.field(RESOURCE, market_segment=market)

    assert not result.error
    assert result.field.values == ('Territory Rep',)
    assert result.field.path == 'ServiceResource.Name'
    escaped = market.replace("'", "\\'") + ' - Sales'
    assert queries == [f"SELECT Id, Name FROM ServiceResource WHERE Name != null AND "
                       f"{TERRITORY} = '{escaped}' ORDER BY Id ASC LIMIT 1000"]
    # This assertion also prevents returning to the expensive customer-history lookup.
    assert all(term not in queries[0] for term in ('ServiceAppointment', 'WorkOrder', 'Lead__r',
                                                  'GROUP BY', 'IsActive', 'SchedStartTime'))


def test_resource_options_are_distinct_market_scoped_and_not_cut_at_1000():
    first = [resource(index, f'Rep {index:04}') for index in range(1000)]
    second = [resource(1000, 'Rep 1000'), resource(1001, 'Rep 1001')]
    service, queries = source_pages([{'records': first, 'done': True}, second, []])

    result = service.field(RESOURCE, market_segment='Olympia')

    assert not result.error
    assert result.field.values == tuple(f'Rep {index:04}' for index in range(1002))
    assert len(queries) == 3
    assert all(f"{TERRITORY} = 'Olympia - Sales'" in query for query in queries)
    assert all('FROM ServiceResource' in query and 'ORDER BY Id ASC LIMIT 1000' in query
               for query in queries)
    assert f"Id > '{first[-1]['Id']}'" in queries[1]
    assert f"Id > '{second[-1]['Id']}'" in queries[2]


def test_resource_cache_is_per_market_and_all_market_has_no_territory_predicate():
    service, queries = source_pages([
        [resource(1, 'Olympia Rep')], [], [resource(2, 'Seattle Rep')], [],
        [resource(1, 'Olympia Rep'), resource(2, 'Seattle Rep')], [],
    ])
    first = service.field(RESOURCE, market_segment=' Olympia ')
    assert first.field.values == ('Olympia Rep',)
    assert service.field(RESOURCE, market_segment='Seattle').field.values == ('Seattle Rep',)
    assert service.field(RESOURCE, market_segment='Olympia').field == first.field
    assert len(queries) == 4
    assert f"{TERRITORY} = 'Seattle - Sales'" in queries[2]
    assert service.field(RESOURCE).field.values == ('Olympia Rep', 'Seattle Rep')
    assert all(TERRITORY not in query for query in queries[4:])


def test_market_is_escaped_and_names_are_not_split_or_used_as_pagination_cursors():
    service, queries = source_pages([[resource(1, "O'Neil; Alex")], []])
    result = service.field(RESOURCE, market_segment="King's \\ North")
    assert not result.error
    assert result.field.values == ("O'Neil; Alex",)
    assert f"{TERRITORY} = 'King\\'s \\\\ North - Sales'" in queries[0]
    assert "Id > '0Hn000000000001AAA'" in queries[1]
    assert 'O\'Neil' not in queries[1]


@pytest.mark.parametrize('metadata', [{'done': False}, {'done': True, 'totalSize': 3}])
def test_same_name_resources_on_later_pages_do_not_break_pagination(metadata):
    service, queries = source_pages([
        {'records': [resource(1, 'Shared Rep')], **metadata},
        [resource(2, 'Shared Rep'), resource(3, 'Another Rep')], [],
    ])
    result = service.field(RESOURCE, market_segment='Olympia')
    assert not result.error
    assert result.field.values == ('Another Rep', 'Shared Rep')
    assert len(queries) == 3
    assert "Id > '0Hn000000000001AAA'" in queries[1]


@pytest.mark.parametrize('broken_page', [
    {}, {'records': [], 'done': False}, {'records': [], 'totalSize': 1},
    [resource(1, 'Rep One')], [resource(2, None)], [{'Name': 'No ID'}],
    [{'Id': "bad' OR Id != null", 'Name': 'Bad ID'}],
    [resource(2, 'Rep Two'), resource(2, 'Rep Two')],
    [resource(index, 'Too many') for index in range(1001)], OSError('source unavailable'),
    subprocess.TimeoutExpired('sf', 45),
])
def test_incomplete_resource_read_is_not_returned_or_cached(broken_page):
    service, queries = source_pages([
        [resource(1, 'Rep One')], broken_page,
        [resource(1, 'Rep One'), resource(2, 'Rep Two')], [],
    ])
    failed = service.field(RESOURCE, market_segment='Olympia')
    assert failed.error
    assert failed.field is None
    retried = service.field(RESOURCE, market_segment='Olympia')
    assert not retried.error
    assert retried.field.values == ('Rep One', 'Rep Two')
    assert len(queries) == 4


@pytest.mark.parametrize('market', [None, 12, 'x' * 129, 'Olympia\nSeattle'])
def test_invalid_market_never_reaches_source(market):
    service, queries = source_pages([])
    assert service.field(RESOURCE, market_segment=market).error
    assert queries == []


def test_field_http_endpoint_passes_selected_market_to_the_source():
    flask = pytest.importorskip('flask')
    from printer_app.salesforce_sandbox.web import blueprint

    service, queries = source_pages([[resource(1, 'Market Rep')], []])
    app = flask.Flask(__name__)
    app.register_blueprint(blueprint(service))
    response = app.test_client().get('/salesforce-sandbox/api/field/assigned_service_resource',
                                    query_string={'marketsegment': "King's Market"})
    assert response.status_code == 200
    assert response.json['field']['values'] == ['Market Rep']
    assert f"{TERRITORY} = 'King\\'s Market - Sales'" in queries[0]
    assert all('FROM ServiceResource' in query for query in queries)


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
    'marketSegment','productCategory','srcType','assignedServiceResource']) ids[id]=new Element();
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
    requests.push({market:url.searchParams.get('marketsegment'),resolve:values=>resolve(reply(values)),reject});
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
