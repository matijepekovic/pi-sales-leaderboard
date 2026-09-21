/** Gallery contact intent: native phone links, followed by an explicit shared note. */
export class GalleryContact {
  constructor({openDialog, closeDialog, saveNote, onSaved=()=>{}, getAuthor=()=>'', rememberAuthor=()=>{}}) {
    this.openDialog = openDialog;
    this.closeDialog = closeDialog;
    this.saveNote = saveNote;
    this.onSaved = onSaved;
    this.getAuthor = getAuthor;
    this.rememberAuthor = rememberAuthor;
    this.subject = '';
    this.pending = null;
    this.item = null;
    this.enabled = false;
    this.saving = false;
    this.title = document.getElementById('galleryContactTitle');
    this.context = document.getElementById('galleryContactContext');
    this.form = document.getElementById('galleryContactForm');
    this.author = this.form?.querySelector('[name="author"]');
    this.confirm = document.getElementById('galleryContactConfirm');
    this.cancelButton = document.getElementById('galleryContactCancel');
    this.message = document.getElementById('galleryContactMessage');
    this.links = ['dial', 'message'].map(action => {
      const link = document.querySelector(`#galleryViewer [data-action="${action}"]`);
      return {action, link};
    });
    this.ready = Boolean(this.title && this.context && this.form && this.author && this.confirm
      && this.cancelButton && this.message && this.links.every(({link}) => link));
    // An older cached shell may briefly load the newer module during an update.
    if (!this.ready) return;
    for (const {action, link} of this.links) {
      link.addEventListener('click', event => this.begin(event, action));
    }
    this.author.required = true;
    this.author.addEventListener('input', () => {
      if (!this.pending || this.saving) return;
      this.pending.author = this.author.value;
      this.persist();
    });
    this.form.addEventListener('submit', event => {
      event.preventDefault();
      void this.submit();
    });
    this.cancelButton.addEventListener('click', event => {
      event.preventDefault();
      this.cancel();
    });
    this.update(null, false);
  }

  storageKey() {
    return 'stats.gallery.contact.' + this.subject;
  }

  configure(subject) {
    if (!this.ready) return;
    const next = String(subject || '');
    if (this.subject === next) return;
    if (this.subject) this.closeDialog();
    this.subject = next;
    this.pending = null;
    this.saving = false;
    this.message.textContent = '';
    this.title.textContent = '';
    this.context.textContent = '';
    this.author.value = '';
    if (next) {
      try {
        const saved = JSON.parse(sessionStorage.getItem(this.storageKey()));
        if (saved?.subject === next && /^[a-f0-9]{64}$/.test(saved.itemId || '')
            && /^[a-f0-9]{32}$/.test(saved.noteId || '') && /^\+?\d+$/.test(saved.phoneDial || '')
            && ['dial', 'message'].includes(saved.action)) this.pending = saved;
      } catch (_) { /* Storage can be unavailable; current-page confirmation still works. */ }
    }
    this.setBusy(false);
    this.refreshLinks();
  }

  persist() {
    if (!this.subject) return;
    try {
      if (this.pending) sessionStorage.setItem(this.storageKey(), JSON.stringify(this.pending));
      else sessionStorage.removeItem(this.storageKey());
    } catch (_) { /* Private browsing must not prevent a native phone action. */ }
  }

  update(item, enabled) {
    // Copy only contact fields: later viewer updates must not retarget an intent.
    this.item = item ? {id:String(item.id || ''), name:String(item.lead_name || ''),
      date:String(item.document_date || ''), phone:String(item.phone || ''),
      phoneDial:String(item.phone_dial || '')} : null;
    this.enabled = Boolean(enabled);
    this.refreshLinks();
  }

