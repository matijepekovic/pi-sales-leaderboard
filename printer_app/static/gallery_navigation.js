/** Gallery-local history: serializable view positions, never document data or IO. */
export class GalleryNavigation {
  constructor({capture, restore, changed}) {
    this.capture = capture; this.restore = restore; this.changed = changed;
    this.restoring = false; this.pending = Promise.resolve();
    const state = history.state?.gallery;
    this.depth = state?.depth || 0;
    history.scrollRestoration = 'manual';
    if (!state) this.save();
    window.addEventListener('popstate', event => {
      const entry = event.state?.gallery;
      if (!entry) return; // Do not hijack navigation outside this gallery.
      this.pending = this.pending.then(async () => {
        this.restoring = true; this.depth = entry.depth;
        try { await this.restore(entry.view); }
        finally { this.restoring = false; this.changed(this.depth); }
      }).catch(() => { this.restoring = false; this.changed(this.depth); });
    });
  }
  save() {
    if (this.restoring) return;
    history.replaceState({gallery:{depth:this.depth, view:this.capture()}}, '');
  }
  push() {
    if (this.restoring) return;
    this.depth++;
    history.pushState({gallery:{depth:this.depth, view:this.capture()}}, '');
    this.changed(this.depth);
  }
  back() {
    // Only our own pushed entries expose an in-app Back button.
    if (this.depth > 0 && !this.restoring) { this.save(); history.back(); }
  }
}
