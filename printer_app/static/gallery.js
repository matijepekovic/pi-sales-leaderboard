import { GalleryDates } from './gallery_dates.js';
import { GalleryFocus } from './gallery_focus.js';
import { GalleryNavigation } from './gallery_navigation.js';
import { GalleryNetwork } from './gallery_network.js';
import { GalleryOffline } from './gallery_offline.js';

'use strict';
(() => {
  const el = id => document.getElementById(id);
  const searchModes = {
    rep:{label:'Rep', placeholder:'Enter a rep name…', subject:'rep names'},
    lead_name:{label:'H/O', placeholder:'Enter H/O name…', subject:'H/O names'},
    address:{label:'Address', placeholder:'Enter a street or address…', subject:'addresses'},
  };
  const checkedSearchField = value => Object.hasOwn(searchModes, value) ? value : 'lead_name';
  const initialView = history.state?.gallery?.view;
  let chooseLatest = !initialView;
  const nextFrame = () => new Promise(resolve => requestAnimationFrame(resolve));
  const cards = new Map(), groups = new Map(), drafts = new Map(), saving = new Set();
  let query = '', relatedId = null, selected = null, offset = 0, total = 0, dateFilter = '';
  let searchField = 'lead_name';
  let searchOpen = false, searchTimer = null;
  let generation = 0, detailGeneration = 0, loading = false, galleryDirty = false, actionPending = false, notesVersion = '', pendingDetails = 0;
  let access = null, offlineMode = false;
  let shareQrSessionId = '';
  const network = new GalleryNetwork({
    onChange: reachable => {
      if (!reachable && offline.isEnabled()) {
        el('galleryOfflineStatus').textContent = 'Stats unreachable · using cards stored on this phone';
      }
    },
  });
  const offline = new GalleryOffline({
    network,
    onStatus: message => { el('galleryOfflineStatus').textContent = message; },
  });
  const dates = new GalleryDates({
    onSelect: chooseDate, openDialog: id => showDialog(id),
    blocked: () => searchOpen || loading || navigation.restoring || Boolean(document.querySelector('dialog[open]')),
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
    const context = Boolean(relatedId || query || searchOpen);
    document.querySelector('.gallery-date-nav').dataset.context = String(context);
    el('galleryMain').dataset.singleDate = String(Boolean(dateFilter));
    el('galleryMain').dataset.searching = String(searchOpen);
    el('gallerySearchSheet').hidden = !searchOpen;
    el('galleryViewerDate').disabled = searchOpen;
    el('galleryBack').hidden = !context || navigation.depth === 0;
  }
  function captureView() {
    const navBottom = (searchOpen ? el('gallerySearchSheet') : document.querySelector('.gallery-date-nav')).getBoundingClientRect().bottom;
    const anchor = [...el('galleryCards').querySelectorAll('.gallery-card')]
      .find(node => node.getBoundingClientRect().bottom > navBottom);
    return {query, searchField, searchOpen, relatedId, dateFilter, count:cards.size, scroll:window.scrollY,
      anchor:anchor?.dataset.id, anchorTop:anchor?.getBoundingClientRect().top,
      selected:selected?.id, viewerScroll:el('galleryViewer').scrollTop,
      dialogs:[...document.querySelectorAll('dialog[open]')].map(node => node.id),
      searchDraft:el('query').value, searchDraftField:selectedSearchField()};
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
    clearTimeout(searchTimer); searchTimer = null;
    chooseLatest = false;
    const restoredField = checkedSearchField(view.searchField);
    const reload = galleryDirty || query !== view.query || relatedId !== view.relatedId ||
      dateFilter !== view.dateFilter || searchField !== restoredField || loading || !cards.size;
    galleryDirty = false; detailGeneration++;
    closeDialogs();
    // Native close events must finish saving the old draft before opening a new sheet.
    await nextFrame();
    query = view.query || ''; relatedId = view.relatedId || null; dateFilter = view.dateFilter || '';
    searchField = restoredField;
    searchOpen = Boolean(view.searchOpen || query);
    if (searchOpen) dateFilter = '';
    el('query').value = view.searchDraft ?? query;
    searchControls(view.searchDraftField || searchField);
    updateNavigation();
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
      else if (id === 'galleryLeadSheet' && selected && editIdentityCapability()) openLeadEditor(false);
      else if (id === 'galleryDateSheet') dates.open();
      else if (id === 'galleryMenuSheet') openMenu(false);
      else if (id === 'galleryShareSheet' && shareCapability()) await openShare(false);
      else if (id === 'galleryInfoSheet') { showDialog(id, false); summary(); }
    }
    actions();
    if (searchOpen && !document.querySelector('dialog[open]') &&
        (el('query').value.trim() !== query || selectedSearchField() !== searchField)) queueSearch();
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
  const cardImageUrl = item => item._offline_image_url || '/gallery/image/' + item.id +
    (item.image_revision ? '?v=' + encodeURIComponent(item.image_revision) : '');
  const cardOrigin = item => item.origin === 'morning' ? 'Awaiting scan · ' : '';
  function updateImage(image, item) {
    const url = cardImageUrl(item);
    if (image.getAttribute('src') !== url) image.src = url;
    image.alt = `${cardName(item)} — complete work order, ${dateLabel(item.document_date)}`;
  }
  async function api(url, options) {
    return network.json(url, options);
  }
  function shareCapability() {
    return Boolean(access?.capabilities?.includes('share'));
  }
  function editIdentityCapability() {
    return Boolean(access?.capabilities?.includes('edit_identity')) && !offlineMode;
  }
  function shareExpiry(value) {
    return new Date(Number(value) * 1000).toLocaleString([], {
      month:'short', day:'numeric', hour:'numeric', minute:'2-digit'
    });
  }
  function clearShareQr() {
    shareQrSessionId = '';
    el('galleryShareQrSection').hidden = true;
    el('galleryShareQrCode').replaceChildren();
    el('galleryShareQrName').textContent = '';
    el('galleryShareQrExpiry').textContent = '';
  }
  function renderShareQr(svgText, sessionInfo) {
    const parsed = new DOMParser().parseFromString(String(svgText), 'image/svg+xml');
    const root = parsed.documentElement;
    if (!root || root.localName !== 'svg' || parsed.querySelector('parsererror,script')) {
      throw new Error('Could not render the access QR code.');
    }
    shareQrSessionId = sessionInfo.id;
    el('galleryShareQrCode').replaceChildren(document.importNode(root, true));
    el('galleryShareQrName').textContent = sessionInfo.name;
    el('galleryShareQrExpiry').textContent = 'Access expires ' + shareExpiry(sessionInfo.expires) + '.';
    el('galleryShareQrSection').hidden = false;
  }
  function renderActiveShares(sessions) {
    const host = el('galleryActiveShares');
    host.replaceChildren();
    if (!sessions.length) {
      host.append(text('p', 'No active access sessions.', 'muted'));
      return;
    }
    sessions.forEach(item => {
      const article = text('article', '', 'gallery-share-session');
      const copy = document.createElement('span');
      copy.append(
        text('strong', item.name),
        text('small', (item.opened ? 'Opened · ' : 'Waiting for scan · ') + 'expires ' + shareExpiry(item.expires))
      );
      const revoke = text('button', 'Revoke');
      revoke.type = 'button';
      revoke.className = 'gallery-share-revoke';
      revoke.onclick = async () => {
        revoke.disabled = true;
        const form = new FormData();
        form.set('csrf', el('galleryShareForm').elements.csrf.value);
        try {
          await api('/gallery/api/shares/' + item.id + '/revoke', {method:'POST', body:form});
          if (shareQrSessionId === item.id) clearShareQr();
          el('galleryShareMessage').textContent = item.name + ' access revoked.';
          await loadActiveShares();
        } catch (error) {
          el('galleryShareMessage').textContent = 'Could not revoke access: ' + error.message;
          revoke.disabled = false;
        }
      };
      article.append(copy, revoke);
      host.append(article);
    });
  }
  async function loadActiveShares() {
    const data = await api('/gallery/api/shares');
    const sessions = data.sessions || [];
    if (shareQrSessionId && !sessions.some(item => item.id === shareQrSessionId)) clearShareQr();
    renderActiveShares(sessions);
  }
  async function openShare(record = true) {
    if (!shareCapability()) return;
    el('galleryShareMessage').textContent = '';
    if (record) showDialog('galleryShareSheet');
    else showDialog('galleryShareSheet', false);
    el('galleryShareForm').elements.name.focus();
    try { await loadActiveShares(); }
    catch (error) { el('galleryShareMessage').textContent = 'Could not load active access: ' + error.message; }
  }
  function accessControls(info, resumed = false) {
    // Offline is exposed only on the already-secure Gallery. The certificate
    // setup page remains server-side but there is intentionally no UI path to it.
    const canOffline = resumed ||
      (window.isSecureContext && Boolean(info?.capabilities?.includes('offline')));
    const canShare = !resumed && Boolean(info?.capabilities?.includes('share'));
    el('galleryOfflineWrap').hidden = !canOffline;
    el('galleryShare').hidden = !canShare;
    if (!canShare) {
      if (el('galleryShareSheet').open) el('galleryShareSheet').close();
      clearShareQr();
    }
    el('galleryOfflineToggle').checked = canOffline && offline.isEnabled();
    if (!canOffline) el('galleryOfflineStatus').textContent = '';
    const title = el('galleryTitle');
    const canEditIdentity = !resumed && Boolean(info?.capabilities?.includes('edit_identity'));
    title.dataset.editable = String(canEditIdentity);
    title.title = canEditIdentity ? 'Long press to change this lead name everywhere' : '';
    if (info?.csrf) {
      const csrf = el('galleryNote').elements.csrf;
      if (csrf) csrf.value = info.csrf;
      const shareCsrf = el('galleryShareForm').elements.csrf;
      if (shareCsrf) shareCsrf.value = info.csrf;
      const leadCsrf = el('galleryLeadForm').elements.csrf;
      if (leadCsrf) leadCsrf.value = info.csrf;
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
      if ((!error.status || error.status >= 500) && await offline.resume()) {
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
  function cardSubtitle(item) {
    const base = cardOrigin(item) + `Page ${item.page} · work order ${item.part}`;
    return item.assigned_service_resource ? base + ` · Rep: ${item.assigned_service_resource}` : base;
  }
  function updateCard(item) {
    const card = cards.get(item.id);
    if (!card) return;
    Object.assign(card.item, item);
    if (!item._offline_image_url && !offlineMode) delete card.item._offline_image_url;
    card.name.textContent = cardName(card.item);
    card.subtitle.textContent = cardSubtitle(card.item);
    updateImage(card.image, card.item);
    const count = item.notes ? item.notes.length : item.notes_count;
    if (count !== undefined) card.badge.textContent = `${count} ${count === 1 ? 'note' : 'notes'}`;
  }
  function addCard(item) {
    if (cards.has(item.id)) { updateCard(item); return; }
    const key = item.document_date || 'undated';
    if (!groups.has(key)) {
      const section = text('section', '', 'gallery-day'); section.dataset.date = key;
      const heading = text('div', '', 'gallery-day-heading');
      const label = item.document_date ? new Date(item.document_date + 'T12:00:00').toLocaleDateString('en-US', {weekday:'long'}) : 'Confirm in notes';
      const title = text('h2', '');
      const dateButton = text('button', dateLabel(item.document_date) + ' ⌄', 'gallery-date-trigger');
      dateButton.type = 'button'; dateButton.setAttribute('aria-haspopup', 'dialog');
      dateButton.disabled = searchOpen;
      dateButton.setAttribute('aria-controls', 'galleryDateSheet');
    dateButton.addEventListener('click', () => { if (!searchOpen) dates.open(key); });
      title.append(dateButton); heading.append(title, text('span', label));
      const list = text('div', '', 'gallery-day-cards'); section.append(heading, list);
      groups.set(key, list); el('galleryCards').append(section);
    }
    const node = text('button', '', 'gallery-card'); node.type = 'button'; node.dataset.id = item.id;
    const image = document.createElement('img'); image.loading = 'lazy'; image.decoding = 'async';
    // Always use the full stored image. Never crop/cover it or request thumbnails.
    updateImage(image, item);
    const meta = text('span', '', 'gallery-card-meta');
    const caption = text('span', ''); const name = text('span', cardName(item), 'gallery-card-name');
    const subtitle = text('span', cardSubtitle(item), 'gallery-card-subtitle');
    caption.append(name, subtitle);
    const badge = text('span', `${item.notes_count} ${item.notes_count === 1 ? 'note' : 'notes'}`, 'gallery-card-badge');
    meta.append(caption, badge); node.append(image, meta);
    node.addEventListener('click', () => openViewer(cards.get(item.id).item));
    cards.set(item.id, {node, item, image, name, subtitle, badge}); groups.get(key).append(node);
  }
  async function load(reset = true) {
    if (!reset && loading) return;
    if (reset) { generation++; offset = 0; cards.clear(); groups.clear(); selected = null; detailGeneration++; el('galleryCards').replaceChildren(); focus.reset(); actions(); }
    el('galleryDateMessage').textContent = '';
    const token = generation, start = offset, related = relatedId;
    loading = true; dates.busy(true); el('galleryCards').setAttribute('aria-busy', 'true'); el('galleryMore').disabled = true; el('galleryMessage').textContent = reset ? 'Loading cards…' : '';
    const suffix = `&date=${encodeURIComponent(dateFilter)}&field=${encodeURIComponent(searchField)}`;
    const url = (related ? `/gallery/api/items/${related}/related?offset=${start}` : `/gallery/api/items?q=${encodeURIComponent(query)}&offset=${start}`) + suffix;
    try {
      let data;
      try {
        if (offlineMode && !network.isReachable()) throw new Error('Stats is unreachable from this network.');
        data = await api(url);
        offlineMode = false;
      } catch (networkError) {
        data = await offline.list({q:query, field:searchField, relatedId:related, date:dateFilter, offset:start});
        if (!data) throw networkError;
        offlineMode = true;
        el('galleryOfflineStatus').textContent = 'Stats unreachable · showing cards stored on this phone';
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
      el('galleryFilterTitle').textContent = related ? (data.lead_name || data.address || 'Related work orders') : query;
      el('galleryFilterHint').textContent = related ? 'Name letters within 1 character or exact address · all retained dates' :
        'Matching ' + searchModes[searchField].subject + ' only';
      el('galleryMore').hidden = offset >= total;
      el('galleryEmpty').hidden = total !== 0;
      el('galleryEmpty').textContent = dateFilter ? 'No work orders on this date. Choose another date.' : query || related ? 'No matching work orders.' : 'No work orders yet.';
      el('galleryMessage').textContent = ''; updateNavigation(); actions();
      if (searchOpen) el('gallerySearchHint').textContent = `All dates · ${total} ${total === 1 ? 'card' : 'cards'}`;
    } catch (error) { if (token === generation) el('galleryMessage').textContent = error.message; }
    finally { if (token === generation) { loading = false; dates.busy(false); el('galleryCards').setAttribute('aria-busy', 'false'); el('galleryMore').disabled = false; focus.reset(); } }
  }
  async function chooseDate(value) {
    if (navigation.restoring || searchOpen) return;
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
    if (el('galleryViewer').open) updateImage(el('galleryFull'), item);
    el('galleryViewerDate').textContent = dateLabel(item.document_date);
    el('gallerySource').textContent = cardOrigin(item) + `${item.filename} · page ${item.page}, work order ${item.part}` +
      (item.assigned_service_resource ? ` · Rep: ${item.assigned_service_resource}` : '');
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
        if (offlineMode && !network.isReachable()) throw new Error('Stats is unreachable from this network.');
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
    el('gallerySource').textContent = cardOrigin(item) + `${item.filename} · page ${item.page}, work order ${item.part}` +
      (item.assigned_service_resource ? ` · Rep: ${item.assigned_service_resource}` : '');
    updateImage(el('galleryFull'), item);
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
  function openLeadEditor(record = true) {
    if (!selected?.id || !editIdentityCapability()) return;
    if (record) navigation.save();
    const form = el('galleryLeadForm');
    const unnamed = !selected.lead_name;
    form.dataset.itemId = selected.id;
    form.dataset.unnamed = String(unnamed);
    form.elements.lead_name.value = selected.lead_name || '';
    el('galleryLeadContext').textContent =
      selected.address || 'No address was recognized on this work order.';
    el('galleryLeadScope').textContent = unnamed
      ? 'This work order has no lead name yet. The first name you set applies only to this work order.'
      : 'This is a global Gallery update. Lead-name letters within 1 character or the exact same address will receive the new lead name. Symbols and digits in names are ignored.';
    el('galleryLeadSubmit').textContent = unnamed ? 'Set lead name' : 'Update lead name everywhere';
    el('galleryLeadMessage').textContent = '';
    showDialog('galleryLeadSheet', false);
    if (record) navigation.push();
    form.elements.lead_name.focus();
    if (!unnamed) form.elements.lead_name.select();
  }
  function closeDialogs() { document.querySelectorAll('dialog[open]').forEach(d => d.close()); }
  async function related() {
    if (!el('galleryViewer').open) return;
    const target = currentCard();
    if (!target || actionPending) return;
    const id = target.id;
    actionPending = true; actions();
    try {
      await detail();
      if (selected?.id !== id) return;
      navigation.save(); chooseLatest = false;
      clearTimeout(searchTimer); searchTimer = null; searchOpen = false;
      relatedId = id; query = ''; dateFilter = ''; dates.setFilter(''); closeDialogs(); updateNavigation();
      await load(); window.scrollTo({top:0}); navigation.push();
    } catch (error) { el('galleryMessage').textContent = error.message; }
    finally { actionPending = false; actions(); focus.reset(); }
  }
  function openMenu(record = true) {
    showDialog('galleryMenuSheet', record);
  }
  async function openSearch() {
    if (searchOpen && !document.querySelector('dialog[open]')) {
      window.scrollTo({top:0}); el('query').focus(); return;
    }
    navigation.save(); closeDialogs(); chooseLatest = false;
    searchOpen = true; relatedId = null; dateFilter = ''; dates.setFilter('');
    el('query').value = query; searchControls(searchField); updateNavigation();
    window.scrollTo({top:0}); el('query').focus(); navigation.push();
    await load(); navigation.save();
  }
  function selectedSearchField() {
    return checkedSearchField(el('gallerySearch').querySelector('input[name="field"]:checked')?.value);
  }
  function searchControls(field) {
    const mode = checkedSearchField(field), info = searchModes[mode];
    el('gallerySearch').querySelectorAll('input[name="field"]').forEach(input => {
      input.checked = input.value === mode;
    });
    el('galleryQueryLabel').textContent = info.label;
    el('query').placeholder = info.placeholder;
    el('gallerySearchHint').textContent = 'All dates';
  }
  async function searchNow() {
    clearTimeout(searchTimer); searchTimer = null;
    if (!searchOpen || document.querySelector('dialog[open]')) return;
    chooseLatest = false; query = el('query').value.trim(); searchField = selectedSearchField();
    relatedId = null; dateFilter = ''; dates.setFilter('');
    navigation.save(); window.scrollTo({top:0});
    await load(); navigation.save();
  }
  function queueSearch(event) {
    clearTimeout(searchTimer);
    generation++; // A response for the previous input must never replace newer results.
    if (event?.isComposing) return;
    searchTimer = setTimeout(searchNow, 200);
  }
  el('gallerySearchFields').addEventListener('change', () => {
    searchControls(selectedSearchField()); queueSearch();
  });
  el('query').addEventListener('input', queueSearch);
  el('query').addEventListener('compositionend', queueSearch);
  el('gallerySearchClose').onclick = () => {
    clearTimeout(searchTimer); searchTimer = null;
    if (navigation.depth > 0) navigation.back();
    else {
      searchOpen = false; query = ''; el('query').value = ''; updateNavigation();
      load().then(() => navigation.save());
    }
  };
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
      if (searchOpen && !navigation.restoring && !document.querySelector('dialog[open]') &&
          (el('query').value.trim() !== query || selectedSearchField() !== searchField)) queueSearch();
      focus.reset();
    });
  });
  el('galleryNotesSheet').addEventListener('close', () => { if (!el('galleryNotesSheet').open) { draft(); delete el('galleryNote').dataset.itemId; } });
  el('galleryViewer').addEventListener('close', () => { if (!el('galleryViewer').open) el('galleryFull').removeAttribute('src'); });
  const leadTitle = el('galleryTitle');
  let leadPressTimer = null, leadPressStart = null, leadPressTriggered = false;
  const cancelLeadPress = () => {
    if (leadPressTimer) clearTimeout(leadPressTimer);
    leadPressTimer = null;
    leadPressStart = null;
  };
  leadTitle.addEventListener('pointerdown', event => {
    if (!editIdentityCapability() || !selected?.id || event.button > 0) return;
    leadPressTriggered = false;
    leadPressStart = {x:event.clientX,y:event.clientY};
    leadPressTimer = setTimeout(() => {
      leadPressTimer = null;
      leadPressTriggered = true;
      openLeadEditor();
    }, 550);
  });
  leadTitle.addEventListener('pointermove', event => {
    if (!leadPressStart) return;
    if (Math.hypot(event.clientX-leadPressStart.x,event.clientY-leadPressStart.y) > 12) cancelLeadPress();
  });
  ['pointerup','pointercancel','pointerleave'].forEach(name => leadTitle.addEventListener(name, cancelLeadPress));
  leadTitle.addEventListener('contextmenu', event => { if (editIdentityCapability()) event.preventDefault(); });
  leadTitle.addEventListener('click', event => {
    if (leadPressTriggered) { event.preventDefault(); event.stopPropagation(); leadPressTriggered = false; }
  });
  el('galleryViewerDate').onclick = () => { if (!searchOpen) dates.open(selected?.document_date || 'undated'); };
  el('galleryMore').onclick = () => load(false);
  el('galleryBack').onclick = () => navigation.back();
  el('galleryMenuButton').onclick = () => openMenu();
  el('galleryMenuRefresh').onclick = () => {
    galleryDirty = true;
    if (offline.isEnabled() && network.isReachable()) offline.sync().catch(() => {});
    requestClose('galleryMenuSheet');
  };
  el('galleryOfflineToggle').onchange = async event => {
    const toggle = event.currentTarget;
    if (!window.isSecureContext) {
      toggle.checked = false;
      return;
    }
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
  el('galleryLeadForm').onsubmit = async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const id = form.dataset.itemId;
    if (!id || selected?.id !== id || !editIdentityCapability()) return;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    el('galleryLeadMessage').textContent = 'Updating related work orders…';
    try {
      const result = await api('/gallery/api/items/' + id + '/lead-name', {method:'POST', body:new FormData(form)});
      galleryDirty = true;
      await detail(true);
      const noun = result.updated === 1 ? 'work order' : 'work orders';
      const message = result.scope === 'single'
        ? 'Lead name set for this work order.'
        : 'Lead name updated across ' + result.updated + ' related ' + noun + '.';
      el('galleryLeadMessage').textContent = message;
      el('galleryViewerMessage').textContent = message;
      form.dataset.unnamed = 'false';
      el('galleryLeadScope').textContent =
        'This is now a named work order. Future changes compare name letters only, with the exact-address fallback.';
      el('galleryLeadSubmit').textContent = 'Update lead name everywhere';
      if (offline.isEnabled()) offline.sync().catch(() => {});
    } catch (error) {
      el('galleryLeadMessage').textContent = 'Could not update lead name: ' + error.message;
    } finally { button.disabled = false; }
  };
  el('galleryShare').onclick = () => openShare();
  el('galleryShareForm').onsubmit = async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    el('galleryShareMessage').textContent = 'Creating access…';
    try {
      const data = new FormData(form);
      const result = await api('/gallery/api/share', {method:'POST', body:data});
      renderShareQr(result.qr_svg, result.session);
      form.elements.name.value = '';
      el('galleryShareMessage').textContent = '6-hour access ready. Show this QR code to ' + result.session.name + '.';
      await loadActiveShares();
    } catch (error) {
      el('galleryShareMessage').textContent = 'Could not create access: ' + error.message;
    } finally {
      button.disabled = false;
    }
  };
  el('galleryRefresh').onclick = () => { galleryDirty = true; requestClose('galleryInfoSheet'); };
  el('gallerySearch').onsubmit = async event => {
    event.preventDefault(); await searchNow();
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
  setInterval(() => {
    if (selected && !pendingDetails && !document.hidden &&
        (el('galleryViewer').open || el('galleryNotesSheet').open)) detail().catch(() => {});
  }, 5000);
  setInterval(() => {
    if (!document.hidden && network.isReachable() && el('galleryInfoSheet').open) summary();
  }, 15000);
  setInterval(() => {
    if (!document.hidden && network.isReachable() && offline.isEnabled()) offline.sync().catch(() => {});
  }, 60000);
  setInterval(() => {
    if (!document.hidden && network.isReachable() && el('galleryShareSheet').open) {
      loadActiveShares().catch(() => {});
    }
  }, 30000);

  let probingStats = false;
  async function probeStats() {
    if (document.hidden || probingStats) return;
    probingStats = true;
    const wasOffline = offlineMode;
    try {
      const reachable = await network.probe();
      if (!reachable) return;
      try {
        const live = await configureAccess();
        if (!live) return;
      } catch (error) {
        if (access?.role === 'guest' && (error.status === 401 || error.status === 403)) {
          location.replace('/gallery/');
        }
        return;
      }
      if (offline.isEnabled()) await offline.sync().catch(() => {});
      if (wasOffline) await load();
    } finally {
      probingStats = false;
    }
  }
  setInterval(() => { if (access?.role === 'guest') probeStats(); }, 15000);
  setInterval(() => { if (access?.role !== 'guest') probeStats(); }, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) probeStats(); });
  window.addEventListener('focus', probeStats);
  window.addEventListener('online', probeStats);
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
