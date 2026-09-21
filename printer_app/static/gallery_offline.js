/* Offline Runtime owns phone-local gallery persistence and queued note sync.
 * Gallery rendering stays in gallery.js; the server remains authoritative online. */
const DB_VERSION = 2;
const PAGE_SIZE = 24;
const MODE_KEY = 'stats.gallery.accessMode';
const SUBJECT_KEY = 'stats.gallery.offlineSubject';
const IMAGE_CACHE = 'stats-gallery-images-v1';
const SEARCH_COLUMNS = Object.freeze({
  rep:'assigned_service_resource', lead_name:'lead_name', address:'address',
});

// Match unicode61's Unicode words and Latin accent folding, without broadening
// selected-field search to notes, filenames, or arbitrary recognized text.
const searchTokens = value => String(value ?? '')
  .replace(/\p{Script=Latin}/gu, letter => letter.normalize('NFD').replace(/\p{M}/gu, ''))
  .toLowerCase().replace(/[\u0300-\u036f]/g, '')
  .replace(/[\u017f\u00b5\u03c2]/g, letter => ({'ſ':'s', 'µ':'μ', 'ς':'σ'})[letter])
  .match(/[\p{L}\p{N}\p{Co}]+/gu) || [];

const searchTerms = query => {
  const limited = Array.from(String(query ?? '')).slice(0, 300).join('');
  return [...limited.matchAll(/"([^"\n]+)"|([\p{L}\p{N}_]+)/gu)].slice(0, 20)
    .map(match => ({words:searchTokens(match[1] ?? match[2]), prefix:match[1] === undefined}));
};

const matchesSearch = (value, terms) => {
  const tokens = searchTokens(value);
  return terms.every(({words, prefix}) => words.length && tokens.some((_, start) =>
    words.every((word, index) => prefix && index === words.length - 1
      ? tokens[start + index]?.startsWith(word) : tokens[start + index] === word)));
};

const identityKey = value =>
  String(value || '').normalize('NFKD').toLocaleLowerCase()
    .replace(/[\u0300-\u036f]/g, '').match(/[a-z0-9]+/g)?.join(' ') || '';

const nameLetters = value =>
  String(value || '').normalize('NFKD').toLocaleLowerCase()
    .replace(/\p{M}/gu, '').match(/\p{L}/gu)?.join('') || '';

const withinOneCharacter = (left, right) => {
  if (!left || !right) return false;
  if (left === right) return true;
  if (Math.abs(left.length-right.length) > 1) return false;
  if (left.length > right.length) [left,right] = [right,left];
  if (left.length === right.length) {
    let differences = 0;
    for (let i=0;i<left.length;i++) if (left[i] !== right[i] && ++differences > 1) return false;
    return true;
  }
  let i=0,j=0,differences=0;
  while (i<left.length && j<right.length) {
    if (left[i] === right[j]) { i++; j++; continue; }
    if (++differences > 1) return false;
    j++;
  }
  return true;
};

const requestResult = request => new Promise((resolve, reject) => {
  request.onsuccess = () => resolve(request.result);
  request.onerror = () => reject(request.error);
});
const transactionDone = transaction => new Promise((resolve, reject) => {
  transaction.oncomplete = () => resolve();
  transaction.onabort = () => reject(transaction.error);
  transaction.onerror = () => reject(transaction.error);
});

const imageBytes = card => {
  const value = card?.image_bytes;
  if (value instanceof ArrayBuffer && value.byteLength) return value;
  if (ArrayBuffer.isView(value) && value.byteLength) {
    return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength);
  }
  return null;
};

const offlineImagePath = (subject, id) =>
  '/gallery/offline-image/' + encodeURIComponent(subject) + '/' + encodeURIComponent(id);
const imageRevision = card => String(card?.image_revision ?? card?.summary?.image_revision ?? '');
const withRevision = (path, revision) => path + (revision ? '?v=' + encodeURIComponent(revision) : '');

export class GalleryOffline {
  constructor({network, onStatus = () => {}} = {}) {
    if (!network) throw new Error('GalleryOffline requires the shared Gallery network runtime.');
    this.network = network;
    this.onStatus = onStatus;
    this.subject = '';
    this.allowed = false;
    this.csrf = '';
    this.db = null;
    this.syncing = false;
    this.syncRequested = false;
    this.urls = new Map();
  }

