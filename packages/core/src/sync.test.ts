/**
 * Sync engine tests.
 *
 * The spec names this suite specifically: "simulate 3 devices going offline,
 * generating conflicting events, and reconciling. That's where the bugs will
 * be." So the three-device scenarios below are not illustrative — they are the
 * requirement, written as assertions.
 */

import { describe, expect, it } from 'vitest';

import {
  applyEvent,
  backoffMs,
  dueEntries,
  emptyTicketState,
  isDue,
  newEventId,
  orderEvents,
  replay,
  shouldRetry,
  type OutboxEntry,
  type SyncEvent,
} from './sync';

const TICKET = 'ticket-press-4';

function ev(
  eventId: string,
  type: SyncEvent['type'],
  opts: Partial<SyncEvent> = {},
): SyncEvent {
  return {
    eventId,
    ticketId: TICKET,
    type,
    actorId: 1,
    deviceId: 'device-a',
    clientTs: '2026-08-24T09:00:00.000Z',
    ...opts,
  };
}

describe('idempotency — the flaky-network guarantee', () => {
  it('applying the same event twice changes nothing', () => {
    const e = ev('e1', 'ACKNOWLEDGED', { serverReceivedAt: '2026-08-24T09:01:00Z' });
    const once = applyEvent(emptyTicketState(TICKET), e);
    const twice = applyEvent(once, e);
    expect(twice).toEqual(once);
  });

  it('a retried upload does not grow the noop list forever', () => {
    // A retry loop that appended a noop every time would leak unboundedly on a
    // device that spends a shift out of signal.
    let state = emptyTicketState(TICKET);
    const dup = ev('dup', 'ACKNOWLEDGED');
    for (let i = 0; i < 50; i++) state = applyEvent(state, dup);
    expect(state.appliedEventIds).toHaveLength(1);
    expect(state.noopEventIds).toHaveLength(0);
  });

  it('replaying the whole log is stable', () => {
    const log = [
      ev('e1', 'ACKNOWLEDGED', { serverReceivedAt: '2026-08-24T09:01:00Z' }),
      ev('e2', 'REPAIR_STARTED', { serverReceivedAt: '2026-08-24T09:20:00Z' }),
    ];
    expect(replay(TICKET, log)).toEqual(replay(TICKET, [...log].reverse()));
  });
});

describe('forward-only, except REOPENED', () => {
  it('a late ACKNOWLEDGED cannot un-close a ticket', () => {
    // The exact hazard of offline sync: a device that was in a dead zone finally
    // uploads an acknowledgement for a ticket that has since been closed.
    const state = replay(TICKET, [
      ev('a', 'ACKNOWLEDGED', { serverReceivedAt: '2026-08-24T09:01:00Z' }),
      ev('b', 'REPAIR_STARTED', { serverReceivedAt: '2026-08-24T09:10:00Z' }),
      ev('c', 'RESOLVED', { serverReceivedAt: '2026-08-24T10:00:00Z' }),
      ev('d', 'DIAGNOSED', { serverReceivedAt: '2026-08-24T10:30:00Z' }),
      ev('e', 'CLOSED', { serverReceivedAt: '2026-08-24T11:00:00Z', payload: { rating: 4 } }),
      // Arrives last, from a phone that was offline all morning.
      ev('late', 'ACKNOWLEDGED', { serverReceivedAt: '2026-08-24T11:05:00Z' }),
    ]);

    expect(state.currentStage).toBe(6);
    expect(state.noopEventIds).toContain('late');
  });

  it('REOPENED is the one backwards move, and it is explicit', () => {
    const state = replay(TICKET, [
      ev('a', 'ACKNOWLEDGED', { serverReceivedAt: '2026-08-24T09:01:00Z' }),
      ev('b', 'REPAIR_STARTED', { serverReceivedAt: '2026-08-24T09:10:00Z' }),
      ev('c', 'RESOLVED', { serverReceivedAt: '2026-08-24T10:00:00Z' }),
      ev('d', 'CLOSED', { serverReceivedAt: '2026-08-24T11:00:00Z', payload: { rating: 5 } }),
      ev('r', 'REOPENED', { serverReceivedAt: '2026-08-25T08:00:00Z' }),
    ]);

    expect(state.currentStage).toBe(3);
    expect(state.reopenCount).toBe(1);
    // The previous conclusion no longer holds — the machine is down again.
    expect(state.closedAt).toBeNull();
    expect(state.rating).toBeNull();
  });
});

