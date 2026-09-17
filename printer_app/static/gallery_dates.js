/* Date browsing owns only UI state/gestures. The gallery supplies date buckets
 * for the entire current search/related scope; retrieval stays in gallery.js. */
const el = id => document.getElementById(id);
const label = date => new Date(date + 'T12:00:00').toLocaleDateString('en-US',
  {month:'long', day:'numeric', year:'numeric'});
const monthLabel = month => new Date(month + '-01T12:00:00').toLocaleDateString('en-US',
  {month:'long', year:'numeric'});

export class GalleryDates {
  constructor({onSelect, blocked, openDialog}) {
    this.onSelect = onSelect; this.blocked = blocked; this.openDialog = openDialog;
    this.filter = ''; this.counts = new Map(); this.dates = []; this.undated = 0;
    this.loading = true; this.month = ''; this.gesture = null; this.touches = new Set();
    this.suppressClickUntil = 0;
    el('galleryChooseDate').onclick = () => this.open();
    el('galleryPreviousDate').onclick = () => this.move(-1);
    el('galleryNextDate').onclick = () => this.move(1);
    el('galleryCalendarMonth').onchange = event => { this.month = event.target.value; this.calendar(); };
    let pending = false;
    window.addEventListener('scroll', () => {
      if (pending || this.filter) return;
      pending = true; requestAnimationFrame(() => { pending = false; this.buttons(); });
    }, {passive:true});
    this.gestures(el('galleryMain'));
  }
  setFilter(value) { this.filter = value; this.buttons(); }
  busy(value) { this.loading = value; this.buttons(); }
  update(buckets, filter) {
    this.filter = filter;
    this.counts = new Map((buckets || []).filter(b => b.date).map(b => [b.date, b.count]));
    this.dates = [...this.counts.keys()].sort(); // ISO dates: chronological, no UTC conversion.
    this.undated = (buckets || []).find(b => b.date === null)?.count || 0;
    this.buttons();
  }
  anchor() {
    if (this.filter === 'undated') return '';
    if (this.filter && this.filter !== 'undated') return this.filter;
    const navBottom = el('galleryChooseDate').getBoundingClientRect().bottom;
    for (const group of el('galleryCards').querySelectorAll('.gallery-day')) {
      if (group.dataset.date !== 'undated' && group.getBoundingClientRect().bottom > Math.max(100, navBottom)) {
        return group.dataset.date;
      }
    }
    return this.dates.at(-1) || '';
  }
  neighbor(direction, anchor = this.anchor()) {
    if (!anchor) return '';
    return (direction > 0 ? this.dates.find(date => date > anchor) :
      [...this.dates].reverse().find(date => date < anchor)) || '';
  }
  buttons() {
    el('galleryChooseDate').textContent = (this.filter === 'undated' ? 'Dates need checking' :
      this.filter ? label(this.filter) : 'All dates') + ' ⌄';
    el('galleryChooseDate').disabled = this.loading;
    el('galleryPreviousDate').disabled = this.loading || !this.neighbor(-1);
    el('galleryNextDate').disabled = this.loading || !this.neighbor(1);
  }
  move(direction, anchor) {
    if (this.loading || this.blocked()) return;
    const next = this.neighbor(direction, anchor);
    if (next) this.onSelect(next);
    else el('galleryDateMessage').textContent = this.dates.length ?
      (direction > 0 ? 'You are at the newest available date.' : 'You are at the oldest available date.') :
      'No dated work orders in this view.';
  }
  open(anchor) {
    if (this.loading) return;
    const months = [...new Set(this.dates.map(date => date.slice(0, 7)))].reverse();
    const requested = (anchor && anchor !== 'undated' ? anchor : this.anchor()).slice(0, 7);
    this.month = months.includes(requested) ? requested : (months[0] || '');
    el('galleryCalendarMonth').replaceChildren(...months.map(month => {
      const option = document.createElement('option'); option.value = month; option.textContent = monthLabel(month);
      return option;
    }));
    el('galleryCalendarMonth').value = this.month;
    el('galleryCalendarMonth').disabled = !months.length;
    this.calendar(); this.openDialog('galleryDateSheet');
  }
  calendar() {
    const days = el('galleryCalendarDays'); days.replaceChildren();
    el('galleryCalendarEmpty').hidden = Boolean(this.month);
    if (!this.month) return;
    const [year, month] = this.month.split('-').map(Number);
    const start = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
    const end = new Date(Date.UTC(year, month, 0)).getUTCDate();
    for (let n = 0; n < start; n++) days.append(document.createElement('span'));
    for (let n = 1; n <= end; n++) {
      const date = this.month + '-' + String(n).padStart(2, '0');
      const count = this.counts.get(date) || 0;
      const button = document.createElement('button'); button.type = 'button';
      button.dataset.date = date; button.className = 'gallery-calendar-day'; button.textContent = String(n);
      button.disabled = !count;
      button.setAttribute('aria-label', `${label(date)} — ${count} ${count === 1 ? 'work order' : 'work orders'}`);
      if (date === this.filter) button.setAttribute('aria-current', 'date');
      if (count) { const badge = document.createElement('small'); badge.textContent = String(count); button.append(badge); }
      button.onclick = () => this.onSelect(date); days.append(button);
    }
  }
  gestures(surface) {
    // Only the feed handles swipes. Dialogs, document zoom/pan, form editing and
    // browser-edge navigation keep their normal behavior. No document mutation.
    window.addEventListener('pointerdown', event => {
      if (event.pointerType !== 'touch') return;
      this.touches.add(event.pointerId);
      if (this.touches.size > 1) this.gesture = null;
    }, {capture:true, passive:true});
    const zoomed = () => (window.visualViewport?.scale || 1) > 1.05;
    surface.addEventListener('pointerdown', event => {
      const control = event.target.closest('a,button,input,textarea,select,[contenteditable]');
      this.gesture = null;
      if (event.pointerType !== 'touch' || !event.isPrimary || this.touches.size !== 1 ||
          this.loading || this.blocked() || zoomed() || event.clientX < 24 ||
          event.clientX > window.innerWidth - 24 || (control && !control.matches('.gallery-card'))) return;
      const group = event.target.closest('.gallery-day');
      this.gesture = {id:event.pointerId, x:event.clientX, y:event.clientY, time:performance.now(),
        anchor:group ? (group.dataset.date === 'undated' ? '' : group.dataset.date) : this.anchor()};
    }, {passive:true});
    window.addEventListener('pointermove', event => {
      const g = this.gesture;
      if (!g || g.id !== event.pointerId) return;
      const dx = Math.abs(event.clientX - g.x), dy = Math.abs(event.clientY - g.y);
      if (zoomed() || this.touches.size !== 1 || (dy > 12 && dy >= dx)) this.gesture = null;
    }, {passive:true});
    window.addEventListener('pointerup', event => {
      this.touches.delete(event.pointerId);
      const g = this.gesture;
      if (!g || g.id !== event.pointerId) return;
      this.gesture = null;
      const dx = event.clientX - g.x, dy = event.clientY - g.y;
      if (zoomed() || this.loading || this.blocked() || performance.now() - g.time > 1100 ||
          Math.abs(dx) < Math.max(56, Math.min(120, surface.clientWidth * .15)) || Math.abs(dx) < Math.abs(dy) * 1.6) return;
      this.suppressClickUntil = performance.now() + 500;
      this.move(dx < 0 ? 1 : -1, g.anchor);
    }, {passive:true});
    window.addEventListener('pointercancel', event => {
      this.touches.delete(event.pointerId); this.gesture = null;
    }, {passive:true});
    window.addEventListener('blur', () => { this.touches.clear(); this.gesture = null; });
    surface.addEventListener('click', event => {
      if (event.detail && event.target.closest('.gallery-card') && performance.now() < this.suppressClickUntil) {
        event.preventDefault(); event.stopImmediatePropagation();
      }
    }, true);
  }
}