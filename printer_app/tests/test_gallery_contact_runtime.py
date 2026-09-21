"""Execute the Gallery contact controller without a phone or network."""
from pathlib import Path
import shutil
import subprocess

import pytest


RUNTIME = Path(__file__).resolve().parents[1] / 'static' / 'gallery_contact.js'

SETUP = r'''
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';
// HTTP pages expose getRandomValues, but not the secure-only randomUUID API.
Object.defineProperty(globalThis,'crypto',{value:{getRandomValues:array=>webcrypto.getRandomValues(array)}});
const code = readFileSync(process.argv[2], 'utf8');
const {GalleryContact} = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
const storage = new Map();
globalThis.sessionStorage = {
  getItem:key => storage.get(key) ?? null,
  setItem:(key,value) => storage.set(key,String(value)),
  removeItem:key => storage.delete(key),
};
globalThis.fetch = () => assert.fail('The contact controller must not own network requests.');
class Element extends EventTarget {
  constructor() { super(); this.attributes=new Map(); this.value=''; this.textContent=''; this.disabled=false; }
  setAttribute(key,value) { this.attributes.set(key,String(value)); }
  getAttribute(key) { return this.attributes.get(key) ?? null; }
  removeAttribute(key) { this.attributes.delete(key); }
  focus() { this.focused=true; }
}
const originalId='a'.repeat(64), otherId='b'.repeat(64);
const item = Object.freeze({id:originalId,lead_name:'Original Customer',document_date:'2026-09-21',
  phone:'(312) 555-0198',phone_dial:'+13125550198'});
const other = Object.freeze({id:otherId,lead_name:'Other Customer',document_date:'2026-09-20',
  phone:'312-555-0177',phone_dial:'3125550177'});
const turn = () => new Promise(resolve=>setImmediate(resolve));
function setup(callbacks={}) {
  const fields={};
  for (const name of ['Title','Context','Form','Confirm','Cancel','Message']) fields[name]=new Element();
  fields.author=new Element(); fields.dial=new Element(); fields.message=new Element();
  fields.Form.querySelector=selector => selector==='[name="author"]' ? fields.author : null;
  globalThis.document={
    getElementById:id=>fields[id.replace('galleryContact','')] ?? null,
    querySelector:selector=>fields[selector.includes('"dial"')?'dial':'message'],
  };
  const saved=[], changed=[], remembered=[];
  let opened=0,closed=0;
  const runtime=new GalleryContact({
    openDialog:()=>{opened++;}, closeDialog:()=>{closed++;},
    saveNote:async value=>{saved.push({...value}); return {offline:false};},
    onSaved:(id,result)=>changed.push({id,result}),
    getAuthor:()=>'', rememberAuthor:author=>remembered.push(author), ...callbacks,
  });
  const event=(element,type)=>{ const event=new Event(type,{cancelable:true}); element.dispatchEvent(event); return event; };
  return {runtime,fields,saved,changed,remembered,event,opened:()=>opened,closed:()=>closed};
}
'''