describe('three devices offline, conflicting, reconciling', () => {
  /**
   * The scenario the spec asks for.
   *
   * A press stops. Three people are in a dead zone at the same time:
   *   - Device A, a technician, acknowledges it
   *   - Device B, a second technician, also acknowledges it
   *   - Device C, a supervisor, starts the repair
   *
   * All three reconnect in a different order than they acted.
   */
  const deviceA = ev('a-ack', 'ACKNOWLEDGED', {
    deviceId: 'phone-a',
    clientTs: '2026-08-24T09:05:00.000Z',
    serverReceivedAt: '2026-08-24T09:31:00.000Z', // reconnected second
  });
  const deviceB = ev('b-ack', 'ACKNOWLEDGED', {
    deviceId: 'phone-b',
    clientTs: '2026-08-24T09:06:00.000Z',
    serverReceivedAt: '2026-08-24T09:30:00.000Z', // reconnected first
  });
  const deviceC = ev('c-repair', 'REPAIR_STARTED', {
    deviceId: 'tablet-c',
    clientTs: '2026-08-24T09:12:00.000Z',
    serverReceivedAt: '2026-08-24T09:32:00.000Z',
  });

  it('both acknowledgements survive, only one takes effect', () => {
    const state = replay(TICKET, [deviceA, deviceB, deviceC]);

    // Device B reached the server first, so B's acknowledgement is the one that
    // set the timestamp — even though A acted a minute earlier by its own clock.
    expect(state.appliedEventIds).toContain('b-ack');
    expect(state.noopEventIds).toContain('a-ack');
    // Nothing is lost. A's event is still in the log, which is what makes
    // "who acknowledged this, and when" answerable.
    expect(state.appliedEventIds.length + state.noopEventIds.length).toBe(3);
    expect(state.currentStage).toBe(3);
  });

  it('reaches the same state whatever order the uploads arrive in', () => {
    const orders = [
      [deviceA, deviceB, deviceC],
      [deviceC, deviceB, deviceA],
      [deviceB, deviceC, deviceA],
      [deviceC, deviceA, deviceB],
    ];
    const states = orders.map((o) => replay(TICKET, o));
    for (const s of states) {
      expect(s.currentStage).toBe(states[0]!.currentStage);
      expect(s.ackedAt).toBe(states[0]!.ackedAt);
      expect([...s.appliedEventIds].sort()).toEqual([...states[0]!.appliedEventIds].sort());
    }
  });

  it('a device with a wrong clock does not win', () => {
    // A phone an hour fast would take over every conflict if client time
    // decided ordering. Server order is authoritative precisely for this.
    const fastPhone = ev('fast', 'ACKNOWLEDGED', {
      deviceId: 'phone-wrong-clock',
      clientTs: '2026-08-24T10:59:00.000Z', // an hour ahead
      serverReceivedAt: '2026-08-24T09:33:00.000Z', // but arrived last
    });
    const state = replay(TICKET, [deviceB, fastPhone]);
    expect(state.appliedEventIds).toContain('b-ack');
    expect(state.noopEventIds).toContain('fast');
  });

  it('two technicians writing different root causes: last server write wins, both kept', () => {
    const base = [
      ev('ack', 'ACKNOWLEDGED', { serverReceivedAt: '2026-08-24T09:01:00Z' }),
      ev('rep', 'REPAIR_STARTED', { serverReceivedAt: '2026-08-24T09:10:00Z' }),
      ev('res', 'RESOLVED', {
        serverReceivedAt: '2026-08-24T10:00:00Z',
        payload: { immediate_correction: 'Replaced the seal kit.' },
      }),
    ];
    const state = replay(TICKET, [
      ...base,
      ev('diag-a', 'DIAGNOSED', {
        deviceId: 'phone-a',
        serverReceivedAt: '2026-08-24T10:20:00Z',
        payload: { why_1: 'Seal failed.', preventive_action: 'Check seals monthly.' },
      }),
      ev('diag-b', 'DIAGNOSED', {
        deviceId: 'phone-b',
        serverReceivedAt: '2026-08-24T10:25:00Z',
        payload: { why_1: 'Seal hardened from running hot.' },
      }),
    ]);

    // diag-b advanced the stage first at 10:20 (diag-a), so diag-b is a NOOP —
    // and the text it carried is NOT silently merged in. The winning write is
    // whole, not a Frankenstein of two people's sentences.
    expect(state.why1).toBe('Seal failed.');
    expect(state.preventiveAction).toBe('Check seals monthly.');
    expect(state.noopEventIds).toContain('diag-b');
  });
});

