"""Execute field-specific offline search in the real browser runtime using Node."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'static' / 'gallery_offline.js'
CASES = Path(__file__).with_name('gallery_search_cases.json')

SETUP = r'''
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const code = readFileSync(process.argv[2], 'utf8');
const {GalleryOffline} = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
function freeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}
function runtimeFor(cards) {
  const stored = freeze(cards);
  const before = JSON.stringify(stored);
  const unexpected = () => assert.fail('Local search must not use the network or mutate storage');
  const runtime = new GalleryOffline({network:{json:unexpected, fetch:unexpected, isReachable:unexpected}});
  runtime.isEnabled = () => true;
  runtime.allCards = async () => stored;
  runtime.imageUrl = async id => '/already-cached/' + id;
  runtime.putCard = unexpected;
  return {runtime, unchanged:() => assert.equal(JSON.stringify(stored), before)};
}
const ids = result => result.items.map(item => item.id);
'''


def _run(script):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required to execute the offline search runtime.')
    result = subprocess.run(
        [node, '--input-type=module', '-', str(RUNTIME), str(CASES)],
        input=SETUP + script, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_offline_search_matches_shared_online_field_cases():
    _run(r'''
const fixture = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const {runtime, unchanged} = runtimeFor(fixture.cards.map(card => ({
  id:card.id,
  summary:{...card, filename:'synthetic-' + card.id + '.pdf', page:1, part:1},
  detail:{...card, notes:[{author:'Synthetic Author', body:card.notes_text || ''}]},
})));
for (const example of fixture.cases) {
  const result = await runtime.list({q:example.q, field:example.field, date:example.date || ''});
  assert.deepEqual(ids(result).sort(), [...example.ids].sort(), JSON.stringify(example));
}
unchanged();
''')


def test_offline_search_uses_fresh_selected_summary_and_preserves_blank_fields():
    _run(r'''
for (const [field, column] of Object.entries({rep:'assigned_service_resource',lead_name:'lead_name',address:'address'})) {
  const stored = [
    {id:'fresh', summary:{id:'fresh',[column]:'Current Value'}, detail:{[column]:'Obsolete Value'}},
    {id:'cleared', summary:{id:'cleared',[column]:''}, detail:{[column]:'Obsolete Value'}},
    {id:'null-fallback', summary:{id:'null-fallback',[column]:null}, detail:{[column]:'Fallback Value'}},
    {id:'missing-fallback', summary:{id:'missing-fallback'}, detail:{[column]:'Fallback Value'}},
  ];
  const {runtime, unchanged} = runtimeFor(stored);
  assert.deepEqual(ids(await runtime.list({q:'current',field})), ['fresh']);
  assert.deepEqual(ids(await runtime.list({q:'obsolete',field})), []);
  assert.deepEqual(ids(await runtime.list({q:'fallback',field})), ['missing-fallback','null-fallback']);
  unchanged();
}
const {runtime, unchanged} = runtimeFor([
  {id:'named',summary:{id:'named',lead_name:'Customer Default',address:'Other Place',assigned_service_resource:'Other Rep'},
   detail:{text:'Hidden Needle',notes_text:'Hidden Needle',filename:'Hidden Needle.pdf',
           notes:[{author:'Hidden',body:'Needle'}]}},
]);
assert.deepEqual(ids(await runtime.list({q:'cust'})), ['named']);
for (const field of ['lead_name','address','rep']) {
  assert.equal((await runtime.list({q:'needle',field})).total, 0);
}
for (const field of ['text','notes','assigned_service_resource','constructor','__proto__','',null]) {
  await assert.rejects(runtime.list({q:'customer',field}), /^Error: Choose Rep, Lead name, or Address\.$/);
}
unchanged();
''')


def test_offline_search_caps_queries_and_paginates_the_selected_date():
    _run(r'''
const cards = Array.from({length:30}, (_,index) => {
  const id = String(index).padStart(2,'0');
  return {id,summary:{id,lead_name:'Shared Customer',assigned_service_resource:'Shared Rep',
    document_date:index < 27 ? '2026-09-21' : index < 29 ? '2026-09-20' : null,page:1,part:index+1},detail:{}};
});
// Deliberately reverse storage order: list must sort a copy, not stored values.
const {runtime, unchanged} = runtimeFor(cards.reverse());
const first = await runtime.list({q:'shared',field:'rep',date:'2026-09-21'});
assert.equal(first.total,27);
assert.deepEqual(ids(first),Array.from({length:24},(_,i)=>String(i).padStart(2,'0')));
assert.deepEqual(first.dates,[{date:'2026-09-21',count:27},{date:'2026-09-20',count:2},{date:null,count:1}]);
assert.deepEqual(ids(await runtime.list({q:'shared',field:'rep',date:'2026-09-21',offset:24})),['24','25','26']);
assert.deepEqual(ids(await runtime.list({q:'shared',field:'rep',date:'undated'})),['29']);
assert.equal((await runtime.list({q:'shared '.repeat(20)+'absent',field:'rep'})).total,30);
assert.equal((await runtime.list({q:'shared'+' '.repeat(294)+'absent',field:'rep'})).total,30);
assert.equal((await runtime.list({q:'---',field:'rep'})).total,30);
assert.equal((await runtime.list({q:'"---"',field:'rep'})).total,0);
unchanged();
''')


def test_detail_refresh_updates_search_without_waiting_for_index_or_image_sync():
    _run(r'''
let stored = freeze({id:'card',image_revision:'downloaded-image',legacy_image:'keep cached bytes',
  summary:{id:'card',lead_name:'Former Lead',address:'Former Street',assigned_service_resource:'Former Rep',
           notes_count:0,image_revision:'downloaded-image'},
  detail:{lead_name:'Former Lead',address:'Former Street',assigned_service_resource:'Former Rep',notes:[]},
});
let freshDetail = {lead_name:'Current Lead',address:'Current Street',assigned_service_resource:'',
                   notes:[{body:'A synced note'}],image_revision:'not-yet-downloaded-image'};
const requests = [];
const unexpected = () => assert.fail('Search must not fetch an index or image after refreshing detail');
const runtime = new GalleryOffline({network:{
  json:async url => {requests.push(url);assert.equal(url,'/gallery/api/items/card');return freshDetail;},
  fetch:unexpected,isReachable:unexpected,
}});
runtime.isEnabled = () => true;
runtime.card = async id => {assert.equal(id,'card');return stored;};
runtime.putCard = async card => {stored = freeze(card);};
runtime.allCards = async () => [stored];
runtime.imageUrl = async () => '/already-cached/downloaded-image';

await runtime.refreshDetail('card');
assert.deepEqual(ids(await runtime.list({q:'current',field:'lead_name'})),['card']);
assert.deepEqual(ids(await runtime.list({q:'current',field:'address'})),['card']);
for (const field of ['lead_name','address','rep']) {
  assert.equal((await runtime.list({q:'former',field})).total,0);
}
assert.equal(stored.summary.assigned_service_resource,'','A cleared rep must stay cleared');
assert.equal(stored.summary.notes_count,1);
assert.equal(stored.image_revision,'downloaded-image');
assert.equal(stored.summary.image_revision,'downloaded-image');
assert.equal(stored.legacy_image,'keep cached bytes');

freshDetail = {lead_name:'',address:'',assigned_service_resource:'Current Rep',notes:[],
               image_revision:'not-yet-downloaded-image'};
await runtime.refreshDetail('card');
assert.equal((await runtime.list({q:'current',field:'lead_name'})).total,0);
assert.equal((await runtime.list({q:'current',field:'address'})).total,0);
assert.deepEqual(ids(await runtime.list({q:'current',field:'rep'})),['card']);
assert.equal(stored.summary.lead_name,'');
assert.equal(stored.summary.address,'');
assert.equal(stored.image_revision,'downloaded-image');
assert.equal(stored.summary.image_revision,'downloaded-image');
assert.deepEqual(requests,['/gallery/api/items/card','/gallery/api/items/card']);
''')


def test_related_cards_keep_existing_name_or_address_matching():
    _run(r'''
const rows = [
  ['original','Jordan Example','123 Main St'],
  ['similar','Jordann Example','Different Address'],
  ['address','Another Customer','123 Main St'],
  ['unrelated','Someone Else','Other Place'],
].map(([id,name,address])=>({id,summary:{id,lead_name:name,address},detail:{lead_name:name,address}}));
const {runtime, unchanged} = runtimeFor(rows);
const result = await runtime.list({relatedId:'original'});
assert.deepEqual(ids(result),['address','original','similar']);
assert.equal(result.lead_name,'Jordan Example');
assert.equal(result.address,'123 Main St');
unchanged();
''')