  enabledKey(subject = this.subject) {
    return 'stats.gallery.offlineEnabled.' + subject;
  }

  savedNoteAuthor(subject = this.subject) {
    if (!subject) return '';
    try { return localStorage.getItem('stats.gallery.noteAuthor.' + subject) || ''; }
    catch (_) { return ''; }
  }

  rememberNoteAuthor(value, subject = this.subject) {
    if (!subject) return;
    try { localStorage.setItem('stats.gallery.noteAuthor.' + subject, String(value ?? '')); }
    catch (_) { /* A saved note must not depend on storing a convenience preference. */ }
  }

  isEnabled() {
    return Boolean(this.subject) && localStorage.getItem(this.enabledKey()) === '1';
  }

  async configure(access) {
    this.csrf = access?.csrf || this.csrf;
    const full = access?.role === 'full' && access.capabilities?.includes('offline');
    localStorage.setItem(MODE_KEY, access?.role || 'guest');
    this.allowed = Boolean(full);
    if (!full) {
      if (this.db) this.db.close();
      this.releaseUrls();
      this.subject = '';
      this.db = null;
      return false;
    }
    if (this.subject && this.subject !== access.subject) {
      if (this.db) this.db.close();
      this.releaseUrls();
      this.db = null;
    }
    this.subject = access.subject;
    localStorage.setItem(SUBJECT_KEY, this.subject);
    if (this.isEnabled()) {
      await this.open();
      if (window.isSecureContext) await this.registerShell();
    }
    return this.isEnabled();
  }

  async resume() {
    if (localStorage.getItem(MODE_KEY) !== 'full') return false;
    const subject = localStorage.getItem(SUBJECT_KEY) || '';
    if (!subject || localStorage.getItem(this.enabledKey(subject)) !== '1') return false;
    this.subject = subject;
    this.allowed = true;
    await this.open();
    return true;
  }

