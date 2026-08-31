import { describe, expect, it } from 'vitest';

import {
  ACK_SLA_MINUTES,
  escalationOf,
  flagsFor,
  formatDuration,
  scoreRootCause,
  severityScore,
  type TicketLike,
} from './tickets';
import type { Priority } from './domain';

const NOW = '2026-08-24T10:00:00.000Z';

function minutesAgo(n: number): string {
  return new Date(Date.parse(NOW) - n * 60000).toISOString();
}

function ticket(overrides: Partial<TicketLike> = {}): TicketLike {
  return {
    currentStage: 0,
    priority: 'Medium' as Priority,
    raisedAt: minutesAgo(5),
    ...overrides,
  };
}

describe('escalation', () => {
  it('stays quiet inside the SLA', () => {
    const t = ticket({ priority: 'Critical', raisedAt: minutesAgo(5) });
    expect(escalationOf(t, NOW).level).toBe('none');
  });

  it('reaches the supervisor past the SLA', () => {
    const t = ticket({ priority: 'Critical', raisedAt: minutesAgo(15) });
    const e = escalationOf(t, NOW);
    expect(e.level).toBe('supervisor');
    expect(Math.round(e.overdueMinutes)).toBe(15 - ACK_SLA_MINUTES.Critical);
  });

  it('reaches the plant head at double the SLA', () => {
    const t = ticket({ priority: 'Critical', raisedAt: minutesAgo(25) });
    expect(escalationOf(t, NOW).level).toBe('plant_head');
  });

  it('escalates a Critical long before a Low', () => {
    const raised = minutesAgo(60);
    expect(escalationOf(ticket({ priority: 'Critical', raisedAt: raised }), NOW).level).toBe(
      'plant_head',
    );
    expect(escalationOf(ticket({ priority: 'Low', raisedAt: raised }), NOW).level).toBe('none');
  });

  it('stops once someone acknowledges', () => {
    // Escalation is about nobody responding. After that, duration is a
    // performance question, not an alarm.
    const t = ticket({
      priority: 'Critical',
      raisedAt: minutesAgo(300),
      ackedAt: minutesAgo(290),
      currentStage: 1,
    });
    expect(escalationOf(t, NOW).level).toBe('none');
  });

  it('is derived, so the same inputs always give the same answer', () => {
    // No scheduler, nothing stored — a stalled escalator would leave the board
    // looking calm while a press sits dead.
    const t = ticket({ priority: 'High', raisedAt: minutesAgo(45) });
    expect(escalationOf(t, NOW)).toEqual(escalationOf(t, NOW));
  });
});

describe('flags', () => {
  it('flags a ticket running again but with no root cause written', () => {
    const t = ticket({ currentStage: 4, raisedAt: minutesAgo(120) });
    expect(flagsFor(t, NOW)).toContain('awaiting_root_cause');
  });

  it('flags ageing only past three days', () => {
    expect(flagsFor(ticket({ raisedAt: minutesAgo(2 * 24 * 60) }), NOW)).not.toContain('ageing');
    expect(flagsFor(ticket({ raisedAt: minutesAgo(4 * 24 * 60) }), NOW)).toContain('ageing');
  });

  it('flags reopened and repeat faults', () => {
    expect(flagsFor(ticket({ reopenCount: 1 }), NOW)).toContain('reopened');
    expect(flagsFor({ ...ticket(), repeatCount: 3 }, NOW)).toContain('repeat');
  });

  it('leaves a closed ticket alone', () => {
    const closed = ticket({ currentStage: 6, raisedAt: minutesAgo(10 * 24 * 60) });
    const flags = flagsFor(closed, NOW);
    expect(flags).not.toContain('ageing');
    expect(flags).not.toContain('escalated');
  });
});

describe('severity ranking', () => {
  it('puts an escalated Critical above a quiet Low', () => {
    const critical = ticket({ priority: 'Critical', raisedAt: minutesAgo(40) });
    const low = ticket({ priority: 'Low', raisedAt: minutesAgo(5) });
    expect(severityScore(critical, NOW)).toBeGreaterThan(severityScore(low, NOW));
  });

  it('lifts a repeat fault above a one-off of the same priority', () => {
    const once = { ...ticket({ priority: 'Medium' }), repeatCount: 1 };
    const again = { ...ticket({ priority: 'Medium' }), repeatCount: 4 };
    expect(severityScore(again, NOW)).toBeGreaterThan(severityScore(once, NOW));
  });
});

describe('root-cause quality', () => {
  const good = {
    why1: 'Hydraulic seal failed and pressure dropped below 90 bar.',
    why2: 'The seal had hardened from continuous running above rated temperature.',
    why3: 'Cooling circuit flow was never checked after the June pump change.',
    preventiveAction: 'Add cooling flow verification to the quarterly PM checklist.',
  };

  it('scores a full why-why with a distinct action as usable', () => {
    const result = scoreRootCause(good);
    expect(result.usable).toBe(true);
    expect(result.score).toBeGreaterThanOrEqual(90);
  });

  it('rejects the entries that actually show up in week three', () => {
    for (const junk of ['machine stopped', 'belt issue', 'not working', 'fixed']) {
      const result = scoreRootCause({ why1: junk });
      expect(result.usable).toBe(false);
    }
  });

  it('penalises a copy of the previous entry for the same machine', () => {
    const fresh = scoreRootCause(good);
    const copied = scoreRootCause({ ...good, previousForMachine: good.why1 });
    expect(copied.score).toBeLessThan(fresh.score);
    expect(copied.reasons.join(' ')).toMatch(/identical/i);
  });

  it('penalises a preventive action that just restates the last why', () => {
    const lazy = scoreRootCause({ ...good, preventiveAction: good.why3 });
    expect(lazy.score).toBeLessThan(scoreRootCause(good).score);
  });

  it('says a fix is not a prevention', () => {
    const noAction = scoreRootCause({ ...good, preventiveAction: null });
    expect(noAction.reasons.join(' ')).toMatch(/preventive/i);
  });

  it('rewards each additional why-level', () => {
    const one = scoreRootCause({ why1: good.why1 }).score;
    const two = scoreRootCause({ why1: good.why1, why2: good.why2 }).score;
    const three = scoreRootCause({ why1: good.why1, why2: good.why2, why3: good.why3 }).score;
    expect(two).toBeGreaterThan(one);
    expect(three).toBeGreaterThan(two);
  });

  it('never returns a score outside 0-100', () => {
    const worst = scoreRootCause({ why1: 'x', previousForMachine: 'x' });
    expect(worst.score).toBeGreaterThanOrEqual(0);
    expect(worst.score).toBeLessThanOrEqual(100);
  });
});

describe('formatDuration', () => {
  it('reads the way a person would say it', () => {
    expect(formatDuration(0.4)).toBe('<1 min');
    expect(formatDuration(14)).toBe('14 min');
    expect(formatDuration(130)).toBe('2h 10m');
    expect(formatDuration(60 * 27)).toBe('1d 3h');
  });
});
