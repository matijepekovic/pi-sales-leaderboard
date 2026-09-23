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
RESOURCE_PATH = 'FSSK__FSK_Assigned_Service_Resource__r.Name'
MARKET_PATH = 'FSSK__FSK_Work_Order__r.Lead__r.Market__c'
RUNTIME = Path(__file__).resolve().parents[1] / 'static/mod_sheets/runtime.js'


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


def test_resource_options_are_distinct_market_scoped_and_not_cut_at_1000():
    first = [{'Name': f'Rep {index:04}'} for index in range(1000)]
    second = [{'Name': 'Rep 1000'}, {'Name': 'Rep 1001'}]
    service, queries = source_pages([first, second, []])

    result = service.field(RESOURCE, market_segment='Olympia')

    assert not result.error
    assert result.field.values == tuple(f'Rep {index:04}' for index in range(1002))
    assert len(queries) == 3
    assert all(f"{MARKET_PATH} = 'Olympia'" in query for query in queries)
    assert all(f'GROUP BY {RESOURCE_PATH} ORDER BY {RESOURCE_PATH} ASC LIMIT 1000' in query
               for query in queries)
    assert f"{RESOURCE_PATH} > 'Rep 0999'" in queries[1]
    assert f"{RESOURCE_PATH} > 'Rep 1001'" in queries[2]
    assert all('SchedStartTime' not in query for query in queries)


def test_resource_cache_is_per_market_and_all_market_has_no_market_predicate():
    service, queries = source_pages([
        [{'Name': 'Olympia Rep'}], [], [{'Name': 'Seattle Rep'}], [],
        [{'Name': 'Olympia Rep'}, {'Name': 'Seattle Rep'}], [],
    ])
    first = service.field(RESOURCE, market_segment=' Olympia ')
    assert first.field.values == ('Olympia Rep',)
    assert service.field(RESOURCE, market_segment='Seattle').field.values == ('Seattle Rep',)
    assert service.field(RESOURCE, market_segment='Olympia').field == first.field
    assert len(queries) == 4  # Returning to a market uses only that market's cached list.
    assert service.field(RESOURCE).field.values == ('Olympia Rep', 'Seattle Rep')
    assert all(MARKET_PATH not in query for query in queries[4:])


def test_market_and_name_cursor_are_escaped_without_splitting_names():
    service, queries = source_pages([[{'Name': "O'Neil; Alex"}], []])
    result = service.field(RESOURCE, market_segment="King's \\ North")
    assert not result.error
    assert result.field.values == ("O'Neil; Alex",)
    assert f"{MARKET_PATH} = 'King\\'s \\\\ North'" in queries[0]
    assert f"{RESOURCE_PATH} > 'O\\'Neil; Alex'" in queries[1]


@pytest.mark.parametrize('broken_page', [
    {}, {'records': [], 'done': False}, {'records': [], 'totalSize': 1},
    [{'Name': 'Rep One'}], [{'Name': None}], OSError('source unavailable'),
])
def test_incomplete_resource_read_is_not_returned_or_cached(broken_page):
    service, queries = source_pages([
        [{'Name': 'Rep One'}], broken_page,
        [{'Name': 'Rep One'}, {'Name': 'Rep Two'}], [],
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

    service, queries = source_pages([[{'Name': 'Market Rep'}], []])
    app = flask.Flask(__name__)
    app.register_blueprint(blueprint(service))
    response = app.test_client().get('/salesforce-sandbox/api/field/assigned_service_resource',
                                    query_string={'marketsegment': "King's Market"})
    assert response.status_code == 200
    assert response.json['field']['values'] == ['Market Rep']
    assert f"{MARKET_PATH} = 'King\\'s Market'" in queries[0]


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
