/**
 * Offline sync: the event reducer and the conflict rules.
 *
 * Pure functions, no DOM, no Dexie, no fetch. The same logic has to produce the
 * same ticket on a phone that has been offline for six hours, on the server
 * when it replays the outbox, and in the nightly export. Three implementations
 * would drift, and the first symptom would be two devices disagreeing about
 * whether a press is still down.
 *
 * WHY EVENT SOURCING AT ALL (spec §3.2)
 * Two devices acting on the same ticket offline produce two EVENTS, not two
 * conflicting writes. Both survive, both are visible in the audit trail, and
 * the state is whatever replaying them in server order says it is.
 *
 * THE FOUR RULES
 *   1. IDEMPOTENT — `event_id` is client-generated and unique. A retry over a
 *      flaky connection is a no-op, so an unreliable network stops being a
 *      correctness problem and becomes merely slow.
 *   2. FORWARD ONLY — stages never move backwards, except an explicit
 *      REOPENED. A late-arriving ACKNOWLEDGED cannot un-close a ticket.
 *   3. DUPLICATE TRANSITIONS ARE RECORDED, NOT REJECTED — first by server
 *      order wins; the second becomes a NOOP that stays in the log. Two
 *      technicians acknowledging the same ticket offline is a thing that
 *      happened, not an error.
 *   4. TEXT IS LAST-WRITE-WINS by `server_received_at`, with the prior value
 *      still readable in the event history.
 *
 * CLOCK SKEW
 * Phones on a factory floor have wrong clocks. `client_ts` is what the user
 * experienced and drives display; `server_received_at` is authoritative for
 * ordering. Never sort state resolution by client time — a phone an hour fast
 * would silently win every conflict.
 */

import { CLOSED_STAGE } from './domain';

export const SYNC_EVENT_TYPES = [
  'RAISED',
  'ACKNOWLEDGED',
  'MATERIAL_RECORDED',
  'REPAIR_STARTED',
  'RESOLVED',
  'DIAGNOSED',
  'CLOSED',
  'REOPENED',
  'NOOP',
] as const;

export type SyncEventType = (typeof SYNC_EVENT_TYPES)[number];

/** Which stage each event moves a ticket to. */
export const STAGE_FOR_EVENT: Record<Exclude<SyncEventType, 'NOOP'>, number> = {
  RAISED: 0,
  ACKNOWLEDGED: 1,
  MATERIAL_RECORDED: 2,
  REPAIR_STARTED: 3,
  RESOLVED: 4,
  DIAGNOSED: 5,
  CLOSED: 6,
  REOPENED: 3,
};

export interface SyncEvent {
  eventId: string;
  ticketId: string;
  type: SyncEventType;
  actorId: number | null;
  deviceId: string;
  /** What the user's device believed. Display only. */
  clientTs: string;
  /** Authoritative for ordering. Absent until the server has seen it. */
  serverReceivedAt?: string | null;
  payload?: Record<string, unknown>;
}

export interface TicketState {
  ticketId: string;
  currentStage: number;
  reopenCount: number;
  ackedAt: string | null;
  resolvedAt: string | null;
  closedAt: string | null;
  immediateCorrection: string | null;
  why1: string | null;
  why2: string | null;
  why3: string | null;
  preventiveAction: string | null;
  rating: number | null;
  /** Events that arrived but changed nothing. Kept for the audit trail. */
  noopEventIds: string[];
  appliedEventIds: string[];
}

export function emptyTicketState(ticketId: string): TicketState {
  return {
    ticketId,
    currentStage: 0,
    reopenCount: 0,
    ackedAt: null,
    resolvedAt: null,
    closedAt: null,
    immediateCorrection: null,
    why1: null,
    why2: null,
    why3: null,
    preventiveAction: null,
    rating: null,
    noopEventIds: [],
    appliedEventIds: [],
  };
}

/**
 * Deterministic ordering.
 *
 * Server time first. Events the server has not seen yet sort last, in client
 * order, so an offline device can still show a sensible optimistic state — but
 * the moment the server assigns times, its order wins.
 *
 * `eventId` breaks exact ties. UUIDv7 sorts by creation time, so this is a
 * stable, meaningful tiebreak rather than an arbitrary one.
 */
export function orderEvents(events: SyncEvent[]): SyncEvent[] {
  return [...events].sort((a, b) => {
    const aServer = a.serverReceivedAt;
    const bServer = b.serverReceivedAt;
    if (aServer && bServer) {
      if (aServer !== bServer) return aServer < bServer ? -1 : 1;
      return a.eventId < b.eventId ? -1 : 1;
    }
    if (aServer) return -1; // acknowledged events precede pending ones
    if (bServer) return 1;
    if (a.clientTs !== b.clientTs) return a.clientTs < b.clientTs ? -1 : 1;
    return a.eventId < b.eventId ? -1 : 1;
  });
}

