import { GalleryDates } from './gallery_dates.js';
import { GalleryFocus } from './gallery_focus.js';
import { GalleryNavigation } from './gallery_navigation.js';
import { GalleryOffline } from './gallery_offline.js';

'use strict';
(() => {
  const el = id => document.getElementById(id);
  const initialView = history.state?.gallery?.view;
  let chooseLatest = !initialView;
  const nextFrame = () => new Promise(resolve => requestAnimationFrame(resolve));
  const cards = new Map(), groups = new Map(), drafts = new Map(), saving = new Set();
  let query = '', relatedId = null, selected = null, offset = 0, total = 0, dateFilter = '';
  let generation = 0, detailGeneration = 0, loading = false, galleryDirty = false, actionPending = false, notesVersion = '', pendingDetails = 0;
  let access = null, offlineMode = false;
  let preparedShare = null, sharePreparing = null;
  const offline = new GalleryOffline({
    onStatus: message => { el('galleryOfflineStatus').textContent = message; },
  });
  const dates = new GalleryDates({
    onSelect: chooseDate,
    openDialog: id => {
      showDialog(id);
      if (id === 'galleryDateSheet') prepareShare().catch(error => {
        el('galleryOfflineStatus').textContent = 'Could not prepare sharing: ' + error.message;
      });
    },
    blocked: () => loading || navigation.restoring || Boolean(document.querySelector('dialog[open]')),
  });
  const focus = new GalleryFocus({
    container: el('galleryCards'),
    blocked: () => loading || actionPending || navigation.restoring || Boolean(document.querySelector('dialog[open]')),
    onChange: id => {
      selected = cards.get(id)?.item || null;
      detailGeneration++;
      actions();
    },
  });
  const navigation = new GalleryNavigation({
    capture: captureView, restore: restoreView,
    changed: () => { updateNavigation(); focus.reset(); },
  });
  function updateNavigation() {
    const context = Boolean(relatedId || query);
    document.querySelector('.gallery-date-nav').dataset.context = String(context);
    el('galleryMain').dataset.singleDate = String(Boolean(dateFilter));
    el('galleryBack').hidden = !context || navigation.depth === 0;
  }
  function captureView() {
    const navBottom = document.querySelector('.gallery-date-nav').getBoundingClientRect().bottom;
    const anchor = [...el('galleryCards').querySelectorAll('.gallery-card')]
      .find(node => node.getBoundingClientRect().bottom > navBottom);
    return {query, relatedId, dateFilter, count:cards.size, scroll:window.scrollY,
      anchor:anchor?.dataset.id, anchorTop:anchor?.getBoundingClientRect().top,
      selected:selected?.id, viewerScroll:el('galleryViewer').scrollTop,
      dialogs:[...document.querySelectorAll('dialog[open]')].map(node => node.id),
      searchDraft:el('query').value};
  }
  function showDialog(id, record = true) {
    if (record) navigation.save();
    el(id).showModal();
    if (record) navigation.push();
  }
  function requestClose(id) {
    if (navigation.depth > 0) navigation.back();
    else el(id).close();
  }
  async function restoreView(view) {
    if (!view) return;
    chooseLatest = false;
    const reload = galleryDirty || query !== view.query || relatedId !== view.relatedId ||
      dateFilter !== view.dateFilter || !cards.size;
    galleryDirty = false; detailGeneration++;
    closeDialogs();
    // Native close events must finish saving the old draft before opening a new sheet.
    await nextFrame();
    query = view.query || ''; relatedId = view.relatedId || null; dateFilter = view.dateFilter || '';
    dates.setFilter(dateFilter);
    if (reload) await load();
    while (cards.size < (view.count || 0) && offset < total) {
      const before = offset; await load(false); if (offset === before) break;
    }
    updateNavigation();
    const nodes = [...el('galleryCards').querySelectorAll('.gallery-card')];
    const anchorIndex = nodes.findIndex(node => node.dataset.id === view.anchor);
    await Promise.all(nodes.slice(0, Math.max(1,anchorIndex+1)).map(node => {
      const image = node.querySelector('img'); image.loading = 'eager';
      return image.decode().catch(() => {});
    }));
    await nextFrame();
    const anchor = cards.get(view.anchor)?.node;
    window.scrollTo(0, anchor ? window.scrollY + anchor.getBoundingClientRect().top - view.anchorTop : view.scroll || 0);
    selected = cards.get(view.selected)?.item || null;
    const dialogs = view.dialogs || [];
    if (view.selected && !selected && dialogs.length) {
      try { selected = await api('/gallery/api/items/' + view.selected); }
      catch (_) {
        selected = await offline.detail(view.selected);
        if (!selected) el('galleryMessage').textContent = 'That work order is no longer available.';
      }
    }
    for (const id of dialogs) {
      if (id === 'galleryViewer' && selected) {
        const details = openViewer(selected, false);
        await Promise.all([el('galleryFull').decode().catch(() => {}), details]);
        // Detail rendering and native history settling can both happen after showModal.
        // Reapply the nested viewer position after those layout changes so Back returns
        // to the exact place inside the work order instead of snapping to the top.
        await nextFrame();
        el(id).scrollTop = view.viewerScroll || 0;
        await nextFrame();
        el(id).scrollTop = view.viewerScroll || 0;
      }
      else if (id === 'galleryNotesSheet' && selected) await openNotes(false);
      else if (id === 'galleryDateSheet') dates.open();
      else if (id === 'gallerySearchSheet') { el('query').value = view.searchDraft || ''; showDialog(id, false); }
      else if (id === 'galleryInfoSheet') { showDialog(id, false); summary(); }
    }
    actions();
  }
  function currentCard() {
    // Resolve the dominant visible card, including documents taller than the screen.
    // While a dialog is open, its existing target stays pinned instead.
    if (!navigation.restoring && !document.querySelector('dialog[open]')) focus.refresh();
    return selected;
  }
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
  function fallbackCopy(value) {
    const field = document.createElement('textarea');
    field.value = value;
    field.setAttribute('readonly', '');
    field.style.position = 'fixed';
    field.style.opacity = '0';
    field.style.pointerEvents = 'none';
    document.body.append(field);
    field.select();
    field.setSelectionRange(0, field.value.length);
    let copied = false;
    try { copied = document.execCommand('copy'); } catch (_) { copied = false; }
    field.remove();
    return copied;
  }
  function copyShareLink(value) {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      return navigator.clipboard.writeText(value).then(() => true).catch(() => fallbackCopy(value));
    }
    return Promise.resolve(fallbackCopy(value));
  }
  function shareCapability() {
    return Boolean(access?.capabilities?.includes('share'));
  }
  async function prepareShare(force = false) {
    const button = el('galleryShare');
    if (!shareCapability()) {
      preparedShare = null;
      button.disabled = false;
      return null;
    }
    const fresh = preparedShare && preparedShare.expiresAt - Date.now() > 5 * 60 * 1000;
    if (!force && fresh) return preparedShare;
    if (sharePreparing) return sharePreparing;
    button.disabled = true;
    sharePreparing = (async () => {
      const form = new FormData();
      form.set('csrf', el('galleryNote').elements.csrf.value);
      const shared = await api('/gallery/api/share', {method:'POST', body:form});
      preparedShare = {
        url: shared.url,
        expiresAt: Date.now() + Math.max(60, Number(shared.expires_in) || 86400) * 1000,
      };
      return preparedShare;
    })();
    try {
      return await sharePreparing;
    } finally {
      sharePreparing = null;
      button.disabled = false;
    }
  }
  function accessControls(info, resumed = false) {
    const canOffline = resumed || Boolean(info?.capabilities?.includes('offline'));
    const canShare = !resumed && Boolean(info?.capabilities?.includes('share'));
    el('galleryOfflineWrap').hidden = !canOffline;
    el('galleryShare').hidden = !canShare;
    if (!canShare) {
      preparedShare = null;
      sharePreparing = null;
      el('galleryShare').disabled = false;
    }
    el('galleryOfflineToggle').checked = canOffline && offline.isEnabled();
    if (!canOffline) el('galleryOfflineStatus').textContent = '';
    if (info?.csrf) {
      const csrf = el('galleryNote').elements.csrf;
      if (csrf) csrf.value = info.csrf;
    }
  }
  async function configureAccess() {
    try {
      access = await api('/gallery/api/access');
      await offline.configure(access);
      offlineMode = false;
      accessControls(access);
      if (offline.isEnabled()) offline.sync().catch(error => {
        el('galleryOfflineStatus').textContent = 'Offline update paused: ' + error.message;
      });
      return true;
    } catch (error) {
      if (!error.status && await offline.resume()) {
        access = null;
        offlineMode = true;
        accessControls(null, true);
        el('galleryOfflineStatus').textContent = 'Offline · showing cards stored on this phone';
        return false;
      }
      throw error;
    }
  }
  function actions() {
    document.querySelectorAll('[data-action]').forEach(button => {
      button.disabled = button.dataset.action !== 'search' && (!selected || actionPending);
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
    image.src = item._offline_image_url || '/gallery/image/' + item.id;
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
    if (reset) { generation++; offset = 0; cards.clear(); groups.clear(); selected = null; detailGeneration++; el('galleryCards').replaceChildren(); focus.reset(); actions(); }
    el('galleryDateMessage').textContent = '';
    const token = generation, start = offset, related = relatedId;
    loading = true; dates.busy(true); el('galleryCards').setAttribute('aria-busy', 'true'); el('galleryMore').disabled = true; el('galleryMessage').textContent = reset ? 'Loading cards…' : '';
    const suffix = `&date=${encodeURIComponent(dateFilter)}`;
    const url = (related ? `/gallery/api/items/${related}/related?offset=${start}` : `/gallery/api/items?q=${encodeURIComponent(query)}&offset=${start}`) + suffix;
    try {
      let data;
      try {
        data = await api(url);
        offlineMode = false;
      } catch (networkError) {
        data = await offline.list({q:query, relatedId:related, date:dateFilter, offset:start});
        if (!data) throw networkError;
        offlineMode = true;
        el('galleryOfflineStatus').textContent = 'Offline · showing cards stored on this phone';
      }
      if (token !== generation) return;
      if (chooseLatest) {
        chooseLatest = false;
        const latest = (data.dates || []).find(bucket => bucket.date)?.date;
        if (latest && !query && !relatedId) {
          dateFilter = latest; dates.setFilter(latest); loading = false;
          return await load();
        }
      }
      dates.update(data.dates, dateFilter);
      data.items.forEach(addCard); total = data.total; offset = start + data.items.length;
      el('galleryHeading').textContent = related ? 'Related cards' : query ? 'Search results' : 'Gallery';
      el('galleryCount').textContent = `${total} ${total === 1 ? 'work order' : 'work orders'} · ${dateFilter ? (dateFilter === 'undated' ? 'dates need checking' : dateLabel(dateFilter)) : 'newest dates first'}`;
      el('galleryFilter').hidden = !related && !query;
      el('galleryFilterTitle').textContent = related ? data.lead_name : query;
      el('galleryFilterHint').textContent = related ? 'Lead name in printed text or notes · all retained dates' : 'Matching printed text and shared notes';
      el('galleryMore').hidden = offset >= total;
      el('galleryEmpty').hidden = total !== 0;
      el('galleryEmpty').textContent = dateFilter ? 'No work orders on this date. Choose another date.' : query || related ? 'No matching work orders.' : 'No work orders yet.';
      el('galleryMessage').textContent = ''; updateNavigation(); actions();
    } catch (error) { if (token === generation) el('galleryMessage').textContent = error.message; }
    finally { if (token === generation) { loading = false; dates.busy(false); el('galleryCards').setAttribute('aria-busy', 'false'); el('galleryMore').disabled = false; focus.reset(); } }
  }
  async function chooseDate(value) {
    if (navigation.restoring) return;
    const fromSheet = el('galleryDateSheet').open;
    navigation.save(); chooseLatest = false;
    dateFilter = value; selected = null; detailGeneration++; galleryDirty = false;
    dates.setFilter(value); closeDialogs(); actions();
    await load(); window.scrollTo({top:0});
    // Selecting from the picker replaces it; Back does not reopen a stale picker.
    if (fromSheet) navigation.save(); else navigation.push();
    updateNavigation();
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
    const id = el('galleryNote').dataset.itemId;
    const busy = !id || selected?.id !== id || saving.has(id);
    ['author', 'body'].forEach(name => { el('galleryNote').elements[name].disabled = busy; });
    el('galleryNote').querySelector('button').disabled = busy;
  }
  function renderDetail(item, initial) {
    el('galleryTitle').textContent = cardName(item);
    if (item._offline_image_url && el('galleryViewer').open) el('galleryFull').src = item._offline_image_url;
    el('galleryViewerDate').textContent = dateLabel(item.document_date);
    el('gallerySource').textContent = `${item.filename} · page ${item.page}, work order ${item.part}`;
    el('galleryNotesContext').textContent = `${cardName(item)} · ${dateLabel(item.document_date)}`;
    const notes = item.notes.map(note => {
      const article = text('article', ''); const at = new Date(note.created * 1000);
      const stamp = text('time', at.toLocaleString()); stamp.dateTime = at.toISOString();
      article.append(text('strong', note.author), stamp, text('p', note.body)); return article;
    });
    const version = item.id + ':' + item.notes.map(n => n.id).join(',');
    el('galleryViewerNotesSection').hidden = !notes.length;
    if (initial || notesVersion !== version) {
      el('galleryNotes').replaceChildren(...notes);
      notesVersion = version;
    }
    updateCard(item);
  }
  async function detail(initial = false) {
    if (!selected) return;
    const id = selected.id, token = ++detailGeneration;
    pendingDetails++;
    try {
      let item;
      try {
        item = await api('/gallery/api/items/' + id);
        offlineMode = false;
      } catch (networkError) {
        item = await offline.detail(id);
        if (!item) throw networkError;
        offlineMode = true;
      }
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
  function openViewer(item, record = true) {
    if (record) navigation.save();
    selected = item; actions(); el('galleryViewerMessage').textContent = '';
    el('galleryTitle').textContent = cardName(item); el('galleryViewerDate').textContent = dateLabel(item.document_date);
    el('gallerySource').textContent = `${item.filename} · page ${item.page}, work order ${item.part}`;
    el('galleryFull').src = item._offline_image_url || '/gallery/image/' + item.id;
    showDialog('galleryViewer', false); el('galleryViewer').scrollTop = 0;
    el('galleryViewer').querySelector('[data-close]').focus({preventScroll:true});
    if (record) navigation.push();
    return detail().catch(() => {});
  }
  async function openNotes(record = true) {
    if (!currentCard()) return;
    if (record) navigation.save();
    const saved = drafts.get(selected.id) || {author:'', body:'', noteId:randomId()};
    drafts.set(selected.id, saved);
    el('galleryNote').dataset.itemId = selected.id;
    el('galleryNote').elements.author.value = saved.author; el('galleryNote').elements.body.value = saved.body;
    el('galleryNoteMessage').textContent = '';
    el('galleryNotesContext').textContent = `${cardName(selected)} · ${dateLabel(selected.document_date)}`;
    noteControls(); showDialog('galleryNotesSheet', false);
    if (record) navigation.push();
    try {
      await detail(true);
    } catch (_) { /* The sheet keeps the error visible. */ }
  }
  function closeDialogs() { document.querySelectorAll('dialog[open]').forEach(d => d.close()); }
  async function related() {
    const target = currentCard();
    if (!target || actionPending) return;
    const id = target.id;
    actionPending = true; actions();
    try {
      await detail();
      if (selected?.id !== id) return;
      if (!selected.lead_name) {
        const message = 'The lead name could not be read on this card. Related results are unavailable.';
        el(el('galleryViewer').open ? 'galleryViewerMessage' : 'galleryMessage').textContent = message;
        return; // Never open a name-entry prompt or guess a different lead.
      }
      navigation.save(); chooseLatest = false;
      relatedId = id; query = ''; dateFilter = ''; dates.setFilter(''); closeDialogs();
      await load(); window.scrollTo({top:0}); navigation.push();
    } catch (error) { el('galleryMessage').textContent = error.message; }
    finally { actionPending = false; actions(); focus.reset(); }
  }
  function openSearch() {
    el('query').value = query; showDialog('gallerySearchSheet'); el('query').focus();
  }
  document.querySelectorAll('[data-action]').forEach(button => {
    button.addEventListener('click', () => ({related, notes:openNotes, search:openSearch})[button.dataset.action]());
  });
  document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => requestClose(button.dataset.close)));
  document.querySelectorAll('dialog').forEach(dialog => {
    dialog.addEventListener('click', event => { if (event.target === dialog) {
      const box = dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) requestClose(dialog.id);
    }});
    dialog.addEventListener('cancel', event => { event.preventDefault(); requestClose(dialog.id); });
    dialog.addEventListener('close', () => {
      if (galleryDirty && !navigation.restoring && !document.querySelector('dialog[open]')) { galleryDirty = false; load(); }
      focus.reset();
    });
  });
  el('galleryNotesSheet').addEventListener('close', () => { if (!el('galleryNotesSheet').open) { draft(); delete el('galleryNote').dataset.itemId; } });
  el('galleryViewer').addEventListener('close', () => { if (!el('galleryViewer').open) el('galleryFull').removeAttribute('src'); });
  el('galleryViewerDate').onclick = () => dates.open(selected?.document_date || 'undated');
  el('galleryMore').onclick = () => load(false);
  el('galleryBack').onclick = () => navigation.back();
  el('galleryDateRefresh').onclick = () => {
    galleryDirty = true;
    if (offline.isEnabled() && navigator.onLine) offline.sync().catch(() => {});
    requestClose('galleryDateSheet');
  };
  el('galleryOfflineToggle').onchange = async event => {
    const toggle = event.currentTarget;
    toggle.disabled = true;
    try {
      await offline.setEnabled(toggle.checked);
    } catch (error) {
      toggle.checked = offline.isEnabled();
      el('galleryOfflineStatus').textContent = error.message;
    } finally {
      toggle.disabled = false;
    }
  };
  el('galleryShare').onclick = async () => {
    const button = el('galleryShare');
    if (!preparedShare) {
      el('galleryOfflineStatus').textContent = 'Preparing share link…';
      try { await prepareShare(); }
      catch (error) {
        el('galleryOfflineStatus').textContent = 'Could not share: ' + error.message;
        return;
      }
    }
    const shared = preparedShare;
    preparedShare = null;
    button.disabled = true;

    // Invoke both native operations before awaiting either one. With a prepared
    // URL this keeps the phone's user gesture intact for the Web Share API.
    const copyPromise = copyShareLink(shared.url);
    let nativeShare = null;
    if (navigator.share) {
      try {
        nativeShare = navigator.share({
          title:'Stats Gallery',
          text:'24-hour gallery access',
          url:shared.url,
        });
      } catch (error) {
        nativeShare = Promise.reject(error);
      }
    }

    // Prepare the next one-time link in the background for the next tap.
    prepareShare(true).catch(() => {});

    let copied = false;
    try { copied = await copyPromise; } catch (_) { copied = false; }

    if (nativeShare) {
      try {
        await nativeShare;
        el('galleryOfflineStatus').textContent = copied
          ? '24-hour access link copied and shared.'
          : '24-hour access link shared.';
      } catch (error) {
        if (error.name === 'AbortError') {
          el('galleryOfflineStatus').textContent = copied
            ? '24-hour access link copied.'
            : 'Sharing canceled.';
        } else {
          el('galleryOfflineStatus').textContent = copied
            ? 'Link copied. The phone share menu could not open.'
            : 'Could not share: ' + error.message;
        }
      }
    } else if (copied) {
      el('galleryOfflineStatus').textContent = window.isSecureContext
        ? '24-hour access link copied. Native share menu is unavailable in this browser.'
        : '24-hour access link copied. The phone share menu requires HTTPS.';
    } else {
      el('galleryOfflineStatus').textContent = '24-hour access link: ' + shared.url;
    }
    button.disabled = Boolean(sharePreparing);
  };
  el('galleryRefresh').onclick = () => { galleryDirty = true; requestClose('galleryInfoSheet'); };
  el('gallerySearch').onsubmit = async event => {
    event.preventDefault(); navigation.save(); chooseLatest = false; query = el('query').value.trim(); relatedId = null; selected = null; dateFilter = ''; dates.setFilter('');
    closeDialogs(); actions(); await load(); window.scrollTo({top:0}); navigation.save(); updateNavigation();
  };
  el('galleryNote').addEventListener('input', draft);
  el('galleryNote').onsubmit = async event => {
    event.preventDefault();
    const form = event.currentTarget, id = form.dataset.itemId;
    if (!id || selected?.id !== id || saving.has(id)) return;
    draft();
    const data = new FormData(form); data.set('note_id', drafts.get(id).noteId);
    saving.add(id); noteControls(); el('galleryNoteMessage').textContent = 'Saving…';
    try {
      await api(`/gallery/api/items/${id}/notes`, {method:'POST', body:data});
      drafts.set(id, {author:data.get('author'), body:'', noteId:randomId()});
      if (selected?.id === id) {
        form.elements.body.value = ''; el('galleryNoteMessage').textContent = 'Saved. Other open devices update within five seconds.';
        await detail().catch(() => { el('galleryNoteMessage').textContent = 'Saved. Reopen notes to refresh the list.'; });
      }
    } catch (error) {
      if (selected?.id === id && offline.isEnabled() && !error.status) {
        try {
          const note = {
            id:String(data.get('note_id')),
            author:String(data.get('author') || '').trim() || 'Anonymous',
            body:String(data.get('body') || '').trim(),
            created:Date.now()/1000,
          };
          await offline.queueNote(id, note);
          drafts.set(id, {author:note.author === 'Anonymous' ? '' : note.author, body:'', noteId:randomId()});
          form.elements.body.value = '';
          const cached = await offline.detail(id);
          if (cached && selected?.id === id) {
            selected = cached; renderDetail(cached, true); actions();
          }
          el('galleryNoteMessage').textContent = 'Saved offline. It will sync when Stats is reachable again.';
        } catch (offlineError) {
          el('galleryNoteMessage').textContent = 'Not saved: ' + offlineError.message;
        }
      } else if (selected?.id === id) {
        el('galleryNoteMessage').textContent = 'Not saved: ' + error.message;
      }
    }
    finally { saving.delete(id); noteControls(); }
  };
  setInterval(() => { if (selected && !pendingDetails && !document.hidden && (el('galleryViewer').open || el('galleryNotesSheet').open)) detail().catch(() => {}); }, 5000);
  setInterval(() => { if (!document.hidden && el('galleryInfoSheet').open) summary(); }, 15000);
  setInterval(() => { if (!document.hidden && navigator.onLine && offline.isEnabled()) offline.sync().catch(() => {}); }, 60000);
  setInterval(() => { if (!document.hidden && navigator.onLine) configureAccess().catch(() => {}); }, 15 * 60 * 1000);
  window.addEventListener('online', async () => {
    const wasOffline = offlineMode;
    try {
      await configureAccess();
      if (offline.isEnabled()) await offline.sync();
      if (wasOffline) await load();
    } catch (_) { /* The cached gallery remains available. */ }
  });
  async function start() {
    try {
      await configureAccess();
    } catch (error) {
      el('galleryMessage').textContent = error.message;
      return;
    }
    actions();
    if (initialView) {
      navigation.restoring = true;
      restoreView(initialView).finally(() => { navigation.restoring = false; updateNavigation(); focus.reset(); });
    } else load().then(() => navigation.save());
  }
  start();
})();