def _run(script):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required to execute the Gallery contact runtime.')
    result = subprocess.run(
        [node, '--input-type=module', '-', str(RUNTIME)],
        input=SETUP + script, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_phone_links_open_confirmation_without_saving_and_cancel_is_empty():
    _run(r'''
const h=setup(); h.runtime.configure('device'); h.runtime.update(item,true);
assert.equal(h.fields.dial.getAttribute('href'),'tel:+13125550198');
assert.equal(h.fields.message.getAttribute('href'),'sms:+13125550198');
assert.equal(h.fields.dial.tabIndex,0);
assert.equal(h.fields.dial.title,'(312) 555-0198');
let nativeAllowed=false;
h.fields.dial.addEventListener('click',event=>{
  nativeAllowed=!event.defaultPrevented;
  assert.equal(h.opened(),1,'Confirmation is prepared synchronously before native navigation.');
  event.preventDefault(); // Only the test stops the phone navigation, after the controller.
});
h.event(h.fields.dial,'click');
assert.equal(nativeAllowed,true);
assert.equal(h.fields.Title.textContent,'Called?');
assert.equal(h.fields.Confirm.textContent,'Called');
assert.equal(h.fields.Context.textContent,'Original Customer · 2026-09-21 · (312) 555-0198');
assert.equal(h.saved.length,0,'Opening a phone app must never imply that contact happened.');
assert.equal(storage.size,1);
h.event(h.fields.Cancel,'click');
assert.equal(h.closed(),1); assert.equal(storage.size,0); assert.equal(h.saved.length,0);
h.event(h.fields.Cancel,'click');
assert.equal(h.closed(),1,'Repeated cancellation cannot request another history Back.');
assert.equal(h.runtime.restore(),false);
for (const [card,enabled] of [[item,false],[{...item,phone_dial:''},true],
    [{...item,phone_dial:'javascript:alert(1)'},true],[{...item,phone_dial:'123;body=bad'},true],[null,true]]) {
  h.runtime.update(card,enabled);
  assert.equal(h.fields.message.getAttribute('href'),null);
  assert.equal(h.fields.message.getAttribute('aria-disabled'),'true');
  assert.equal(h.fields.message.tabIndex,-1);
  assert.equal(h.fields.message.title,'No phone number available for this card');
  assert.equal(h.event(h.fields.message,'click').defaultPrevented,true);
}
assert.equal(h.saved.length,0);
''')


def test_confirmation_requires_author_and_pins_original_card_across_viewer_changes():
    _run(r'''
const h=setup(); h.runtime.configure('device'); h.runtime.update(item,true);
assert.equal(h.fields.author.required,true);
assert.equal(h.event(h.fields.message,'click').defaultPrevented,false);
assert.equal(h.fields.Title.textContent,'Text sent?');
assert.equal(h.fields.Confirm.textContent,'Text sent');
h.fields.author.value='   ';
h.event(h.fields.Form,'submit'); await turn();
assert.equal(h.saved.length,0); assert.equal(h.fields.author.focused,true);
assert.equal(h.fields.Message.textContent,'Enter your name.');
h.runtime.update(other,true);
h.fields.author.value='  Alex Reviewer  '; h.event(h.fields.author,'input');
const pending=JSON.parse([...storage.values()][0]);
assert.match(pending.noteId,/^[a-f0-9]{32}$/);
h.event(h.fields.Form,'submit'); await turn();
assert.deepEqual(h.saved,[{itemId:originalId,noteId:pending.noteId,author:'Alex Reviewer',body:'Text sent'}]);
assert.deepEqual(h.changed,[{id:originalId,result:{offline:false}}]);
assert.deepEqual(h.remembered,['Alex Reviewer']);
assert.equal(h.fields.Message.textContent,'Saved'); assert.equal(h.closed(),1); assert.equal(storage.size,0);
assert.equal(h.fields.dial.getAttribute('href'),'tel:3125550177');
''')


def test_pending_intent_and_typed_author_survive_reload_but_never_cross_identity():
    _run(r'''
const first=setup({getAuthor:()=>'Previous Author'});
first.runtime.configure('device-a'); first.runtime.update(item,true);
first.event(first.fields.dial,'click');
assert.equal(first.fields.author.value,'Previous Author');
first.fields.author.value='New Author'; first.event(first.fields.author,'input');
const noteId=first.runtime.pending.noteId;
const reloaded=setup(); reloaded.runtime.configure('device-b'); reloaded.runtime.update(other,true);
assert.equal(reloaded.runtime.restore(),false); assert.equal(reloaded.opened(),0);
reloaded.runtime.configure('device-a');
assert.equal(reloaded.runtime.restore(),true);
assert.equal(reloaded.fields.author.value,'New Author');
assert.equal(reloaded.fields.Context.textContent,'Original Customer · 2026-09-21 · (312) 555-0198');
assert.equal(reloaded.runtime.pending.noteId,noteId);
await reloaded.runtime.submit();
assert.deepEqual(reloaded.saved,[{itemId:originalId,noteId,author:'New Author',body:'Called'}]);
assert.equal(storage.size,0);
reloaded.runtime.configure('device-b');
assert.equal(reloaded.fields.Context.textContent,'');
assert.equal(reloaded.runtime.openPending(),false);
''')


def test_failed_confirmation_retries_same_id_and_double_submit_cannot_duplicate_note():
    _run(r'''
let rejectSave,resolveSave;
const saves=[];
const h=setup({saveNote:value=>{
  saves.push({...value});
  return new Promise((resolve,reject)=>{resolveSave=resolve;rejectSave=reject;});
}});
h.runtime.configure('device'); h.runtime.update(item,true); h.event(h.fields.dial,'click');
h.fields.author.value='Alex';
const first=h.runtime.submit();
await h.runtime.submit();
assert.equal(saves.length,1);
assert.equal(h.fields.Confirm.disabled,true); assert.equal(h.fields.Cancel.disabled,true);
assert.equal(h.runtime.cancel(),false,'An in-flight save cannot truthfully be canceled.');
rejectSave(new Error('Pi could not save this note.')); await first;
assert.equal(h.fields.Message.textContent,'Pi could not save this note.');
assert.equal(h.fields.Confirm.disabled,false); assert.equal(h.closed(),0);
assert.equal(storage.size,1); assert.ok(h.runtime.pending);
const retry=h.runtime.submit(); await h.runtime.submit();
assert.equal(saves.length,2); assert.deepEqual(saves[1],saves[0]);
resolveSave({offline:true}); await retry;
assert.equal(h.fields.Message.textContent,'Saved offline');
assert.equal(storage.size,0); assert.equal(h.closed(),1);
assert.deepEqual(h.changed,[{id:originalId,result:{offline:true}}]);
assert.equal(h.fields.dial.getAttribute('href'),'tel:+13125550198');
await h.runtime.submit(); assert.equal(saves.length,2);
''')


def test_completed_save_cannot_be_retried_when_refresh_fails_or_identity_changes():
    _run(r'''
const h=setup({onSaved:async()=>{throw new Error('Detail refresh unavailable');},
  rememberAuthor:()=>{throw new Error('Storage unavailable');}});
h.runtime.configure('device'); h.runtime.update(item,true); h.event(h.fields.dial,'click');
h.fields.author.value='Alex'; await h.runtime.submit();
assert.equal(h.fields.Message.textContent,'Saved'); assert.equal(h.closed(),1);
assert.equal(h.runtime.pending,null); assert.equal(storage.size,0);
await h.runtime.submit(); assert.equal(h.saved.length,1);
let resolve;
const switching=setup({saveNote:()=>new Promise(done=>{resolve=done;})});
switching.runtime.configure('first'); switching.runtime.update(item,true);
switching.event(switching.fields.message,'click'); switching.fields.author.value='Alex';
const saving=switching.runtime.submit();
switching.runtime.configure('second'); switching.runtime.update(other,true);
resolve({offline:false}); await saving;
assert.equal(switching.fields.Context.textContent,''); assert.equal(switching.changed.length,0);
assert.equal(switching.runtime.pending,null); assert.equal(switching.runtime.saving,false);
''')


def test_old_cached_shell_and_unavailable_session_storage_do_not_break_native_links():
    _run(r'''
globalThis.document={getElementById:()=>null,querySelector:()=>null};
const inert=new GalleryContact({openDialog:()=>assert.fail(),closeDialog:()=>assert.fail(),saveNote:()=>assert.fail()});
inert.configure('device'); inert.update(item,true);
assert.equal(inert.restore(),false); assert.equal(inert.openPending(),false); assert.equal(inert.cancel(),false);
globalThis.sessionStorage={getItem:()=>{throw new Error('blocked');},setItem:()=>{throw new Error('blocked');},
  removeItem:()=>{throw new Error('blocked');}};
const h=setup(); h.runtime.configure('device'); h.runtime.update(item,true);
assert.equal(h.event(h.fields.dial,'click').defaultPrevented,false);
h.fields.author.value='Alex'; await h.runtime.submit();
assert.equal(h.saved.length,1); assert.equal(h.closed(),1);
''')


def test_confirmation_stays_busy_until_saved_card_refresh_finishes():
    _run(r'''
let finishRefresh;
const h=setup({onSaved:()=>new Promise(resolve=>{finishRefresh=resolve;})});
h.runtime.configure('device'); h.runtime.update(item,true); h.event(h.fields.dial,'click');
h.fields.author.value='Alex'; const saving=h.runtime.submit(); await turn();
assert.equal(h.saved.length,1); assert.equal(storage.size,0);
assert.equal(h.closed(),0,'The parent refreshes the card before closing the confirmation history entry.');
assert.equal(h.fields.Confirm.disabled,true); assert.equal(h.fields.Cancel.disabled,true);
assert.equal(h.event(h.fields.message,'click').defaultPrevented,true);
await h.runtime.submit(); assert.equal(h.saved.length,1);
finishRefresh(); await saving;
assert.equal(h.closed(),1); assert.equal(h.fields.Confirm.disabled,false);
assert.equal(h.fields.dial.getAttribute('href'),'tel:+13125550198');
''')


def test_malformed_or_wrong_identity_pending_intents_never_restore():
    _run(r'''
const valid={subject:'device',itemId:originalId,noteId:'c'.repeat(32),phoneDial:'+13125550198',action:'dial'};
for (const invalid of [{...valid,subject:'other'},{...valid,itemId:'other'},
    {...valid,noteId:'550e8400-e29b-41d4-a716-446655440000'},
    {...valid,phoneDial:'123;body=bad'},{...valid,action:'anything'}]) {
  storage.set('stats.gallery.contact.device',JSON.stringify(invalid));
  const h=setup(); h.runtime.configure('device'); h.runtime.update(item,true);
  assert.equal(h.runtime.restore(),false); assert.equal(h.opened(),0); assert.equal(h.saved.length,0);
}
''')


def test_offline_contact_retry_preserves_original_note_without_duplicating_or_requeueing():
    _run(r'''
const offlineCode=readFileSync(process.argv[2].replace('gallery_contact.js','gallery_offline.js'),'utf8');
const {GalleryOffline}=await import('data:text/javascript;base64,'+Buffer.from(offlineCode).toString('base64'));
const clone=value=>value===undefined?undefined:structuredClone(value);
const storedCards=new Map([[originalId,{id:originalId,summary:{notes_count:0},detail:{notes:[]}}]]);
const outbox=new Map();
const writes=[];
const offline=new GalleryOffline({network:{isReachable:()=>false}});
offline.isEnabled=()=>true;
offline.open=async()=>{};
offline.db={transaction:(names,mode)=>{
  assert.deepEqual(names,['cards','pendingNotes']); assert.equal(mode,'readwrite');
  const tx={objectStore:name=>{
    const records=name==='cards'?storedCards:outbox;
    return {
      get:key=>{const request={}; queueMicrotask(()=>{request.result=clone(records.get(key));request.onsuccess();});return request;},
      put:value=>{writes.push(name);records.set(value.id,clone(value));},
    };
  }};
  setImmediate(()=>tx.oncomplete?.());
  return tx;
}};
const note={id:'c'.repeat(32),author:'Original Author',body:'Called',created:1234};
await offline.queueNote(originalId,note);
assert.deepEqual(storedCards.get(originalId).detail.notes,[note]);
assert.equal(storedCards.get(originalId).summary.notes_count,1);
assert.deepEqual(outbox.get(note.id),{...note,item_id:originalId});
const originalWrites=writes.length;
await offline.queueNote(originalId,{...note,author:'Changed Author',body:'Text sent',created:9999});
assert.equal(writes.length,originalWrites,'A retried pending intent leaves the original transaction untouched.');
assert.deepEqual(storedCards.get(originalId).detail.notes,[note]);
assert.equal(storedCards.get(originalId).summary.notes_count,1);
assert.deepEqual(outbox.get(note.id),{...note,item_id:originalId});

// A server-confirmed note has no outbox row. Restoring an older confirmation
// must not queue it again merely because its sessionStorage cleanup was lost.
outbox.delete(note.id);
await offline.queueNote(originalId,note);
assert.equal(outbox.size,0); assert.equal(writes.length,originalWrites);

// A detail refresh can arrive while a note remains queued. The outbox keeps
// the original payload even if a same-ID retry supplies different text.
outbox.set(note.id,{...note,item_id:originalId});
storedCards.set(originalId,{id:originalId,summary:{notes_count:0},detail:{notes:[]}});
await offline.queueNote(originalId,{...note,author:'Changed Author',body:'Text sent'});
assert.deepEqual(storedCards.get(originalId).detail.notes,[note]);
assert.equal(storedCards.get(originalId).summary.notes_count,1);
assert.deepEqual(outbox.get(note.id),{...note,item_id:originalId});
assert.equal(outbox.size,1);
''')


def test_saved_note_author_is_scoped_to_identity_and_tolerates_unavailable_storage():
    _run(r'''
const offlineCode=readFileSync(process.argv[2].replace('gallery_contact.js','gallery_offline.js'),'utf8');
const {GalleryOffline}=await import('data:text/javascript;base64,'+Buffer.from(offlineCode).toString('base64'));
const preferences=new Map();
globalThis.localStorage={
  getItem:key=>preferences.get(key) ?? null,
  setItem:(key,value)=>preferences.set(key,String(value)),
};
const offline=new GalleryOffline({network:{json:()=>assert.fail('Author preferences are local.')}});
assert.equal(offline.savedNoteAuthor(),'');
offline.rememberNoteAuthor('No identity');
assert.equal(preferences.size,0,'An absent identity cannot create a shared author preference.');
offline.subject='full-a'; offline.rememberNoteAuthor('First Reviewer');
assert.equal(offline.savedNoteAuthor(),'First Reviewer');
offline.subject='full-b'; assert.equal(offline.savedNoteAuthor(),'');
offline.rememberNoteAuthor('Second Reviewer');
assert.equal(offline.savedNoteAuthor('full-a'),'First Reviewer');
assert.equal(offline.savedNoteAuthor(),'Second Reviewer');
offline.rememberNoteAuthor('Guest Reviewer','guest-session');
assert.equal(offline.savedNoteAuthor('guest-session'),'Guest Reviewer');
assert.equal(offline.savedNoteAuthor(),'Second Reviewer','Explicit guest identity does not change full-device identity.');
offline.rememberNoteAuthor('No identity','');
assert.equal(offline.savedNoteAuthor(''),'');
assert.equal(preferences.size,3);
offline.rememberNoteAuthor('');
assert.equal(offline.savedNoteAuthor(),'');
assert.equal(offline.savedNoteAuthor('full-a'),'First Reviewer');
globalThis.localStorage={getItem:()=>{throw new Error('blocked');},setItem:()=>{throw new Error('blocked');}};
assert.equal(offline.savedNoteAuthor(),'');
offline.rememberNoteAuthor('Ignored while storage is blocked');
delete globalThis.localStorage;
assert.equal(offline.savedNoteAuthor(),'');
offline.rememberNoteAuthor('Ignored without storage');
''')
