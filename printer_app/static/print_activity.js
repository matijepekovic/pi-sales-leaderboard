'use strict';
(() => {
  const root = document.getElementById('printActivity');
  if (!root) return;
  const content = document.getElementById('printActivityContent');
  const status = document.getElementById('printActivityLive');
  let timer, pending = false;

  async function refresh() {
    clearTimeout(timer);
    if (pending || document.hidden) return;
    pending = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(root.dataset.url, {
        headers: {'Accept': 'text/html'}, cache: 'no-store', signal: controller.signal,
      });
      if (response.status === 401 || response.redirected) {
        status.textContent = 'Sign in again to see current print results.';
        return;
      }
      if (!response.ok) throw new Error('Print results unavailable');
      const html = await response.text();
      const documentFragment = new DOMParser().parseFromString(html, 'text/html');
      const active = content.contains(document.activeElement) ? document.activeElement : null;
      const nextFocus = active && [...documentFragment.querySelectorAll('a')].find(link =>
        link.getAttribute('href') === active.getAttribute('href') && link.textContent === active.textContent);
      if (active && !nextFocus) {
        status.textContent = 'Updates paused while this print link is selected.';
        return;
      }
      const scroll = content.querySelector('.print-activity-list')?.scrollTop || 0;
      content.replaceChildren(...documentFragment.body.childNodes);
      nextFocus?.focus({preventScroll: true});
      const list = content.querySelector('.print-activity-list');
      if (list) list.scrollTop = scroll;
      status.textContent = 'Updated ' + new Date().toLocaleTimeString() + ' · every 5 seconds';
    } catch (_) {
      status.textContent = 'Live updates unavailable. Showing the last known results; retrying…';
    } finally {
      clearTimeout(timeout);
      pending = false;
      if (!document.hidden) timer = setTimeout(refresh, 5000);
    }
  }
  document.addEventListener('visibilitychange', () => {
    clearTimeout(timer);
    if (!document.hidden) refresh();
  });
  content.addEventListener('focusout', () => {
    if (status.textContent.startsWith('Updates paused')) {
      clearTimeout(timer);
      timer = setTimeout(refresh, 0);
    }
  });
  window.addEventListener('pagehide', () => clearTimeout(timer));
  window.addEventListener('pageshow', () => { if (!pending) refresh(); });
})();
