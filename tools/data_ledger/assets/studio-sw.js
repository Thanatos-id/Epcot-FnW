// The Studio's service worker. It exists for two reasons, and caching for
// speed is not one of them:
//
//   1. Chrome offers "Install" for a page that has one, which is what turns
//      the Studio into a standalone app with its own window and Dock icon.
//   2. When the server is down - localhost:8123 not running, or no network -
//      the app still opens, from the last copy it saw. Edits live in the
//      browser's own storage either way, so nothing is lost.
//
// Network first, always. Every launch and every reload asks the server for
// the current studio.html, so a rebuild (or, for the GitHub Pages copy, a
// merge to main) is what the app shows next time it opens. The cache is
// only ever the fallback, never the answer while the server can be reached.
//
// Registered with scope "./studio", so it sees the Studio's own files and
// nothing else: the ledger and the survey are served exactly as before.

const CACHE = 'epcot-studio-shell-v1';
const SHELL = ['studio.html', 'studio.webmanifest'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .catch(() => {})
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k.startsWith('epcot-studio-') && k !== CACHE).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  // Map tiles, fonts and Leaflet come from other hosts and go straight there.
  if (new URL(request.url).origin !== self.location.origin) return;

  event.respondWith(
    // `no-cache` revalidates with the server rather than trusting the HTTP
    // cache, so a rebuilt page is never hidden behind a stale copy.
    fetch(request, { cache: 'no-cache' })
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request, { ignoreSearch: true }))
  );
});
