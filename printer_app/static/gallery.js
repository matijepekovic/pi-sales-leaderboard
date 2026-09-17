'use strict';
(() => {
  const el = id => document.getElementById(id);
  let offset = 0, query = '', selected = null, requestNumber = 0, noteId = '';
  const randomId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
  const mb = bytes => (bytes / 1048576).toFixed(1) + ' MB';
  async function api(url, options) {
    const r = await fetch(url, {cache: 'no-store', credentials: 'same-origin', ...options});
    const data = await r.json().catch(() => ({error: 'Request failed. Reopen the gallery and try again.'}));
    if (!r.ok) throw new Error(data.error || 'Request failed');
    return data;
  }
  function text(tag, value) { const node = document.createElement(tag); node.textContent = value; return node; }
  async function search() {
    const request = ++requestNumber;
    try {
      const data = await api('/gallery/api/items?q=' + encodeURIComponent(query) + '&offset=' + offset);
      if (request !== requestNumber) return;
      el('galleryCards').replaceChildren();
      for (const item of data.items) {
        const card = document.createElement('button'); card.className = 'gallery-card'; card.type = 'button';
        const image = document.createElement('img'); image.loading = 'lazy'; image.decoding = 'async';
        image.src = '/gallery/image/' + item.id; image.alt = 'Work-order crop, page ' + item.page + ', box ' + item.part;
        card.append(image, text('p', (item.document_date || 'Date needs checking') + ' · ' + item.notes_count + ' notes'),
          text('p', item.filename + ' · page ' + item.page + ', box ' + item.part));
        card.addEventListener('click', () => open(item.id)); el('galleryCards').append(card);
      }
      el('galleryCount').textContent = data.total ? `${offset + 1}–${Math.min(offset + 24, data.total)} of ${data.total}` : 'No matching images';
      el('galleryPrevious').disabled = offset === 0; el('galleryNext').disabled = offset + 24 >= data.total;
    } catch (e) { el('galleryStatus').textContent = e.message; }
  }
  async function summary() {
    try {
      const s = await api('/gallery/api/summary');
      const alive = s.heartbeat && Date.now()/1000 - s.heartbeat < 40;
      el('galleryStatus').textContent = `${s.count} images · ${s.waiting} imports waiting · ${s.undated || 0} dates need checking. ` +
        (s.error || (alive ? (s.processing ? 'Processing PDF in the background.' : 'Gallery worker ready.') : 'Gallery worker has not checked in. Printing is separate.'));
      el('galleryStorage').textContent = `Actual gallery storage: ${mb(s.storage.total)} (images ${mb(s.storage.crops)}, database ${mb(s.storage.database)}, temporary imports ${mb(s.storage.spool + s.storage.work)}). Free disk: ${mb(s.storage.free)}. Budget: ${mb(s.limit_bytes)}. ` +
        (s.count ? `Average crop: ${mb(s.average_bytes)}. Estimated ${s.keep_days}-day images: ${mb(s.projected_image_bytes)}, using ${s.estimated_daily} crops/day (${s.estimate_source}); database/notes and temporary workspace are additional. Unknown-date images can exceed this estimate.` : 'Import a PDF to measure crop sizes and estimate retention storage.');
      el('galleryImports').replaceChildren(...s.recent.map(r => text('p', `${r.filename}: ${r.state} · ${r.count} crops${r.error ? ' — ' + r.error : ''}`)));
    } catch (e) { el('galleryStatus').textContent = e.message; }
  }
  async function detail(initial = false) {
    const id = selected;
    if (!id) return;
    const item = await api('/gallery/api/items/' + id);
    if (id !== selected) return;
    el('galleryTitle').textContent = `${item.filename} · page ${item.page}, box ${item.part}`;
    el('galleryDateStatus').textContent = item.document_date ? `Document date: ${item.document_date} (${item.date_status}).` : 'Printed date uncertain — this image will not expire until a date is confirmed.';
    el('galleryText').textContent = item.text || 'No readable text extracted. Typed notes are searchable.';
    el('galleryNotes').replaceChildren(...item.notes.map(n => {
      const a = text('article', '');
      a.append(text('strong', n.author + ' · ' + new Date(n.created * 1000).toLocaleString()), text('p', n.body)); return a;
    }));
    if (initial) el('galleryDate').elements.date.value = item.document_date || '';
  }
  async function open(id) {
    selected = id; noteId = randomId(); el('galleryNote').elements.body.value = '';
    el('galleryMessage').textContent = ''; el('galleryFull').src = '/gallery/image/' + id;
    el('galleryDialog').showModal();
    try { await detail(true); } catch (e) { el('galleryMessage').textContent = e.message; }
  }
  el('galleryClose').onclick = () => el('galleryDialog').close();
  el('galleryDialog').addEventListener('close', () => { selected = null; el('galleryFull').removeAttribute('src'); search(); });
  el('gallerySearch').onsubmit = e => { e.preventDefault(); query = el('query').value; offset = 0; search(); };
  el('galleryPrevious').onclick = () => { offset = Math.max(0, offset - 24); search(); };
  el('galleryNext').onclick = () => { offset += 24; search(); };
  el('galleryNote').onsubmit = async e => {
    e.preventDefault(); const form = e.currentTarget, id = selected, button = form.querySelector('button');
    button.disabled = true; el('galleryMessage').textContent = 'Saving…';
    try {
      const data = new FormData(form); data.set('note_id', noteId);
      await api('/gallery/api/items/' + id + '/notes', {method: 'POST', body: data});
      if (id === selected) { form.elements.body.value = ''; noteId = randomId(); el('galleryMessage').textContent = 'Saved. Other open devices update within five seconds.'; await detail(); }
    } catch (e) { el('galleryMessage').textContent = 'Not saved: ' + e.message; }
    finally { button.disabled = false; }
  };
  el('galleryDate').onsubmit = async e => {
    e.preventDefault();
    try { await api('/gallery/api/items/' + selected + '/date', {method:'POST', body:new FormData(e.currentTarget)}); el('galleryMessage').textContent = 'Date saved.'; await detail(); }
    catch (e) { el('galleryMessage').textContent = 'Not saved: ' + e.message; }
  };
  setInterval(() => { if (selected && !document.hidden) detail().catch(e => { el('galleryMessage').textContent = 'Updates unavailable: ' + e.message; }); }, 5000);
  setInterval(() => { if (!document.hidden) summary(); }, 15000);
  search(); summary();
})();
