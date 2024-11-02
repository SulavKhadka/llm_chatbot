const CACHE_NAME = 'chat-viewer-v1';
const ASSETS = [
  '/',
  '/static/scripts.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(ASSETS))
  );
});

self.addEventListener('fetch', event => {
  // Network-first strategy for API calls
  if (event.request.url.includes('/api/') || 
      event.request.url.includes('/chat/') || 
      event.request.url.includes('/message/')) {
    event.respondWith(
      fetch(event.request)
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Cache-first strategy for static assets
  event.respondWith(
    caches.match(event.request)
      .then(response => response || fetch(event.request))
  );
}); 