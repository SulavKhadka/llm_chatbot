const CACHE_NAME = 'chat-viewer-v2';
const ASSETS = [
  '/',
  '/static/scripts.js',
  '/static/manifest.json',
  '/static/icons/152.png',
  '/static/icons/167.png',
  '/static/icons/180.png',
  '/static/icons/192.png',
  '/static/icons/512.png',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Caching assets');
        return cache.addAll(ASSETS);
      })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME)
            .map(key => caches.delete(key))
      );
    })
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