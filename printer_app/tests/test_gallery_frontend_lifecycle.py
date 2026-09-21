"""Exercise live Gallery modules against synthetic lifecycle changes."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading

import pytest


STATIC = Path(__file__).resolve().parents[1] / 'static'


def test_offline_sync_refreshes_revisions_retries_images_and_removes_only_missing_mornings():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required to execute the browser module regression.')
    script = r'''
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const code = readFileSync(process.argv[2], 'utf8');
const {GalleryOffline} = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
globalThis.window = {isSecureContext:true};
globalThis.localStorage = {getItem:() => '1'};
const clone = value => value === undefined ? undefined : structuredClone(value);
const records = new Map();
const images = new Map();
const key = input => {
  const url = new URL(typeof input === 'string' ? input : input.url, 'https://stats.test');
  return url.pathname + url.search;
};
const cache = {
  match:async input => images.get(key(input))?.clone(),
  put:async (input,response) => { images.set(key(input), response.clone()); },
  keys:async () => [...images.keys()].map(path => new Request('https://stats.test' + path)),
  delete:async input => images.delete(key(input)),
};
const morning = {id:'card',origin:'morning',image_revision:'morning-1',search_revision:1,
  notes_count:0,document_date:'2026-09-21',page:1,part:1,lead_name:'Old Customer'};
records.set('card', {id:'card',summary:clone(morning),detail:{...morning,text:'old details',notes:[]},
  image_revision:'morning-1'});
records.set('retained-scan', {id:'retained-scan',summary:{id:'retained-scan',origin:'scan'},
  detail:{id:'retained-scan',notes:[]}});
records.set('removed-morning', {id:'removed-morning',summary:{id:'removed-morning',origin:'morning'},
  detail:{id:'removed-morning',notes:[]}});
let summaries = [{...morning,search_revision:2,lead_name:'Updated Customer'}];
let responseDetail = {...summaries[0],text:'new phone product and assigned reps',phone_dial:'',notes:[]};
let failDownload = false;
const detailRequests = [], imageRequests = [];
const pending = [{id:'unsent-note',item_id:'removed-morning',body:'Keep this pending note'}];
const network = {
  isReachable:() => true,
  json:async url => {
    if (url === '/gallery/api/offline/index') return {items:clone(summaries)};
    detailRequests.push(url);
    return clone(responseDetail);
  },
  fetch:async url => {
    imageRequests.push(url);
    if (failDownload) throw new Error('temporary image failure');
    return new Response('scanned image bytes', {headers:{'Content-Type':'image/png',
      'Vary':'Cookie', 'Cache-Control':'no-store'}});
  },
};
const offline = new GalleryOffline({network});
offline.subject = 'owner'; offline.allowed = true;
offline.imageCache = async () => cache;
offline.card = async id => clone(records.get(id));
offline.putCard = async card => records.set(card.id, clone(card));
offline.allCards = async () => [...records.values()].map(clone);
offline.pendingNotes = async () => clone(pending);
offline.flushPending = async () => {};
offline.db = {transaction:store => {
  assert.equal(store,'cards','Placeholder cleanup must not delete queued notes');
  const tx = {objectStore:() => ({delete:id => records.delete(id)})};
  queueMicrotask(() => tx.oncomplete?.());
  return tx;
}};
await cache.put(offline.imagePath('card','morning-1'),new Response('morning image bytes'));
await cache.put(offline.imagePath('removed-morning'),new Response('removed morning bytes'));
await cache.put(offline.imagePath('retained-scan'),new Response('retained scan bytes'));

await offline.sync();
assert.equal(detailRequests.length,1,'Search changes refresh detail even with unchanged note count');
assert.equal(imageRequests.length,0,'Unchanged images do not download again');
assert.equal((await offline.list({q:'Updated Customer',field:'lead_name'})).total,1);
assert.equal((await offline.detail('card')).text,'new phone product and assigned reps');
assert.equal(records.has('removed-morning'),false,'Missing morning card must disappear');
assert.equal(await cache.match(offline.imagePath('removed-morning')),undefined);
assert.equal(records.has('retained-scan'),true,'Absent saved scans preserve existing offline retention');
assert.ok(await cache.match(offline.imagePath('retained-scan')));
assert.equal(pending.length,1,'Queued notes survive placeholder cleanup');

summaries = [{...morning,origin:'scan',image_revision:'scan-2',search_revision:3,lead_name:'Corrected Customer'}];
responseDetail = {...summaries[0],text:'corrected searchable scan',phone_dial:'',notes:[]};
failDownload = true;
await offline.sync();
assert.equal(records.get('card').summary.image_revision,'scan-2');
assert.equal(records.get('card').image_revision,'morning-1','Failed image cannot advance downloaded revision');
assert.equal(await offline.imageUrl('card'),offline.imagePath('card','morning-1'));
assert.equal(detailRequests.length,2);

failDownload = false;
await offline.sync();
assert.equal(imageRequests.length,2,'The next sync retries a failed replacement');
assert.ok(imageRequests.every(url => url === '/gallery/image/card?v=scan-2'));
assert.equal(detailRequests.length,2,'Unchanged search revision does not refetch detail');
assert.equal(records.get('card').image_revision,'scan-2');
assert.equal(await offline.imageUrl('card'),offline.imagePath('card','scan-2'));
assert.equal(await (await cache.match(offline.imagePath('card','scan-2'))).text(),'scanned image bytes');
const storedImage = await cache.match(offline.imagePath('card','scan-2'));
assert.equal(storedImage.headers.get('Content-Type'),'image/png');
assert.equal(storedImage.headers.get('Vary'),null,'Virtual images do not vary by the live session cookie');
assert.equal(storedImage.headers.get('Cache-Control'),null,'Virtual images do not inherit no-store');
assert.equal(await cache.match(offline.imagePath('card','morning-1')),undefined,'Obsolete image is removed');
assert.equal((await offline.list({q:'Corrected Customer',field:'lead_name'})).total,1);
assert.equal((await offline.list({q:'Old Customer',field:'lead_name'})).total,0);
assert.equal((await offline.detail('card')).text,'corrected searchable scan');
assert.equal((await offline.detail('card')).origin,'scan');

// An already downloaded card upgrades its contact contract once, without an
// unrelated note, search, or image change.
delete records.get('card').detail.phone_dial;
responseDetail.phone_dial = '+13605550100';
await offline.sync();
assert.equal(detailRequests.length,3,'Legacy detail acquires the contact fields');
assert.equal((await offline.detail('card')).phone_dial,'+13605550100');
await offline.sync();
assert.equal(detailRequests.length,3,'Upgraded contact detail is retained');

// Conflicting references can disable a number without changing searchable text.
// Snapshot replacement advances the existing search revision for that date.
summaries[0].search_revision++;
responseDetail.search_revision = summaries[0].search_revision;
responseDetail.phone_dial = '';
await offline.sync();
assert.equal(detailRequests.length,4,'Reference-only changes refresh contact detail');
assert.equal((await offline.detail('card')).phone_dial,'');
summaries[0].search_revision++;
responseDetail.search_revision = summaries[0].search_revision;
responseDetail.phone_dial = '+13605550100';
await offline.sync();
assert.equal(detailRequests.length,5,'Resolved references restore the contact number');
assert.equal((await offline.detail('card')).phone_dial,'+13605550100');
await offline.sync();
assert.equal(detailRequests.length,5,'Unchanged snapshots do not refetch detail');
assert.equal(imageRequests.length,2,'Contact updates never redownload unchanged images');
console.log('offline lifecycle passed');
'''
    result = subprocess.run(
        [node, '--input-type=module', '-', str(STATIC / 'gallery_offline.js')],
        input=script, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'offline lifecycle passed' in result.stdout


def test_offline_sync_coalesces_refresh_after_an_older_index_and_recovers_from_errors():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required to execute the browser module regression.')
    script = r'''
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const code = readFileSync(process.argv[2], 'utf8');
const {GalleryOffline} = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
globalThis.window = {isSecureContext:true};
const deferred = () => {
  let resolve;
  const promise = new Promise(done => {resolve = done;});
  return {promise, resolve};
};
function setup(blocked = [1], failures = []) {
  const gates = new Map(blocked.map(pass => [pass, {started:deferred(), release:deferred()}]));
  const flags = {enabled:true, reachable:true};
  const records = new Map();
  const pending = [{id:'saved-note',item_id:'card',body:'Keep this note'}];
  let indexes = 0;
  let current = {id:'card',origin:'scan',lead_name:'Synthetic Customer',
    assigned_service_resource:'Old Rep',search_revision:1,image_revision:'same-image',
    document_date:'2026-09-21',notes_count:1,page:1,part:1};
  const runtime = new GalleryOffline({network:{
    isReachable:() => flags.reachable,
    json:async url => {
      if (url === '/gallery/api/offline/index') {
        const pass = ++indexes, snapshot = structuredClone(current), gate = gates.get(pass);
        if (gate) {gate.started.resolve(); await gate.release.promise;}
        if (failures.includes(pass)) throw new Error('Synthetic index failure');
        return {items:[snapshot]};
      }
      assert.equal(url, '/gallery/api/items/card');
      return {...structuredClone(current),notes:structuredClone(pending)};
    },
  }});
  runtime.subject = 'same-owner'; runtime.allowed = true;
  runtime.isEnabled = () => flags.enabled;
  runtime.flushPending = async () => {};
  runtime.pendingNotes = async () => structuredClone(pending);
  runtime.allCards = async () => [...records.values()].map(card => structuredClone(card));
  runtime.card = async id => structuredClone(records.get(id));
  runtime.putCard = async card => records.set(card.id, structuredClone(card));
  runtime.imageCache = async () => ({match:async () => new Response('unchanged image')});
  runtime.ensureImage = async () => runtime.imagePath('card','same-image');
  runtime.removeCachedImages = async () => {};
  runtime.imageUrl = async () => runtime.imagePath('card','same-image');
  return {runtime, flags, pending, gates, records, indexes:() => indexes,
    publish:rep => {current = {...current,assigned_service_resource:rep,search_revision:current.search_revision+1};}};
}

const refreshed = setup();
const first = refreshed.runtime.sync();
await refreshed.gates.get(1).started.promise;
refreshed.publish('Fresh Rep');
await Promise.all(Array.from({length:6}, () => refreshed.runtime.sync()));
assert.equal(refreshed.indexes(),1,'Concurrent refreshes must not start overlapping index passes');
refreshed.gates.get(1).release.resolve();
await first;
assert.equal(refreshed.indexes(),2,'Repeated refreshes coalesce into exactly one fresh index pass');
assert.equal((await refreshed.runtime.list({q:'Fresh',field:'rep'})).total,1);
assert.equal((await refreshed.runtime.list({q:'Old',field:'rep'})).total,0);
assert.equal(refreshed.records.get('card').summary.search_revision,2);
assert.equal(refreshed.records.get('card').image_revision,'same-image');
assert.equal(refreshed.pending[0].body,'Keep this note');
assert.equal(refreshed.runtime.subject,'same-owner');
assert.equal(refreshed.runtime.syncing,false);

// A later publication during the follow-up pass deserves its own fresh pass.
const later = setup([1,2]);
const laterSync = later.runtime.sync();
await later.gates.get(1).started.promise;
later.publish('Middle Rep');
await later.runtime.sync();
later.gates.get(1).release.resolve();
await later.gates.get(2).started.promise;
later.publish('Latest Rep');
await Promise.all([later.runtime.sync(),later.runtime.sync()]);
later.gates.get(2).release.resolve();
await laterSync;
assert.equal(later.indexes(),3);
assert.equal((await later.runtime.list({q:'Latest',field:'rep'})).total,1);

// Permission/network changes suppress the follow-up without leaving a stale latch.
for (const guard of ['allowed','enabled','reachable']) {
  const stopped = setup();
  const running = stopped.runtime.sync();
  await stopped.gates.get(1).started.promise;
  await stopped.runtime.sync();
  if (guard === 'allowed') stopped.runtime.allowed = false;
  else stopped.flags[guard] = false;
  stopped.gates.get(1).release.resolve();
  await running;
  assert.equal(stopped.indexes(),1);
  assert.equal(stopped.runtime.syncing,false);
  assert.equal(stopped.runtime.syncRequested,false);
  stopped.runtime.allowed = stopped.flags.enabled = stopped.flags.reachable = true;
  await stopped.runtime.sync();
  assert.equal(stopped.indexes(),2,'A later allowed sync still runs normally');
}

const recovered = setup([1],[1]);
const recovering = recovered.runtime.sync();
await recovered.gates.get(1).started.promise;
recovered.publish('Recovered Rep');
await recovered.runtime.sync();
recovered.gates.get(1).release.resolve();
await recovering;
assert.equal(recovered.indexes(),2,'The queued fresh pass survives an earlier index error');
assert.equal((await recovered.runtime.list({q:'Recovered',field:'rep'})).total,1);

const failed = setup([1],[2]);
const failing = failed.runtime.sync();
await failed.gates.get(1).started.promise;
await failed.runtime.sync();
failed.gates.get(1).release.resolve();
await assert.rejects(failing,/Synthetic index failure/);
assert.equal(failed.runtime.syncing,false);
assert.equal(failed.runtime.syncRequested,false);
await failed.runtime.sync();
assert.equal(failed.indexes(),3,'A failed follow-up does not block the next sync');
console.log('coalesced offline sync passed');
'''
    result = subprocess.run(
        [node, '--input-type=module', '-', str(STATIC / 'gallery_offline.js')],
        input=script, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'coalesced offline sync passed' in result.stdout


def test_orphaned_pending_note_does_not_block_later_notes_or_get_discarded():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required to execute the browser module regression.')
    script = r'''
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const code = readFileSync(process.argv[2], 'utf8');
const {GalleryOffline} = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
function setup(status) {
  const pending = new Map([
    ['orphan-note',{id:'orphan-note',item_id:'removed-morning',author:'User',body:'Keep unsent note'}],
    ['valid-note',{id:'valid-note',item_id:'retained-scan',author:'User',body:'Sync this note'}],
  ]);
  const requests = [], refreshed = [];
  const runtime = new GalleryOffline({network:{
    isReachable:() => true,
    json:async (url, options) => {
      requests.push({url,note:options.body.get('note_id')});
      if (url.includes('removed-morning')) throw Object.assign(new Error('Synthetic failure'),{status});
      return {};
    },
  }});
  runtime.csrf = 'csrf-fixture';
  runtime.pendingNotes = async () => [...pending.values()];
  runtime.refreshDetail = async id => refreshed.push(id);
  runtime.db = {transaction:(store,mode) => {
    assert.equal(store,'pendingNotes'); assert.equal(mode,'readwrite');
    const tx = {objectStore:() => ({delete:id => pending.delete(id)})};
    queueMicrotask(() => tx.oncomplete?.());
    return tx;
  }};
  return {runtime,pending,requests,refreshed};
}
const absent = setup(404);
await absent.runtime.flushPending();
assert.deepEqual(absent.requests.map(request => request.note),['orphan-note','valid-note']);
assert.deepEqual([...absent.pending.keys()],['orphan-note'],'The missing card note must remain unsent');
assert.deepEqual(absent.refreshed,['retained-scan']);
await absent.runtime.flushPending();
assert.deepEqual([...absent.pending.keys()],['orphan-note'],'Retry must not silently discard the orphan');

for (const status of [400,401,403]) {
  const blocked = setup(status);
  await assert.rejects(blocked.runtime.flushPending(), error => error.status === status);
  assert.equal(blocked.requests.length,1);
  assert.equal(blocked.pending.size,2);
}
for (const status of [500,undefined]) {
  const paused = setup(status);
  await paused.runtime.flushPending();
  assert.equal(paused.requests.length,1,'Other failures keep the existing stop-and-retry behavior');
  assert.equal(paused.pending.size,2);
}
console.log('pending note lifecycle passed');
'''
    result = subprocess.run(
        [node, '--input-type=module', '-', str(STATIC / 'gallery_offline.js')],
        input=script, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'pending note lifecycle passed' in result.stdout


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies')
@pytest.mark.parametrize('engine', ['chromium', 'webkit'])
def test_visible_morning_card_and_open_viewer_refresh_when_scan_revision_arrives(tmp_path, engine):
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server
    from printer_app.app import create_app
    from printer_app.config import Config

    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path, env_file=env, secret_key='s' * 64, email_enabled=False))
    token = app.extensions['gallery_access'].issue_full_invite()
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    current = dict(id='a' * 64, origin='morning', image_revision='morning-1', search_revision=1,
                   lead_name='Example Customer', assigned_service_resource='', filename='morning.pdf',
                   page=1, part=1, notes_count=0, document_date='2026-09-21', notes=[])
    image = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a'
        'HioAAAAASUVORK5CYII='
    )

    def api_response(route):
        if '/gallery/api/items/' in route.request.url:
            body = dict(current)
        else:
            body = dict(items=[dict(current)], total=1, dates=[dict(date=current['document_date'], count=1)])
        route.fulfill(status=200, content_type='application/json', body=json.dumps(body))

    try:
        with sync_playwright() as pw:
            browser = getattr(pw, engine).launch()
            try:
                # These synthetic responses exist only in page.route. A service
                # worker would bypass them and query the deliberately empty DB.
                context = browser.new_context(viewport={'width':390, 'height':844},
                                              is_mobile=True, has_touch=True,
                                              service_workers='block')
                page = context.new_page()
                page.route('**/gallery/api/items**', api_response)
                page.route('**/gallery/image/**', lambda route: route.fulfill(
                    status=200, content_type='image/png', body=image,
                ))
                page.goto(f'http://127.0.0.1:{server.server_port}/gallery/access/{token}')
                card = page.locator('.gallery-card')
                expect(card).to_have_count(1)
                expect(card.locator('.gallery-card-subtitle')).to_contain_text('Awaiting scan')
                expect(card.locator('img')).to_have_attribute('src', '/gallery/image/' + current['id'] + '?v=morning-1')
                card.click()
                expect(page.locator('#gallerySource')).to_contain_text('Awaiting scan')
                expect(page.locator('#galleryFull')).to_have_attribute('src', '/gallery/image/' + current['id'] + '?v=morning-1')

                current.update(origin='scan', image_revision='scan-2', search_revision=2,
                               filename='scan.pdf', lead_name='Corrected Customer')

                expect(page.locator('#galleryFull')).to_have_attribute(
                    'src', '/gallery/image/' + current['id'] + '?v=scan-2', timeout=12000,
                )
                expect(card.locator('img')).to_have_attribute('src', '/gallery/image/' + current['id'] + '?v=scan-2')
                expect(card.locator('.gallery-card-subtitle')).not_to_contain_text('Awaiting scan')
                expect(page.locator('#gallerySource')).not_to_contain_text('Awaiting scan')
                expect(page.locator('#galleryTitle')).to_have_text('Corrected Customer')
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