function text(payload: Record<string, unknown> | undefined, key: string): string | null {
  const value = payload?.[key];
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

/**
 * Fold one event into a ticket.
 *
 * Returns the state unchanged (plus a NOOP record) when the event does not
 * advance anything — which is how duplicate transitions stay visible without
 * corrupting state.
 */
export function applyEvent(state: TicketState, event: SyncEvent): TicketState {
  // Rule 1: idempotency. Seeing the same event twice must change nothing at
  // all — not even the noop list, or a retry loop would grow it forever.
  if (
    state.appliedEventIds.includes(event.eventId) ||
    state.noopEventIds.includes(event.eventId)
  ) {
    return state;
  }

  if (event.type === 'NOOP') {
    return { ...state, noopEventIds: [...state.noopEventIds, event.eventId] };
  }

  const target = STAGE_FOR_EVENT[event.type];

  // Rule 2 and 3. REOPENED is the one sanctioned backwards move; everything
  // else that does not advance the stage is recorded and discarded.
  if (event.type !== 'REOPENED' && target <= state.currentStage) {
    return { ...state, noopEventIds: [...state.noopEventIds, event.eventId] };
  }

  const next: TicketState = {
    ...state,
    appliedEventIds: [...state.appliedEventIds, event.eventId],
  };
  const at = event.serverReceivedAt ?? event.clientTs;

  switch (event.type) {
    case 'RAISED':
      next.currentStage = 0;
      break;
    case 'ACKNOWLEDGED':
      next.currentStage = 1;
      next.ackedAt = at;
      break;
    case 'MATERIAL_RECORDED':
      next.currentStage = 2;
      break;
    case 'REPAIR_STARTED':
      next.currentStage = 3;
      break;
    case 'RESOLVED':
      next.currentStage = 4;
      next.resolvedAt = at;
      // Rule 4: last write wins, and because events are applied in server
      // order, "last" is simply the one applied most recently.
      next.immediateCorrection =
        text(event.payload, 'immediate_correction') ?? next.immediateCorrection;
      break;
    case 'DIAGNOSED':
      next.currentStage = 5;
      next.why1 = text(event.payload, 'why_1') ?? next.why1;
      next.why2 = text(event.payload, 'why_2') ?? next.why2;
      next.why3 = text(event.payload, 'why_3') ?? next.why3;
      next.preventiveAction =
        text(event.payload, 'preventive_action') ?? next.preventiveAction;
      break;
    case 'CLOSED': {
      next.currentStage = CLOSED_STAGE;
      next.closedAt = at;
      const rating = event.payload?.rating;
      next.rating = typeof rating === 'number' ? rating : next.rating;
      break;
    }
    case 'REOPENED':
      next.currentStage = 3;
      next.reopenCount = state.reopenCount + 1;
      // The machine is down again, so the previous conclusion no longer holds.
      // The old values remain in the event history.
      next.resolvedAt = null;
      next.closedAt = null;
      next.rating = null;
      break;
  }

  return next;
}

/** Replay a ticket from scratch. The server's state is always this function. */
export function replay(ticketId: string, events: SyncEvent[]): TicketState {
  return orderEvents(events).reduce(applyEvent, emptyTicketState(ticketId));
}

// ---------------------------------------------------------------------------
// Outbox
// ---------------------------------------------------------------------------

export type OutboxStatus = 'pending' | 'sending' | 'failed';

export interface OutboxEntry {
  event: SyncEvent;
  status: OutboxStatus;
  attempts: number;
  lastError?: string;
  nextAttemptAt?: number;
}

/**
 * Exponential backoff with a cap, in milliseconds.
 *
 * 2s, 4s, 8s … capped at five minutes. Long enough that a sleeping Render
 * instance gets time to wake, short enough that a technician who walks back
 * into signal sees their queue drain rather than waiting out a long timer.
 */
export function backoffMs(attempts: number): number {
  return Math.min(2000 * 2 ** Math.max(0, attempts - 1), 300_000);
}

export function isDue(entry: OutboxEntry, now: number): boolean {
  if (entry.status === 'sending') return false;
  if (entry.nextAttemptAt === undefined) return true;
  return entry.nextAttemptAt <= now;
}

/**
 * Which entries to send, in order.
 *
 * Ordering matters more than it looks: events for the same ticket must go in
 * the order they were created, or the server replays an ACKNOWLEDGED after a
 * RESOLVED and records a NOOP for work that actually happened.
 */
export function dueEntries(entries: OutboxEntry[], now: number): OutboxEntry[] {
  return entries
    .filter((e) => isDue(e, now))
    .sort((a, b) =>
      a.event.clientTs === b.event.clientTs
        ? a.event.eventId < b.event.eventId
          ? -1
          : 1
        : a.event.clientTs < b.event.clientTs
          ? -1
          : 1,
    );
}

/**
 * Classify a failed send.
 *
 * The distinction that matters: a 4xx will never succeed no matter how many
 * times it is retried, so retrying it forever blocks every event behind it in
 * the queue. A 5xx or a dropped connection is worth retrying indefinitely —
 * that is exactly the flaky-plant-wifi case this whole system exists for.
 */
export function shouldRetry(status: number): boolean {
  if (status === 0) return true; // no connection at all
  if (status === 408 || status === 429) return true;
  if (status >= 500) return true;
  return false;
}

/** UUIDv7-shaped id: time-ordered, generated offline, no server round trip. */
export function newEventId(now: number, random: () => number = Math.random): string {
  const ms = Math.floor(now).toString(16).padStart(12, '0');
  const hex = (n: number) =>
    Array.from({ length: n }, () => Math.floor(random() * 16).toString(16)).join('');
  // Version 7, RFC 4122 variant.
  return [
    ms.slice(0, 8),
    ms.slice(8, 12),
    `7${hex(3)}`,
    ((8 + Math.floor(random() * 4)).toString(16) + hex(3)).slice(0, 4),
    hex(12),
  ].join('-');
}
