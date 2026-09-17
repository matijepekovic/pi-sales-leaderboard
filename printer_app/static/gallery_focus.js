/** Owns the current fully visible card; modal actions pin their own record. */
export class GalleryFocus {
  constructor({container, blocked, onChange}) {
    this.container = container;
    this.blocked = blocked;
    this.onChange = onChange;
    this.frame = null;
    this.current = null;
    this.schedule = () => {
      if (this.frame === null) this.frame = requestAnimationFrame(() => {
        this.frame = null; this.refresh();
      });
    };
    window.addEventListener('scroll', this.schedule, {passive:true});
    window.addEventListener('resize', this.schedule, {passive:true});
    window.visualViewport?.addEventListener('scroll', this.schedule, {passive:true});
    window.visualViewport?.addEventListener('resize', this.schedule, {passive:true});
    container.addEventListener('load', this.schedule, true);
    this.observer = new ResizeObserver(this.schedule);
    this.observer.observe(container);
  }
  refresh() {
    if (this.blocked()) return;
    const viewport = window.visualViewport;
    let top = viewport?.offsetTop || 0;
    let bottom = top + (viewport?.height || window.innerHeight);
    const nav = document.querySelector('.gallery-date-nav')?.getBoundingClientRect();
    if (nav && nav.top <= top + 2 && nav.bottom > top) top = nav.bottom;
    // Sticky date headings and the floating dock obscure parts of the viewport.
    document.querySelectorAll('.gallery-day-heading').forEach(node => {
      const rect = node.getBoundingClientRect();
      if (rect.top <= top + 4 && rect.bottom > top) top = rect.bottom;
    });
    const dock = document.querySelector('body > .gallery-dock')?.getBoundingClientRect();
    if (dock && dock.top < bottom && dock.bottom > top) bottom = dock.top - 6;
    const middle = (top + bottom) / 2;
    let id = null, distance = Infinity;
    for (const node of this.container.querySelectorAll('.gallery-card')) {
      const rect = node.getBoundingClientRect();
      const image = node.querySelector('img');
      if (!image?.complete || !image.naturalWidth || rect.top < top - 1 || rect.bottom > bottom + 1) continue;
      const d = Math.abs((rect.top + rect.bottom) / 2 - middle);
      if (d < distance) { distance = d; id = node.dataset.id; }
    }
    if (id !== this.current) { this.current = id; this.onChange(id); }
    return id;
  }
  reset() { this.current = undefined; this.schedule(); }
}
