/* Service worker: офлайн-доступ и установка сайта как приложения.
   Работает только на localhost или по HTTPS — так устроены браузеры. */
'use strict';

const CACHE = 'umpk-v2';
const SHELL = [
  './',
  'index.html',
  'styles.css?v=2',
  'app.js?v=2',
  'manifest.webmanifest',
  'assets/logo.png',
  'assets/favicon.png',
  'assets/icon-192.png',
  'assets/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Картинки почти не меняются — отдаём из кэша сразу.
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.match(request).then((hit) => hit || fetchAndStore(request))
    );
    return;
  }

  // Остальное — сначала сеть, кэш только как запасной вариант,
  // иначе после обновления сайта у людей осталась бы старая версия.
  event.respondWith(
    fetchAndStore(request).catch(() =>
      caches.match(request).then((hit) => hit || caches.match('index.html'))
    )
  );
});

function fetchAndStore(request) {
  return fetch(request).then((response) => {
    if (response && response.ok && response.type === 'basic') {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(request, copy));
    }
    return response;
  });
}
