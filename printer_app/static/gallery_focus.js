/** Owns visible-card selection. Tall documents do not have to fit the viewport. */
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
    if (this.blocked()) return this.current;
    const viewport = window.visualViewport;
    let top = viewport?.offsetTop || 0;
    let bottom = top + (viewport?.height || window.innerHeight);
    const nav = document.querySelector('.gallery-date-nav')?.getBoundingClientRect();
    if (nav && nav.top <= top + 2 && nav.bottom > top) top = nav.bottom;
    document.querySelectorAll('.gallery-day-heading').forEach(node => {
      const rect = node.getBoundingClientRect();
      if (rect.height && rect.top <= top + 4 && rect.bottom > top) top = rect.bottom;
    });
    const dock = document.querySelector('body > .gallery-dock')?.getBoundingClientRect();
    if (dock && dock.top < bottom && dock.bottom > top) bottom = dock.top - 6;
    const left = viewport?.offsetLeft || 0;
    const right = left + (viewport?.width || window.innerWidth);
    const middle = (top + bottom) / 2;
    let id = null, area = 0, distance = Infinity;
    for (const node of this.container.querySelectorAll('.gallery-card')) {
      const rect = node.getBoundingClientRect(), image = node.querySelector('img');
      if (!image?.complete || !image.naturalWidth) continue;
      const visible = Math.max(0, Math.min(bottom, rect.bottom) - Math.max(top, rect.top));
      const width = Math.max(0, Math.min(right, rect.right) - Math.max(left, rect.left));
      const score = visible * width, d = Math.abs((rect.top + rect.bottom)/2 - middle);
      if (!score) continue;
      // Stable ties avoid flickering at the boundary between adjacent cards.
      const tie = Math.abs(score-area) <= Math.max(1,width*2);
      if (score > area && !tie || tie && (node.dataset.id === this.current || id !== this.current && d < distance)) {
        area = score; distance = d; id = node.dataset.id;
      }
    }
    if (id !== this.current) { this.current = id; this.onChange(id); }
    return id;
  }
  reset() { this.current = undefined; this.schedule(); }
}
