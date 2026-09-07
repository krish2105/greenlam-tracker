/**
 * Subscribing this device to notifications.
 *
 * THE iOS PROBLEM, STATED PLAINLY
 *
 * Safari on iOS delivers Web Push only to a PWA that has been added to the
 * Home Screen. In a browser tab, `Notification.requestPermission()` does not
 * exist and `PushManager` is absent — not "denied", absent. So an iPhone user
 * who never adds the app to their Home Screen is never alerted, silently, and
 * the maintenance team quietly stops finding out that machines have stopped.
 *
 * That is why `pushSupport()` distinguishes "this browser cannot" from "this
 * iPhone cannot YET": the second one has a fix, and the app has to say what it
 * is rather than showing a disabled switch.
 */

import * as api from './api';

export type PushSupport =
  | 'ready' // subscribing will work
  | 'needs-home-screen' // iOS Safari, not installed. Fixable by the user.
  | 'unsupported' // no service worker or no push at all
  | 'denied'; // the user said no; only they can undo it, in system settings

/** iOS Safari, including iPadOS pretending to be a Mac. */
function isIos(): boolean {
  const ua = navigator.userAgent;
  return (
    /iPad|iPhone|iPod/.test(ua) ||
    // iPadOS 13+ reports a Mac user agent; the touch points give it away.
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  );
}

/** Whether the app is running as an installed PWA rather than in a tab. */
export function isInstalled(): boolean {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    // Safari's own, non-standard flag. It is the only reliable signal on iOS.
    ('standalone' in navigator && (navigator as { standalone?: boolean }).standalone === true)
  );
}

export function pushSupport(): PushSupport {
  if (!('serviceWorker' in navigator)) return 'unsupported';
  if (!('PushManager' in window) || !('Notification' in window)) {
    // On iOS this is exactly what a Safari tab looks like: the APIs are absent
    // rather than refusing. Naming the reason is the difference between a fix
    // the user can act on and a switch that appears broken.
    return isIos() && !isInstalled() ? 'needs-home-screen' : 'unsupported';
  }
  if (Notification.permission === 'denied') return 'denied';
  return 'ready';
}

/**
 * The VAPID public key arrives base64url-encoded and PushManager wants bytes.
 * Not a formality — a wrong conversion produces a subscription that encrypts
 * to nothing and fails silently at send time, hours later.
 */
function keyToBytes(base64url: string): ArrayBuffer {
  const padded = (base64url + '='.repeat((4 - (base64url.length % 4)) % 4))
    .replace(/-/g, '+')
    .replace(/_/g, '/');
  const raw = atob(padded);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  // The buffer, not the view. TypeScript's DOM types accept a BufferSource and
  // a Uint8Array over a SharedArrayBuffer is not one.
  return bytes.buffer;
}

function toJson(sub: PushSubscription): {
  endpoint: string;
  keys: { p256dh: string; auth: string };
} {
  const json = sub.toJSON();
  return {
    endpoint: json.endpoint!,
    keys: { p256dh: json.keys!.p256dh, auth: json.keys!.auth },
  };
}

/**
 * Ask for permission, subscribe, and register the device with the server.
 *
 * Returns false rather than throwing when the user declines — declining is a
 * normal answer, not an error, and treating it as one puts a red banner in
 * front of somebody who simply said no.
 */
export async function enablePush(): Promise<boolean> {
  const status = await api.pushStatus();
  if (!status.enabled || !status.public_key) return false;

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return false;

  const registration = await navigator.serviceWorker.ready;
  // Reuse an existing subscription. Unsubscribing and re-subscribing rotates
  // the endpoint, which orphans the row the server already has.
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({
      // Required by Chrome, and the honest setting anyway: every notification
      // this app sends is one somebody should see.
      userVisibleOnly: true,
      applicationServerKey: keyToBytes(status.public_key),
    }));

  await api.subscribeToPush(toJson(subscription));
  return true;
}

export async function disablePush(): Promise<void> {
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  if (!subscription) return;

  // Server first. If the browser unsubscribes and the network then fails, the
  // server keeps pushing to an endpoint that no longer exists — invisible to
  // the user and slow to notice.
  await api.unsubscribeFromPush(toJson(subscription));
  await subscription.unsubscribe();
}

/** Whether this specific device currently holds a subscription. */
export async function isSubscribedHere(): Promise<boolean> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return false;
  const registration = await navigator.serviceWorker.ready;
  return (await registration.pushManager.getSubscription()) !== null;
}
