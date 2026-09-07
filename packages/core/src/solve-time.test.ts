/**
 * Solve time, per the Round 2 decisions document.
 *
 * The formula changed from "acknowledged -> complete" to "correction started
 * -> complete, minus pending". These tests pin the parts that are easy to get
 * subtly wrong and impossible to notice: an open window, a repeated hold, and
 * the floor at zero.
 */

import { describe, expect, it } from 'vitest';
import {
  pendingMinutes,
  repairStartDelayMinutes,
  shouldReopenRatherThanRaise,
  solveTimeMinutes,
  REOPEN_WINDOW_HOURS,
} from './tickets';

const at = (h: number, m = 0) =>
  new Date(Date.UTC(2026, 8, 7, h, m)).toISOString();

describe('solve time', () => {
  it('is the gap between starting and finishing when nothing paused', () => {
    expect(
      solveTimeMinutes({ correctionStartedAt: at(9), correctionCompleteAt: at(11) }),
    ).toBe(120);
  });

  it('subtracts a closed wait for a part', () => {
    // 09:00 start, held 09:30-10:30 for a part, done 11:00.
    // Four hours on the clock, three of them working.
    expect(
      solveTimeMinutes({
        correctionStartedAt: at(9),
        correctionCompleteAt: at(11),
        pendingWindows: [{ kind: 'material', startedAt: at(9, 30), endedAt: at(10, 30) }],
      }),
    ).toBe(60);
  });

  it('subtracts every window when the repair stalled more than once', () => {
    // The flowchart loops: hold, resume, try, still broken, hold again.
    expect(
      solveTimeMinutes({
        correctionStartedAt: at(8),
        correctionCompleteAt: at(14),
        pendingWindows: [
          { kind: 'material', startedAt: at(9), endedAt: at(10) },
          { kind: 'correction_pending', startedAt: at(11), endedAt: at(12, 30) },
        ],
      }),
    ).toBe(210); // 360 total - 60 - 90
  });

  it('ignores a window that is still open', () => {
    // Still waiting for the part. The repair has no duration yet, and the
    // subtraction must not grow every time someone loads the dashboard.
    expect(pendingMinutes([{ kind: 'material', startedAt: at(9), endedAt: null }])).toBe(0);
  });

  it('is null while the repair is unfinished', () => {
    // Not 0 - a zero would be averaged in and drag the plant figure down.
    expect(solveTimeMinutes({ correctionStartedAt: at(9) })).toBeNull();
    expect(solveTimeMinutes({ correctionCompleteAt: at(11) })).toBeNull();
  });

  it('never goes negative when clocks disagree', () => {
    // A queued device timestamp can land slightly outside a server-stamped
    // pair. Zero is the floor; a negative repair is not a thing.
    expect(
      solveTimeMinutes({
        correctionStartedAt: at(9),
        correctionCompleteAt: at(9, 30),
        pendingWindows: [{ kind: 'material', startedAt: at(9), endedAt: at(10) }],
      }),
    ).toBe(0);
  });
});

describe('repair start delay', () => {
  it('measures acknowledged to started, and stays out of solve time', () => {
    expect(repairStartDelayMinutes(at(9), at(10, 30))).toBe(90);
    // The same ticket's solve time knows nothing about that 90 minutes.
    expect(
      solveTimeMinutes({ correctionStartedAt: at(10, 30), correctionCompleteAt: at(11) }),
    ).toBe(30);
  });

  it('is null until work actually starts', () => {
    expect(repairStartDelayMinutes(at(9), null)).toBeNull();
  });
});

describe('reopen vs new ticket', () => {
  it('reopens inside the 48 hour bracket', () => {
    expect(shouldReopenRatherThanRaise(at(9), at(9 + 47))).toBe(true);
  });

  it('raises a new ticket once the bracket has passed', () => {
    const complete = new Date(Date.UTC(2026, 8, 7, 9)).toISOString();
    const later = new Date(
      Date.UTC(2026, 8, 7, 9) + (REOPEN_WINDOW_HOURS + 1) * 3600_000,
    ).toISOString();
    expect(shouldReopenRatherThanRaise(complete, later)).toBe(false);
  });

  it('says no when the ticket was never completed', () => {
    expect(shouldReopenRatherThanRaise(null, at(12))).toBe(false);
  });
});
