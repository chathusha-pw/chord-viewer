// Network first so edits show up immediately; cached copies keep the app
// working with no signal on stage. All songs are cached at install.
const CACHE = "chord-viewer-v1";
const SHELL = [
  "./", "index.html", "css/style.css", "js/app.js", "js/chords.js", "js/chordpro.js",
  "js/render.js", "manifest.json", "icon.svg", "songs/index.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(SHELL);
    try {
      const songs = await (await fetch("songs/index.json")).json();
      await cache.addAll(songs.map((s) => `songs/${s.file}`));
    } catch {
      /* songs are cached as they are opened instead */
    }
    self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const response = await fetch(event.request);
      if (response.ok || response.type === "opaque") cache.put(event.request, response.clone());
      return response;
    } catch {
      const cached = await cache.match(event.request, { ignoreSearch: true });
      if (cached) return cached;
      throw new Error(`Offline and not cached: ${event.request.url}`);
    }
  })());
});
