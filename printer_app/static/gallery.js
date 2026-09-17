import { GalleryDates } from './gallery_dates.js';

'use strict';
(() => {
  const el = id => document.getElementById(id);
  const cards = new Map(), groups = new Map(), drafts = new Map(), saving = new Set();
  let query = '', relatedId = null, selected = null, offset = 0, total = 0, dateFilter = '';
  let generation = 0, detailGeneration = 0, loading = false, galleryDirty = false, relatedAfterSave = false, notesVersion = '', pendingDetails = 0;
  const dates = new GalleryDates({
    onSelect: chooseDate,
    blocked: () => loading || Boolean(document.querySelector('dialog[open]')),
  });
  const randomId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
  const mb = bytes => (bytes / 1048576).toFixed(1) + ' MB';
  const text = (tag, value, className = '') => { const n = document.createElement(tag); n.textContent = value; n.className = className; return n; };
  const dateLabel = value => value ? new Date(value + 'T12:00:00').toLocaleDateString('en-US', {month:'long', day:'numeric', year:'numeric'}) : 'Date needs checking';
  const cardName = item => item.lead_name || 'Work order';
  async function api(url, options) {
    const response = await fetch(url, {cache:'no-store', credentials:'same-origin', ...options});
    const data = await response.json().catch(() => ({error:'Request failed. Reopen the gallery and try again.'}));
    if (!response.ok) { const error = new Error(data.error || 'Request failed'); error.status = response.status; throw error; }
    return data;
  }
  function actions() {
    document.querySelectorAll('[data-action]').forEach(button => {
      button.disabled = button.dataset.action !== 'search' && !selected;
    });
    cards.forEach(({node, item}) => node.setAttribute('aria-pressed', String(item.id === selected?.id)));
  }
  function updateCard(item) {
    const card = cards.get(item.id);
    if (!card) return;
    Object.assign(card.item, item);
    card.name.textContent = cardName(item);
    const count = item.notes ? item.notes.length : item.notes_count;
    if (count !== undefined) card.badge.textContent = `${count} ${count === 1 ? 'note' : 'notes'}`;
  }
  function addCard(item) {
    if (cards.has(item.id)) return;
    const key = item.document_date || 'undated';
    if (!groups.has(key)) {
      const section = text('section', '', 'gallery-day'); section.dataset.date = key;
      const heading = text('div', '', 'gallery-day-heading');
      const label = item.document_date ? new Date(item.document_date + 'T12:00:00').toLocaleDateString('en-US', {weekday:'long'}) : 'Confirm in notes';
      const title = text('h2', '');
      const dateButton = text('button', dateLabel(item.document_date) + ' ⌄', 'gallery-date-trigger');
      dateButton.type = 'button'; dateButton.setAttribute('aria-haspopup', 'dialog');
      dateButton.setAttribute('aria-controls', 'galleryDateSheet');
      dateButton.addEventListener('click', () => dates.open(key));
      title.append(dateButton); heading.append(title, text('span', label));
      const list = text('div', '', 'gallery-day-cards'); section.append(heading, list);
      groups.set(key, list); el('galleryCards').append(section);
    }
    const node = text('button', '', 'gallery-card'); node.type = 'button'; node.dataset.id = item.id;
    const image = document.createElement('img'); image.loading = 'lazy'; image.decoding = 'async';
    // Always use the full stored image. Never crop/cover it or request thumbnails.
    image.src = '/gallery/image/' + item.id;
    image.alt = `${cardName(item)} — complete work order, ${dateLabel(item.document_date)}`;
    const meta = text('span', '', 'gallery-card-meta');
    const caption = text('span', ''); const name = text('span', cardName(item), 'gallery-card-name');
    caption.append(name, text('span', `Page ${item.page} · work order ${item.part}`, 'gallery-card-subtitle'));
    const badge = text('span', `${item.notes_count} ${item.notes_count === 1 ? 'note' : 'notes'}`, 'gallery-card-badge');
    meta.append(caption, badge); node.append(image, meta);
    node.addEventListener('click', () => openViewer(cards.get(item.id).item));
    cards.set(item.id, {node, item, name, badge}); groups.get(key).append(node);
  }
  async function load(reset = true) {
    if (!reset && loading) return;
    if (reset) { generation++; offset = 0; cards.clear(); groups.clear(); el('galleryCards').replaceChildren(); }
    el('galleryDateMessage').textContent = '';
    const token = generation, start = offset, related = relatedId;
    loading = true; dates.busy(true); el('galleryCards').setAttribute('aria-busy', 'true'); el('galleryMore').disabled = true; el('galleryMessage').textContent = reset ? 'Loading cards…' : '';
    const suffix = `&date=${encodeURIComponent(dateFilter)}`;
    const url = (related ? `/gallery/api/items/${related}/related?offset=${start}` : `/gallery/api/items?q=${encodeURIComponent(query)}&offset=${start}`) + suffix;
    try {
      const data = await api(url);
      if (token !== generation) return;
      dates.update(data.dates, dateFilter);
      data.items.forEach(addCard); total = data.total; offset = start + data.items.length;
      el('galleryHeading').textContent = related ? 'Related cards' : query ? 'Search results' : 'Gallery';
      el('galleryCount').textContent = `${total} ${total === 1 ? 'work order' : 'work orders'} · ${dateFilter ? (dateFilter === 'undated' ? 'dates need checking' : dateLabel(dateFilter)) : 'newest dates first'}`;
      el('galleryFilter').hidden = !related && !query;
      el('galleryFilterTitle').textContent = related ? data.lead_name : query;
      el('galleryFilterHint').textContent = related ? 'Same lead name · across all retained dates' : 'Matching printed text and shared notes';
      el('galleryMore').hidden = offset >= total;
      el('galleryEmpty').hidden = total !== 0;
      el('galleryEmpty').textContent = dateFilter ? 'No work orders on this date. Choose another date or All dates.' : query || related ? 'No matching work orders.' : 'No work orders yet. Enable gallery email imports in Settings.';
      el('galleryMessage').textContent = ''; actions();
    } catch (error) { if (token === generation) el('galleryMessage').textContent = error.message; }
    finally { if (token === generation) { loading = false; dates.busy(false); el('galleryCards').setAttribute('aria-busy', 'false'); el('galleryMore').disabled = false; } }
  }
  function chooseDate(value) {
    // This is a read-only view filter, never a correction of a document's date.
    dateFilter = value; selected = null; detailGeneration++; galleryDirty = false;
    dates.setFilter(value); closeDialogs(); actions(); load(); window.scrollTo({top:0});
  }
  async function summary() {
    try {
      const s = await api('/gallery/api/summary');
      const alive = s.heartbeat && Date.now()/1000 - s.heartbeat < 40;
      el('galleryStatus').textContent = `${s.count} images · ${s.waiting} imports waiting · ${s.undated || 0} dates need checking. ` +
        (s.error || (alive ? 'Gallery worker ready.' : 'Gallery worker has not checked in. Printing is separate.'));
      el('galleryStorage').textContent = `Storage: ${mb(s.storage.total)}. Free disk: ${mb(s.storage.free)}. Budget: ${mb(s.limit_bytes)}. ` +
        (s.count ? `Average image: ${mb(s.average_bytes)}. Estimated ${s.keep_days}-day images: ${mb(s.projected_image_bytes)} (${s.estimated_daily} per day, ${s.estimate_source}). Database/notes and temporary files are additional.` : 'Import a PDF to measure image sizes.');
      el('galleryImports').replaceChildren(...s.recent.map(r => text('p', `${r.filename}: ${r.state} · ${r.count} images${r.error ? ' — ' + r.error : ''}`)));
    } catch (error) { el('galleryStatus').textContent = error.message; }
  }
  function draft() {
    const form = el('galleryNote'), id = form.dataset.itemId;
    if (!id) return;
    const old = drafts.get(id);
    const value = {author:form.elements.author.value, body:form.elements.body.value, noteId:old?.noteId || randomId()};
    if (old && (old.author !== value.author || old.body !== value.body)) value.noteId = randomId();
    drafts.set(id, value);
  }
  function noteControls() {
    const busy = !selected || saving.has(selected.id);
    ['author', 'body'].forEach(name => { el('galleryNote').elements[name].disabled = busy; });
    el('galleryNote').querySelector('button').disabled = busy;
  }
  function renderDetail(item, initial) {
    el('galleryTitle').textContent = cardName(item);
    el('galleryViewerDate').textContent = dateLabel(item.document_date);
    el('gallerySource').textContent = `${item.filename} · page ${item.page}, work order ${item.part}`;
    el('galleryNotesContext').textContent = `${cardName(item)} · ${dateLabel(item.document_date)}`;
    const notes = item.notes.map(note => {
      const article = text('article', ''); const at = new Date(note.created * 1000);
      const stamp = text('time', at.toLocaleString()); stamp.dateTime = at.toISOString();
      article.append(text('strong', note.author), stamp, text('p', note.body)); return article;
    });
    const version = item.id + ':' + item.notes.map(n => n.id).join(',');
    if (initial || notesVersion !== version) {
      el('galleryNotes').replaceChildren(...(notes.length ? notes : [text('p', 'No notes yet. Add the first note below.', 'muted')]));
      notesVersion = version;
    }
    el('galleryText').textContent = item.text || 'No readable text. Typed notes are searchable.';
    el('galleryDateStatus').textContent = item.document_date ? `Document date: ${item.document_date} (${item.date_status}).` : 'Uncertain date — protected from expiry until confirmed.';
    if (initial) {
      el('galleryLead').elements.lead_name.value = item.lead_name || '';
      el('galleryDate').elements.date.value = item.document_date || '';
    }
    updateCard(item);
  }
  async function detail(initial = false) {
    if (!selected) return;
    const id = selected.id, token = ++detailGeneration;
    pendingDetails++;
    try {
      const item = await api('/gallery/api/items/' + id);
      if (selected?.id !== id || token !== detailGeneration) return;
      selected = item; renderDetail(item, initial); actions();
    } catch (error) {
      if (selected?.id !== id || token !== detailGeneration) return;
      el('galleryViewerMessage').textContent = error.message;
      el('galleryNoteMessage').textContent = 'Updates unavailable: ' + error.message;
      if (error.status === 404) { selected = null; actions(); noteControls(); }
      throw error;
    } finally { pendingDetails--; }
  }
  function openViewer(item) {
    selected = item; actions(); el('galleryViewerMessage').textContent = '';
    el('galleryTitle').textContent = cardName(item); el('galleryViewerDate').textContent = dateLabel(item.document_date);
    el('gallerySource').textContent = `${item.filename} · page ${item.page}, work order ${item.part}`;
    el('galleryFull').src = '/gallery/image/' + item.id;
    el('galleryViewer').showModal(); el('galleryViewer').scrollTop = 0;
    detail().catch(() => {});
  }
  async function openNotes(editLead = false) {
    if (!selected) return;
    const saved = drafts.get(selected.id) || {author:'', body:'', noteId:randomId()};
    drafts.set(selected.id, saved);
    el('galleryNote').dataset.itemId = selected.id;
    el('galleryNote').elements.author.value = saved.author; el('galleryNote').elements.body.value = saved.body;
    el('galleryNoteMessage').textContent = ''; el('galleryNotes').replaceChildren(text('p', 'Loading notes…', 'muted'));
    el('galleryNotesContext').textContent = `${cardName(selected)} · ${dateLabel(selected.document_date)}`;
    el('galleryCardDetails').open = editLead; relatedAfterSave = editLead;
    noteControls(); el('galleryNotesSheet').showModal();
    try {
      await detail(true);
      if (editLead && selected) {
        el('galleryNoteMessage').textContent = 'Confirm the lead name below to show related work orders.';
        el('galleryLead').elements.lead_name.focus();
      }
    } catch (_) { /* The sheet keeps the error visible. */ }
  }
  function closeDialogs() { document.querySelectorAll('dialog[open]').forEach(d => d.close()); }
  async function related() {
    if (!selected) return;
    try {
      await detail();
      if (!selected) return;
      if (!selected.lead_name) { openNotes(true); return; }
      relatedId = selected.id; query = ''; dateFilter = ''; dates.setFilter(''); closeDialogs();
      await load(); window.scrollTo({top:0});
    } catch (error) { el('galleryMessage').textContent = error.message; }
  }
  function openSearch() {
    el('query').value = query; el('gallerySearchSheet').showModal(); el('query').focus();
  }
  document.querySelectorAll('[data-action]').forEach(button => {
    button.addEventListener('click', () => ({related, notes:openNotes, search:openSearch})[button.dataset.action]());
  });
  document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => el(button.dataset.close).close()));
  document.querySelectorAll('dialog').forEach(dialog => {
    dialog.addEventListener('click', event => { if (event.target === dialog) {
      const box = dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
    }});
    dialog.addEventListener('close', () => {
      if (galleryDirty && !document.querySelector('dialog[open]')) { galleryDirty = false; load(); }
    });
  });
  el('galleryNotesSheet').addEventListener('close', () => { draft(); relatedAfterSave = false; });
  el('galleryViewer').addEventListener('close', () => { el('galleryFull').removeAttribute('src'); });
  el('galleryInfo').onclick = () => { el('galleryInfoSheet').showModal(); summary(); };
  el('galleryViewerDate').onclick = () => dates.open(selected?.document_date || 'undated');
  el('galleryMore').onclick = () => load(false);
  el('galleryClear').onclick = () => { relatedId = null; query = ''; chooseDate(''); };
  el('galleryRefresh').onclick = () => { el('galleryInfoSheet').close(); load(); summary(); };
  el('gallerySearch').onsubmit = event => {
    event.preventDefault(); query = el('query').value.trim(); relatedId = null; selected = null; dateFilter = ''; dates.setFilter('');
    closeDialogs(); actions(); load(); window.scrollTo({top:0});
  };
  el('galleryNote').addEventListener('input', draft);
  el('galleryNote').onsubmit = async event => {
    event.preventDefault(); if (!selected || saving.has(selected.id)) return;
    draft(); const form = event.currentTarget, id = selected.id;
    const data = new FormData(form); data.set('note_id', drafts.get(id).noteId);
    saving.add(id); noteControls(); el('galleryNoteMessage').textContent = 'Saving…';
    try {
      await api(`/gallery/api/items/${id}/notes`, {method:'POST', body:data});
      drafts.set(id, {author:data.get('author'), body:'', noteId:randomId()});
      if (selected?.id === id) {
        form.elements.body.value = ''; el('galleryNoteMessage').textContent = 'Saved. Other open devices update within five seconds.';
        await detail().catch(() => { el('galleryNoteMessage').textContent = 'Saved. Reopen notes to refresh the list.'; });
      }
    } catch (error) { if (selected?.id === id) el('galleryNoteMessage').textContent = 'Not saved: ' + error.message; }
    finally { saving.delete(id); noteControls(); }
  };
  el('galleryLead').onsubmit = async event => {
    event.preventDefault(); if (!selected) return;
    const id = selected.id, goRelated = relatedAfterSave, button = event.currentTarget.querySelector('button'); button.disabled = true;
    try {
      await api(`/gallery/api/items/${id}/lead-name`, {method:'POST', body:new FormData(event.currentTarget)});
      if (selected?.id !== id) return;
      el('galleryNoteMessage').textContent = 'Lead name saved.'; await detail().catch(() => { el('galleryNoteMessage').textContent = 'Lead name saved. Reopen to refresh.'; });
      if (goRelated) related();
    } catch (error) { el('galleryNoteMessage').textContent = 'Not saved: ' + error.message; }
    finally { button.disabled = false; }
  };
  el('galleryDate').onsubmit = async event => {
    event.preventDefault(); if (!selected) return;
    const id = selected.id, button = event.currentTarget.querySelector('button'); button.disabled = true;
    try {
      await api(`/gallery/api/items/${id}/date`, {method:'POST', body:new FormData(event.currentTarget)});
      if (selected?.id !== id) return;
      galleryDirty = true; el('galleryNoteMessage').textContent = 'Date saved.'; await detail().catch(() => { el('galleryNoteMessage').textContent = 'Date saved. Reopen to refresh.'; });
    } catch (error) { el('galleryNoteMessage').textContent = 'Not saved: ' + error.message; }
    finally { button.disabled = false; }
  };
  setInterval(() => { if (selected && !pendingDetails && !document.hidden && (el('galleryViewer').open || el('galleryNotesSheet').open)) detail().catch(() => {}); }, 5000);
  setInterval(() => { if (!document.hidden && el('galleryInfoSheet').open) summary(); }, 15000);
  actions(); load();
})();
