/** Owns visible-card selection. The topmost card below the sticky UI is active. */
export class GalleryFocus {
  constructor({container, blocked, onChange}) {
    this.container = container;
    this.blocked = blocked;
    this.onChange = onChange;
    this.frame = null;
    this.current = null;
    this.observed = new Set();
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
    // Geometry changes caused by scrolling are browser-observed rather than assumed
    // to emit a particular window event. This keeps programmatic/mobile scrolling
    // and filter replacement on the same focus contract.
    this.intersections = new IntersectionObserver(this.schedule, {
      root: null,
      threshold: [0, .01, .25, .5, .75, .99, 1],
    });
    this.mutations = new MutationObserver(() => {
      this.syncObserved();
      this.schedule();
    });
    this.mutations.observe(container, {childList:true, subtree:true});
    this.syncObserved();
  }
  syncObserved() {
    const cards = new Set(this.container.querySelectorAll('.gallery-card'));
    for (const node of this.observed) {
      if (!cards.has(node)) { this.intersections.unobserve(node); this.observed.delete(node); }
    }
    for (const node of cards) {
      if (!this.observed.has(node)) { this.intersections.observe(node); this.observed.add(node); }
    }
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
    let id = null;
    // Reading order owns focus: keep the earlier card active for as long as any of
    // it remains visible below the sticky header. Once it has actually scrolled
    // past that boundary, the next visible card becomes active. This is reversible
    // in both scroll directions and works for cards taller than the viewport.
    for (const node of this.container.querySelectorAll('.gallery-card')) {
      const rect = node.getBoundingClientRect();
      const horizontal = Math.max(0, Math.min(right, rect.right) - Math.max(left, rect.left));
      if (!horizontal) continue;
      if (rect.bottom > top + 1 && rect.top < bottom - 1) {
        id = node.dataset.id;
        break;
      }
    }
    if (id !== this.current) { this.current = id; this.onChange(id); }
    return id;
  }
  reset() { this.current = undefined; this.syncObserved(); this.schedule(); }
}