  refreshLinks() {
    if (!this.ready) return;
    const available = Boolean(this.subject && this.enabled && /^[a-f0-9]{64}$/.test(this.item?.id || '')
      && /^\+?\d+$/.test(this.item.phoneDial));
    for (const {action, link} of this.links) {
      if (available && !this.saving) {
        link.setAttribute('href', `${action === 'dial' ? 'tel' : 'sms'}:${this.item.phoneDial}`);
        link.removeAttribute('aria-disabled');
        link.tabIndex = 0;
      } else {
        link.removeAttribute('href');
        link.setAttribute('aria-disabled', 'true');
        link.tabIndex = -1;
      }
      link.title = available ? this.item.phone || this.item.phoneDial : 'No phone number available for this card';
    }
  }

  begin(event, action) {
    if (!this.subject || !this.enabled || this.saving || !/^[a-f0-9]{64}$/.test(this.item?.id || '')
        || !/^\+?\d+$/.test(this.item.phoneDial)) {
      event.preventDefault();
      return;
    }
    const noteId = Array.from(crypto.getRandomValues(new Uint8Array(16)),
      value => value.toString(16).padStart(2, '0')).join('');
    this.pending = {subject:this.subject, itemId:this.item.id, name:this.item.name,
      date:this.item.date, phone:this.item.phone || this.item.phoneDial,
      phoneDial:this.item.phoneDial, action, noteId, author:String(this.getAuthor() || '')};
    this.persist();
    // Synchronous preparation leaves the confirmation waiting when the phone
    // app returns. Do not prevent the anchor's native tel:/sms: navigation.
    this.openPending();
  }

  restore() {
    return this.openPending();
  }

  openPending() {
    if (!this.ready || !this.pending || this.pending.subject !== this.subject) return false;
    const called = this.pending.action === 'dial';
    this.title.textContent = called ? 'Called?' : 'Text sent?';
    this.context.textContent = [this.pending.name, this.pending.date, this.pending.phone].filter(Boolean).join(' · ');
    this.confirm.textContent = called ? 'Called' : 'Text sent';
    this.author.value = this.pending.author || '';
    this.message.textContent = '';
    this.setBusy(this.saving);
    this.openDialog();
    return true;
  }

  setBusy(value) {
    if (!this.ready) return;
    this.confirm.disabled = value;
    this.cancelButton.disabled = value;
    this.author.disabled = value;
  }

  cancel() {
    if (!this.ready || !this.pending) return false;
    if (this.saving) return false;
    this.pending = null;
    this.persist();
    this.message.textContent = '';
    this.closeDialog();
    return true;
  }

  async submit() {
    if (!this.ready || this.saving || !this.pending || this.pending.subject !== this.subject) return;
    const author = this.author.value.trim();
    if (!author) {
      this.message.textContent = 'Enter your name.';
      this.author.focus();
      return;
    }
    const pending = this.pending;
    pending.author = author;
    this.persist();
    this.saving = true;
    this.setBusy(true);
    this.refreshLinks();
    this.message.textContent = 'Saving…';
    let result;
    try {
      result = await this.saveNote({itemId:pending.itemId, noteId:pending.noteId, author,
        body:pending.action === 'dial' ? 'Called' : 'Text sent'});
    } catch (error) {
      if (this.pending === pending && this.subject === pending.subject) {
        this.message.textContent = error?.message || 'Could not save. Try again.';
        this.saving = false;
        this.setBusy(false);
        this.refreshLinks();
      }
      return;
    }
    if (this.pending !== pending || this.subject !== pending.subject) return;
    this.pending = null;
    this.persist();
    this.message.textContent = result?.offline ? 'Saved offline' : 'Saved';
    try { this.rememberAuthor(author); } catch (_) { /* Saving the note already succeeded. */ }
    // A rendering failure must never turn a successful note into a retry.
    try { await this.onSaved(pending.itemId, result); } catch (_) { /* Next render can refresh the note. */ }
    if (!this.pending && this.subject === pending.subject) {
      this.saving = false;
      this.setBusy(false);
      this.refreshLinks();
      this.closeDialog();
    }
  }
}
