const CACHE = 'stats-gallery-shell-v13';
const IMAGE_CACHE = 'stats-gallery-images-v1';
const SHELL = [
  '/gallery/',
  '/gallery/manifest.webmanifest',
  '/static/gallery.css',
  '/static/gallery.js',
  '/static/gallery_dates.js',
  '/static/gallery_focus.js',
  '/static/gallery_navigation.js',
  '/static/gallery_network.js',
  '/static/gallery_contact.js',
  '/static/gallery_offline.js'
];

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await Promise.allSettled(SHELL.map(async url => {
      const response = await fetch(url, {credentials:'same-origin'});
      if (response.ok) await cache.put(url, response.clone());
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith('stats-gallery-shell-') && name !== CACHE)
      .map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/gallery/offline-image/')) {
    event.respondWith((async () => {
      const cache = await caches.open(IMAGE_CACHE);
      return (await cache.match(event.request)) || new Response('', {status:404});
    })());
    return;
  }
  if (event.request.mode === 'navigate' && url.pathname.startsWith('/gallery')) {
    event.respondWith((async () => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2200);
      try {
        const response = await fetch(event.request, {signal:controller.signal});
        if (response.ok && (url.pathname === '/gallery' || url.pathname === '/gallery/')) {
          const cache = await caches.open(CACHE);
          await cache.put('/gallery/', response.clone());
        }
        return response;
      } catch (_) {
        return (await caches.match('/gallery/')) || Response.error();
      } finally {
        clearTimeout(timer);
      }
    })());
    return;
  }
  if (SHELL.includes(url.pathname)) {
    event.respondWith((async () => {
      const cached = await caches.match(url.pathname);
      if (cached) return cached;
      const response = await fetch(event.request);
      if (response.ok) {
        const cache = await caches.open(CACHE);
        await cache.put(url.pathname, response.clone());
      }
      return response;
    })());
  }
});