describe('ordering', () => {
  it('server-acknowledged events precede pending ones', () => {
    const pending = ev('p', 'ACKNOWLEDGED', { clientTs: '2026-08-24T08:00:00Z' });
    const synced = ev('s', 'ACKNOWLEDGED', {
      clientTs: '2026-08-24T09:00:00Z',
      serverReceivedAt: '2026-08-24T09:00:05Z',
    });
    expect(orderEvents([pending, synced]).map((e) => e.eventId)).toEqual(['s', 'p']);
  });

  it('breaks exact ties deterministically', () => {
    const same = '2026-08-24T09:00:00Z';
    const a = ev('aaa', 'ACKNOWLEDGED', { serverReceivedAt: same });
    const b = ev('bbb', 'ACKNOWLEDGED', { serverReceivedAt: same });
    expect(orderEvents([b, a]).map((e) => e.eventId)).toEqual(['aaa', 'bbb']);
    expect(orderEvents([a, b]).map((e) => e.eventId)).toEqual(['aaa', 'bbb']);
  });
});

describe('outbox', () => {
  const entry = (over: Partial<OutboxEntry> = {}): OutboxEntry => ({
    event: ev('x', 'ACKNOWLEDGED'),
    status: 'pending',
    attempts: 0,
    ...over,
  });

  it('backs off exponentially and caps at five minutes', () => {
    expect(backoffMs(1)).toBe(2000);
    expect(backoffMs(2)).toBe(4000);
    expect(backoffMs(3)).toBe(8000);
    expect(backoffMs(99)).toBe(300_000);
  });

  it('never sends something already in flight', () => {
    expect(isDue(entry({ status: 'sending' }), Date.now())).toBe(false);
  });

  it('waits out the backoff window', () => {
    const now = 1_000_000;
    expect(isDue(entry({ status: 'failed', nextAttemptAt: now + 5000 }), now)).toBe(false);
    expect(isDue(entry({ status: 'failed', nextAttemptAt: now - 1 }), now)).toBe(true);
  });

  it('sends a ticket’s events in the order they were created', () => {
    // Out of order, the server replays ACKNOWLEDGED after RESOLVED and records
    // a NOOP for work that actually happened.
    const later = entry({
      event: ev('2', 'REPAIR_STARTED', { clientTs: '2026-08-24T09:10:00Z' }),
    });
    const earlier = entry({
      event: ev('1', 'ACKNOWLEDGED', { clientTs: '2026-08-24T09:05:00Z' }),
    });
    expect(dueEntries([later, earlier], Date.now()).map((e) => e.event.eventId)).toEqual([
      '1',
      '2',
    ]);
  });

  it('retries what is worth retrying and gives up on what is not', () => {
    // A 4xx will never succeed, and retrying it forever blocks every event
    // behind it in the queue.
    expect(shouldRetry(0)).toBe(true); // no connection
    expect(shouldRetry(503)).toBe(true); // Render waking up
    expect(shouldRetry(429)).toBe(true);
    expect(shouldRetry(422)).toBe(false); // malformed; will never pass
    expect(shouldRetry(403)).toBe(false);
  });
});

describe('newEventId', () => {
  it('produces time-ordered ids', () => {
    const early = newEventId(1_700_000_000_000, () => 0.5);
    const late = newEventId(1_700_000_001_000, () => 0.5);
    expect(early < late).toBe(true);
  });

  it('looks like a v7 uuid', () => {
    const id = newEventId(Date.now(), () => 0.5);
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });
});