  async open() {
    if (this.db || !this.subject) return this.db;
    this.db = await new Promise((resolve, reject) => {
      const request = indexedDB.open('stats-gallery-offline-' + this.subject, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains('cards')) db.createObjectStore('cards', {keyPath:'id'});
        if (!db.objectStoreNames.contains('pendingNotes')) db.createObjectStore('pendingNotes', {keyPath:'id'});
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    return this.db;
  }

  async setEnabled(value) {
    if (!this.allowed || !this.subject) throw new Error('Offline access is not available for this account.');
    localStorage.setItem(this.enabledKey(), value ? '1' : '0');
    if (value) {
      if (navigator.storage?.persist) navigator.storage.persist().catch(() => {});
      const shellReady = await this.registerShell();
      await this.sync();
      if (!shellReady) {
        this.onStatus(window.isSecureContext
          ? 'Cards are downloaded, but offline startup is not ready. Reopen the secure Gallery to retry.'
          : 'Cards are downloaded. Reopening away from the office requires the secure full-device setup.');
      }
    } else {
      this.onStatus('Offline automatic downloads are off. Existing downloaded cards stay on this phone.');
    }
  }

  async registerShell() {
    if (!('serviceWorker' in navigator) || !window.isSecureContext) return false;
    try {
      await navigator.serviceWorker.register('/gallery/service-worker.js', {scope:'/gallery/'});
      await navigator.serviceWorker.ready;
      return true;
    } catch (_) {
      return false;
    }
  }

  async json(url, options) {
    return this.network.json(url, options);
  }

  async imageCache() {
    if (!('caches' in globalThis)) return null;
    return caches.open(IMAGE_CACHE);
  }

  imagePath(id, revision = '') {
    return withRevision(offlineImagePath(this.subject, id), revision);
  }

  async ensureImage(id, legacyCard = null, revision = '') {
    const cache = await this.imageCache();
    if (!cache) throw new Error('Offline image cache is unavailable in this browser.');
    const key = this.imagePath(id, revision);
    const cached = await cache.match(key);
    if (cached) return key;

    try {
      // Image downloads get their own longer timeout; one slow card must not make
      // the whole Offline sync look complete while leaving later images missing.
      const response = await this.network.fetch(withRevision('/gallery/image/' + id, revision), {timeoutMs:20000});
      if (!response.ok) throw new Error('Could not download a work-order image.');
      const probe = await response.blob();
      if (!probe.size) throw new Error('Downloaded work-order image was empty.');
      // This device-owned URL identifies the subject, card and image revision.
      // Persist the bytes without the live endpoint's URL or cookie-vary headers.
      await cache.put(key, new Response(probe, {
        status:200, headers:{'Content-Type':probe.type || 'image/png'},
      }));
      return key;
    } catch (error) {
      const migrated = imageRevision(legacyCard) === revision
        ? await this.migrateLegacyImage(id, legacyCard) : '';
      if (migrated) return migrated;
      throw error;
    }
  }

  async migrateLegacyImage(id, card) {
    const cache = await this.imageCache();
    if (!cache) return '';
    const key = this.imagePath(id, imageRevision(card));
    if (await cache.match(key)) return key;

    let blob = null;
    const bytes = imageBytes(card);
    if (bytes) blob = new Blob([bytes], {type:card.image_type || 'image/png'});
    else if (card?.image instanceof Blob && card.image.size) blob = card.image;
    if (!blob?.size) return '';

    await cache.put(
      key,
      new Response(blob, {
        status:200,
        headers:{'Content-Type': blob.type || 'image/png', 'Cache-Control':'private, max-age=31536000'},
      }),
    );
    return key;
  }

  async card(id) {
    await this.open();
    const tx = this.db.transaction('cards', 'readonly');
    return requestResult(tx.objectStore('cards').get(id));
  }

  async putCard(card) {
    await this.open();
    const tx = this.db.transaction('cards', 'readwrite');
    tx.objectStore('cards').put(card);
    await transactionDone(tx);
  }

  async allCards() {
    await this.open();
    const tx = this.db.transaction('cards', 'readonly');
    return requestResult(tx.objectStore('cards').getAll());
  }

  async removeCachedImages(id, keep = '') {
    const cache = await this.imageCache();
    if (!cache) return;
    const path = this.imagePath(id);
    for (const request of await cache.keys()) {
      const url = new URL(request.url, 'https://offline.invalid');
      if (url.pathname === path && url.pathname + url.search !== keep) await cache.delete(request);
    }
    if (this.urls.has(id)) {
      URL.revokeObjectURL(this.urls.get(id));
      this.urls.delete(id);
    }
  }

  async removeMorningCard(id) {
    // Pending notes stay queued independently; an absent morning placeholder
    // must not remain visible as a phantom work order on this phone.
    await this.open();
    const tx = this.db.transaction('cards', 'readwrite');
    tx.objectStore('cards').delete(id);
    await transactionDone(tx);
    await this.removeCachedImages(id);
  }

  async pendingNotes() {
    await this.open();
    const tx = this.db.transaction('pendingNotes', 'readonly');
    return requestResult(tx.objectStore('pendingNotes').getAll());
  }

  async queueNote(itemId, note) {
    if (!this.isEnabled()) throw new Error('Turn on Offline before adding notes without the server.');
    await this.open();
    const tx = this.db.transaction(['cards','pendingNotes'], 'readwrite');
    const cards = tx.objectStore('cards');
    const pending = tx.objectStore('pendingNotes');
    const card = await requestResult(cards.get(itemId));
    if (!card) throw new Error('This work order has not been downloaded to this phone.');
    if (card.detail?.notes?.some(existing => existing.id === note.id)) {
      // This ID was already queued or confirmed by the server. A restored
      // confirmation must not append it again or recreate a delivered outbox row.
      await transactionDone(tx);
      return;
    }
    const queued = await requestResult(pending.get(note.id));
    if (queued && queued.item_id !== itemId) throw new Error('Conflicting note. Reload and try again.');
    const original = queued ? {id:queued.id, author:queued.author, body:queued.body, created:queued.created} : note;
    if (!queued) pending.put({id:note.id, item_id:itemId, author:note.author, body:note.body, created:note.created});
    const detail = {...card.detail, notes:[...(card.detail?.notes || []), original]};
    const summary = {...card.summary, notes_count:(card.summary?.notes_count || 0) + 1};
    cards.put({...card, summary, detail, saved_at:Date.now()});
    await transactionDone(tx);
  }

  async flushPending() {
    if (!this.csrf || !this.network.isReachable()) return;
    const notes = await this.pendingNotes();
    for (const note of notes) {
      const form = new FormData();
      form.set('csrf', this.csrf);
      form.set('note_id', note.id);
      form.set('author', note.author);
      form.set('body', note.body);
      try {
        await this.json('/gallery/api/items/' + note.item_id + '/notes', {method:'POST', body:form});
        const tx = this.db.transaction('pendingNotes', 'readwrite');
        tx.objectStore('pendingNotes').delete(note.id);
        await transactionDone(tx);
        await this.refreshDetail(note.item_id);
      } catch (error) {
        if (error.status === 401 || error.status === 403 || error.status === 400) throw error;
        if (error.status === 404) continue;
        break;
      }
    }
  }

  async refreshDetail(id) {
    const card = await this.card(id);
    if (!card) return;
    const detail = await this.json('/gallery/api/items/' + id);
    const summary = {...card.summary, notes_count:detail.notes.length};
    for (const column of [...Object.values(SEARCH_COLUMNS), 'sales_lead_status']) {
      if (Object.prototype.hasOwnProperty.call(detail, column)) summary[column] = detail[column];
    }
    await this.putCard({...card, detail, summary, saved_at:Date.now()});
  }

  async sync() {
    if (!this.isEnabled() || !this.allowed || !this.network.isReachable()) return;
    if (this.syncing) {
      this.syncRequested = true;
      return;
    }
    this.syncing = true;
    let failure;
    try {
      this.onStatus('Updating offline cards…');
      await this.flushPending();
      const index = await this.json('/gallery/api/offline/index');
      if (!Array.isArray(index.items)) throw new Error('Offline card index was incomplete.');
      let downloaded = 0, missingImages = 0;
      const indexed = new Set(index.items.map(summary => summary.id));
      for (const saved of await this.allCards()) {
        if (saved.summary?.origin === 'morning' && !indexed.has(saved.id)) await this.removeMorningCard(saved.id);
      }
      for (const summary of index.items) {
        const saved = await this.card(summary.id);
        let detail = saved?.detail;
        const notesChanged = !saved || (saved.summary?.notes_count ?? -1) !== summary.notes_count;
        const searchChanged = (saved?.detail?.search_revision ?? saved?.summary?.search_revision ?? 0) !==
          (summary.search_revision ?? 0);
        const revision = String(summary.image_revision ?? '');

        let imageReady = false;
        try {
          const cache = await this.imageCache();
          const key = this.imagePath(summary.id, revision);
          const hadImage = Boolean(cache && await cache.match(key));
          imageReady = Boolean(await this.ensureImage(summary.id, saved, revision));
          if (imageReady && !hadImage) downloaded++;
        } catch (_) {
          // Keep syncing metadata and later images. This card will retry on the
          // next live sync instead of blocking the entire Offline library.
          missingImages++;
        }

        const needsPhone = !Object.prototype.hasOwnProperty.call(detail || {}, 'phone_dial');
        if (!detail || needsPhone || notesChanged || searchChanged) {
          detail = await this.json('/gallery/api/items/' + summary.id);
        }
        else detail = {...detail, ...summary};

        if (imageReady) {
          // Metadata/notes live in IndexedDB. Image bodies live in Cache Storage.
          // A repaired record can now drop the legacy Blob/ArrayBuffer fields.
          await this.putCard({
            id:summary.id,
            summary,
            detail,
            image_revision:revision,
            saved_at:Date.now(),
          });
          await this.removeCachedImages(summary.id, this.imagePath(summary.id, revision));
        } else {
          // Preserve any legacy image bytes until a Cache Storage copy succeeds.
          await this.putCard({
            ...(saved || {}),
            id:summary.id,
            summary,
            detail,
            image_revision:imageRevision(saved),
            saved_at:Date.now(),
          });
        }
      }
      const all = await this.allCards();
      const pending = await this.pendingNotes();
      this.onStatus(
        `Offline ready · ${all.length} ${all.length === 1 ? 'card' : 'cards'} on this phone` +
        (downloaded ? ` · ${downloaded} images repaired` : '') +
        (missingImages ? ` · ${missingImages} image${missingImages === 1 ? '' : 's'} waiting to retry` : '') +
        (pending.length ? ` · ${pending.length} note${pending.length === 1 ? '' : 's'} waiting to sync` : '') +
        (!window.isSecureContext ? ' · secure setup required for relaunch' : '')
      );
    } catch (error) {
      failure = error;
    } finally {
      this.syncing = false;
    }
    const repeat = this.syncRequested;
    this.syncRequested = false;
    // A source refresh may finish after this pass captured its index. Coalesce
    // concurrent requests into one fresh pass, including after a recoverable error.
    if (repeat && this.isEnabled() && this.allowed && this.network.isReachable()) return this.sync();
    if (failure) throw failure;
  }

  releaseUrls() {
    this.urls.forEach(url => URL.revokeObjectURL(url));
    this.urls.clear();
  }

  async imageUrl(id) {
    const card = await this.card(id);
    const cache = await this.imageCache();
    const key = this.imagePath(id, imageRevision(card));
    if (cache && await cache.match(key)) return key;

    // An old install can still self-migrate readable IndexedDB image bytes while
    // already away from Stats. If that fails, the next live sync downloads it.
    const migrated = await this.migrateLegacyImage(id, card);
    if (migrated) return migrated;

    // Cache Storage is unavailable only on unsupported browser contexts. Keep a
    // last-resort object URL for old records rather than silently losing them.
    let blob = null;
    const bytes = imageBytes(card);
    if (bytes) blob = new Blob([bytes], {type:card.image_type || 'image/png'});
    else if (card?.image instanceof Blob && card.image.size) blob = card.image;
    if (!blob) return '';
    const url = URL.createObjectURL(blob);
    this.urls.set(id, url);
    return url;
  }

  async detail(id) {
    if (!this.isEnabled()) return null;
    const card = await this.card(id);
    if (!card?.detail) return null;
    return {...card.detail, _offline_image_url:await this.imageUrl(id)};
  }

  async list({q='', field='lead_name', relatedId=null, date='', offset=0} = {}) {
    if (!Object.prototype.hasOwnProperty.call(SEARCH_COLUMNS, field)) {
      throw new Error('Choose Rep, H/O, or Address.');
    }
    if (!this.isEnabled()) return null;
    let cards = [...await this.allCards()];
    if (!cards.length) return null;
    let relatedName = '', relatedAddress = '';
    if (relatedId) {
      const target = cards.find(card => card.id === relatedId);
      relatedName = target?.detail?.lead_name || target?.summary?.lead_name || '';
      relatedAddress = target?.detail?.address || target?.summary?.address || '';
      const name = nameLetters(relatedName);
      const address = identityKey(relatedAddress);
      cards = (name || address) ? cards.filter(card => {
        const candidateName = nameLetters(card.detail?.lead_name || card.summary?.lead_name || '');
        const candidateAddress = identityKey(card.detail?.address || card.summary?.address || '');
        return withinOneCharacter(name, candidateName) ||
          (Boolean(address) && address === candidateAddress);
      }) : [];
    }
    const terms = searchTerms(q);
    if (terms.length) {
      const column = SEARCH_COLUMNS[field];
      cards = cards.filter(card => matchesSearch(card.summary?.[column] ?? card.detail?.[column] ?? '', terms));
    }
    cards.sort((a,b) => {
      const ad = a.summary?.document_date || '', bd = b.summary?.document_date || '';
      if (ad !== bd) return bd.localeCompare(ad);
      return (a.summary?.page || 0) - (b.summary?.page || 0) ||
        (a.summary?.part || 0) - (b.summary?.part || 0) ||
        a.id.localeCompare(b.id);
    });
    const buckets = new Map();
    cards.forEach(card => {
      const key = card.summary?.document_date || null;
      buckets.set(key, (buckets.get(key) || 0) + 1);
    });
    const dates = [...buckets.entries()].map(([value,count]) => ({date:value,count}))
      .sort((a,b) => String(b.date || '').localeCompare(String(a.date || '')));
    if (date === 'undated') cards = cards.filter(card => !card.summary?.document_date);
    else if (date) cards = cards.filter(card => card.summary?.document_date === date);
    const total = cards.length;
    const page = cards.slice(offset, offset + PAGE_SIZE);
    const items = [];
    for (const card of page) {
      items.push({...card.summary, _offline_image_url:await this.imageUrl(card.id)});
    }
    return {total, items, dates, offline:true, lead_name:relatedName, address:relatedAddress};
  }
}
