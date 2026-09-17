/* Offline Runtime owns phone-local gallery persistence and queued note sync.
 * Gallery rendering stays in gallery.js; the server remains authoritative online. */
const DB_VERSION = 1;
const PAGE_SIZE = 24;
const MODE_KEY = 'stats.gallery.accessMode';
const SUBJECT_KEY = 'stats.gallery.offlineSubject';

const identityKey = (value, address = false) => {
  const aliases = address ? {
    street:'st', avenue:'ave', road:'rd', boulevard:'blvd', drive:'dr', lane:'ln',
    court:'ct', place:'pl', highway:'hwy', parkway:'pkwy', north:'n', south:'s',
    east:'e', west:'w', northeast:'ne', northwest:'nw', southeast:'se', southwest:'sw',
  } : {};
  return String(value || '').normalize('NFKD').toLocaleLowerCase()
    .replace(/[\u0300-\u036f]/g, '').match(/[a-z0-9]+/g)?.map(token => aliases[token] || token).join(' ') || '';
};
const bigramSimilarity = (left, right) => {
  if (!left || !right) return 0;
  if (left === right) return 1;
  if (Math.min(left.length, right.length) < 2) return 0;
  const counts = new Map();
  for (let i=0;i<left.length-1;i++) {
    const pair = left.slice(i,i+2); counts.set(pair,(counts.get(pair)||0)+1);
  }
  let common = 0;
  for (let i=0;i<right.length-1;i++) {
    const pair = right.slice(i,i+2), count = counts.get(pair)||0;
    if (count) { common++; counts.set(pair,count-1); }
  }
  return 2*common / ((left.length-1)+(right.length-1));
};
const closeIdentity = (left, right, threshold) => {
  if (!left || !right) return false;
  if (left === right || bigramSimilarity(left,right) >= threshold) return true;
  const a = new Set(left.split(' ')), b = new Set(right.split(' '));
  let common = 0; a.forEach(token => { if (b.has(token)) common++; });
  return common >= 2 && common / Math.max(1,Math.min(a.size,b.size)) >= .8;
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

export class GalleryOffline {
  constructor({onStatus = () => {}} = {}) {
    this.onStatus = onStatus;
    this.subject = '';
    this.allowed = false;
    this.csrf = '';
    this.db = null;
    this.syncing = false;
    this.urls = new Map();
  }

  enabledKey(subject = this.subject) {
    return 'stats.gallery.offlineEnabled.' + subject;
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
    if (this.isEnabled()) await this.open();
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
      if (!shellReady && !window.isSecureContext) {
        this.onStatus('Cards are downloaded. Reopening the gallery with no network requires a secure (HTTPS) connection.');
      }
    } else {
      this.onStatus('Offline automatic downloads are off. Existing downloaded cards stay on this phone.');
    }
  }

  async registerShell() {
    if (!('serviceWorker' in navigator) || !window.isSecureContext) return false;
    try {
      await navigator.serviceWorker.register('/gallery/service-worker.js', {scope:'/gallery/'});
      return true;
    } catch (_) {
      return false;
    }
  }

  async json(url, options) {
    const response = await fetch(url, {cache:'no-store', credentials:'same-origin', ...options});
    const data = await response.json().catch(() => ({error:'Request failed'}));
    if (!response.ok) {
      const error = new Error(data.error || 'Request failed');
      error.status = response.status;
      throw error;
    }
    return data;
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
    pending.put({id:note.id, item_id:itemId, author:note.author, body:note.body, created:note.created});
    const detail = {...card.detail, notes:[...(card.detail?.notes || []), note]};
    const summary = {...card.summary, notes_count:(card.summary?.notes_count || 0) + 1};
    cards.put({...card, summary, detail, saved_at:Date.now()});
    await transactionDone(tx);
  }

  async flushPending() {
    if (!this.csrf || !navigator.onLine) return;
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
        break;
      }
    }
  }

  async refreshDetail(id) {
    const card = await this.card(id);
    if (!card) return;
    const detail = await this.json('/gallery/api/items/' + id);
    await this.putCard({...card, detail, summary:{...card.summary, notes_count:detail.notes.length}, saved_at:Date.now()});
  }

  async sync() {
    if (!this.isEnabled() || !this.allowed || this.syncing || !navigator.onLine) return;
    this.syncing = true;
    try {
      this.onStatus('Updating offline cards…');
      await this.flushPending();
      const index = await this.json('/gallery/api/offline/index');
      let downloaded = 0;
      for (const summary of index.items || []) {
        const saved = await this.card(summary.id);
        let image = saved?.image;
        let detail = saved?.detail;
        const notesChanged = !saved || (saved.summary?.notes_count ?? -1) !== summary.notes_count;
        if (!image) {
          const response = await fetch('/gallery/image/' + summary.id, {cache:'no-store', credentials:'same-origin'});
          if (!response.ok) throw new Error('Could not download a work-order image.');
          image = await response.blob();
          downloaded++;
        }
        if (!detail || notesChanged) detail = await this.json('/gallery/api/items/' + summary.id);
        else detail = {...detail, ...summary};
        await this.putCard({id:summary.id, summary, detail, image, saved_at:Date.now()});
      }
      const all = await this.allCards();
      const pending = await this.pendingNotes();
      this.onStatus(
        `Offline ready · ${all.length} ${all.length === 1 ? 'card' : 'cards'} on this phone` +
        (downloaded ? ` · ${downloaded} new` : '') +
        (pending.length ? ` · ${pending.length} note${pending.length === 1 ? '' : 's'} waiting to sync` : '')
      );
    } finally {
      this.syncing = false;
    }
  }

  releaseUrls() {
    this.urls.forEach(url => URL.revokeObjectURL(url));
    this.urls.clear();
  }

  async imageUrl(id) {
    if (this.urls.has(id)) return this.urls.get(id);
    const card = await this.card(id);
    if (!card?.image) return '';
    const url = URL.createObjectURL(card.image);
    this.urls.set(id, url);
    return url;
  }

  async detail(id) {
    if (!this.isEnabled()) return null;
    const card = await this.card(id);
    if (!card?.detail) return null;
    return {...card.detail, _offline_image_url:await this.imageUrl(id)};
  }

  async list({q='', relatedId=null, date='', offset=0} = {}) {
    if (!this.isEnabled()) return null;
    let cards = await this.allCards();
    if (!cards.length) return null;
    const normalized = value => String(value || '').trim().toLocaleLowerCase();
    let relatedName = '', relatedAddress = '';
    if (relatedId) {
      const target = cards.find(card => card.id === relatedId);
      relatedName = target?.detail?.lead_name || target?.summary?.lead_name || '';
      relatedAddress = target?.detail?.address || target?.summary?.address || '';
      const name = identityKey(relatedName);
      const address = identityKey(relatedAddress, true);
      cards = (name || address) ? cards.filter(card => {
        const candidateName = identityKey(card.detail?.lead_name || card.summary?.lead_name || '');
        const candidateAddress = identityKey(card.detail?.address || card.summary?.address || '', true);
        return closeIdentity(name, candidateName, .76) ||
          closeIdentity(address, candidateAddress, .68);
      }) : [];
    }
    if (q.trim()) {
      const needle = normalized(q);
      cards = cards.filter(card => {
        const detail = card.detail || {};
        const notes = (detail.notes || []).map(note => note.author + ' ' + note.body).join(' ');
        return normalized([detail.text, detail.filename, detail.lead_name, notes].join(' ')).includes(needle);
      });
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
