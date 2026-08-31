/**
 * The offline outbox.
 *
 * THE RULE THIS EXISTS TO KEEP (CLAUDE.md)
 * "No write ever blocks on the network." An operator standing at a dead press
 * taps submit and gets an answer immediately — the ticket lands in IndexedDB
 * and drains later. Render's free tier cold-starts in 30-60 seconds, so if a
 * write waited on the API the app would feel broken every single morning.
 *
 * WHAT LIVES WHERE
 * Dexie holds the queue and a local mirror of tickets. The ordering, backoff
 * and conflict rules live in `packages/core/src/sync.ts` as pure functions, so
 * the Expo port reuses them and the tests can simulate three devices without a
 * browser.
 *
 * iOS, AND WHY INSTALLING MATTERS
 * Safari evicts script-writable storage — IndexedDB included — after about
 * seven days of no use, for sites that are NOT installed to the home screen.
 * An operator off for a week would lose an unsynced queue. Add-to-Home-Screen
 * is therefore a mandatory training step on iPhone, not a nice-to-have
 * (spec §4.1).
 *
 * NO BACKGROUND SYNC ON iOS
 * There is no Background Sync API there, so draining happens on: app
 * foreground, the `online` event, a timer while the app is open, and
 * immediately after any write. Never assume it runs in the background.
 */

import Dexie, { type Table } from 'dexie';
import {
  backoffMs,
  dueEntries,
  newEventId,
  shouldRetry,
  type OutboxEntry,
  type SyncEvent,
} from '@greenlam/core';

import { ApiError } from './api';

/** One queued write. `id` is the event id, so a retry cannot duplicate a row. */
interface QueuedRow extends OutboxEntry {
  id: string;
  /** Where to POST it. Kept with the entry so replay needs no extra lookup. */
  endpoint: string;
  method: 'POST';
  body: unknown;
}

class OutboxDb extends Dexie {
  queue!: Table<QueuedRow, string>;

  constructor() {
    super('greenlam-outbox');
    // Dexie's versioned migrations matter once updates ship to live devices:
    // a phone that skipped three releases must still open its queue.
    this.version(1).stores({ queue: 'id, status, nextAttemptAt' });
  }
}

const db = new OutboxDb();

type Listener = (pending: number) => void;
const listeners = new Set<Listener>();

async function notify(): Promise<void> {
  const pending = await db.queue.where('status').notEqual('sending').count();
  listeners.forEach((fn) => fn(pending));
}

export function onOutboxChange(fn: Listener): () => void {
  listeners.add(fn);
  void notify();
  return () => listeners.delete(fn);
}

export async function pendingCount(): Promise<number> {
  return db.queue.count();
}

/**
 * Queue a write and return immediately.
 *
 * The caller never awaits the network. A drain is kicked off but deliberately
 * not awaited — that is the whole point.
 */
export async function enqueue(
  endpoint: string,
  body: unknown,
  event: Omit<SyncEvent, 'eventId'> & { eventId?: string },
): Promise<string> {
  const eventId = event.eventId ?? newEventId(Date.now());
  const row: QueuedRow = {
    id: eventId,
    endpoint,
    method: 'POST',
    body: { ...(body as object), event_id: eventId },
    event: { ...event, eventId },
    status: 'pending',
    attempts: 0,
  };
  await db.queue.put(row);
  void notify();
  void drain();
  return eventId;
}

let draining = false;

/**
 * Send everything that is due, oldest first.
 *
 * Single-flight: two concurrent drains would race on the same rows and could
 * send an event twice. Idempotency on the server makes that survivable rather
 * than harmless, and survivable is not a reason to be sloppy.
 */
export async function drain(fetcher = defaultFetcher): Promise<void> {
  if (draining || !navigator.onLine) return;
  draining = true;

  try {
    const all = await db.queue.toArray();
    const due = dueEntries(all, Date.now()) as QueuedRow[];

    for (const row of due) {
      await db.queue.update(row.id, { status: 'sending' });
      void notify();

      try {
        await fetcher(row.endpoint, row.body);
        // Success. Drop it — the server now owns this event, and the local
        // mirror is refreshed from the API rather than from the queue.
        await db.queue.delete(row.id);
      } catch (error) {
        const status = error instanceof ApiError ? error.status : 0;
        const attempts = row.attempts + 1;

        if (!shouldRetry(status)) {
          // A 4xx will never succeed. Retrying it forever would block every
          // event behind it, so it is parked as failed and surfaced instead.
          await db.queue.update(row.id, {
            status: 'failed',
            attempts,
            lastError: error instanceof Error ? error.message : 'rejected',
            nextAttemptAt: undefined,
          });
        } else {
          await db.queue.update(row.id, {
            status: 'failed',
            attempts,
            lastError: error instanceof Error ? error.message : 'network',
            nextAttemptAt: Date.now() + backoffMs(attempts),
          });
          // Stop the pass: the network is down, and hammering it just burns
          // battery on a phone that is already struggling for signal.
          break;
        }
      }
      void notify();
    }
  } finally {
    draining = false;
  }
}

/** Entries a person needs to know about — permanently rejected, not just slow. */
export async function rejected(): Promise<QueuedRow[]> {
  const rows = await db.queue.where('status').equals('failed').toArray();
  return rows.filter((r) => r.nextAttemptAt === undefined);
}

export async function discard(eventId: string): Promise<void> {
  await db.queue.delete(eventId);
  void notify();
}

/** Clears everything. Called on sign-out so a shared tablet carries nothing over. */
export async function clearOutbox(): Promise<void> {
  await db.queue.clear();
  void notify();
}

async function defaultFetcher(endpoint: string, body: unknown): Promise<void> {
  const { postRaw } = await import('./api');
  await postRaw(endpoint, body);
}

/**
 * Triggers, per spec §3.2 — and note what is missing: a background timer.
 * iOS has no Background Sync API, so nothing here fires while the app is shut.
 */
export function startOutbox(): () => void {
  const onOnline = () => void drain();
  const onVisible = () => {
    if (document.visibilityState === 'visible') void drain();
  };

  window.addEventListener('online', onOnline);
  document.addEventListener('visibilitychange', onVisible);
  const timer = window.setInterval(() => void drain(), 5 * 60 * 1000);

  void drain();

  return () => {
    window.removeEventListener('online', onOnline);
    document.removeEventListener('visibilitychange', onVisible);
    window.clearInterval(timer);
  };
}
