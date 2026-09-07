/*
 * Push handling, imported into the generated service worker.
 *
 * A separate file because the PWA plugin runs in `generateSW` mode: Workbox
 * writes the whole service worker, and the supported way to add behaviour to
 * it is `importScripts`. Switching to `injectManifest` to get one event
 * handler would mean owning the precache, the navigation fallback and the
 * update strategy by hand — four things that currently work.
 *
 * TWO HANDLERS, AND WHY THE SECOND ONE IS NOT OPTIONAL
 *
 * `push` shows the notification. `notificationclick` is what makes it useful:
 * without it, tapping an alert about a stopped press opens a new tab at the
 * home screen, and the technician navigates to the ticket by hand while
 * standing next to the machine.
 */

self.addEventListener('push', (event) => {
  // A push with no payload is still worth showing. Chrome will show its own
  // generic "This site has been updated in the background" if a service worker
  // receives a push and shows nothing, which is worse than a vague message of
  // our own.
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = {};
  }

  const title = payload.title || 'Greenlam Tracker';
  event.waitUntil(
    self.registration.showNotification(title, {
      body: payload.body || '',
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      // Same tag replaces rather than stacks. Four alerts about one machine is
      // how a lock screen becomes something people clear without reading.
      tag: payload.tag || 'greenlam',
      renotify: true,
      // A stopped press should buzz. Android silences a notification that
      // arrives while the app is in the foreground unless this is set.
      requireInteraction: false,
      data: { url: payload.url || '/floor/maintenance' },
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      // Reuse an open window rather than piling up tabs. Somebody who gets six
      // alerts in a shift should still have one app open at the end of it.
      for (const client of windows) {
        if ('focus' in client) {
          client.navigate(target);
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});
