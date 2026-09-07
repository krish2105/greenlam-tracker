/**
 * Criticality, per V5 §5.8.
 *
 * The rule replaced a human judgement call, so nothing downstream is watching
 * it any more. A priority somebody picked wrong got caught by the next person
 * to read the ticket; a band boundary off by one produces a dashboard that is
 * confidently wrong and looks fine.
 *
 * The same table is asserted on the Python side in
 * `api/tests/test_criticality.py`, which additionally reads the defaults out of
 * this file's source so the two copies cannot drift apart.
 */

import { describe, expect, it } from 'vitest';

import {
  criticalityFromSolveTime,
  DEFAULT_CRITICALITY_THRESHOLDS,
  solveTimeMinutes,
} from './tickets';

const press = DEFAULT_CRITICALITY_THRESHOLDS.press;
const other = DEFAULT_CRITICALITY_THRESHOLDS.other;

describe('criticalityFromSolveTime', () => {
  it('bands a press repair at half the width of everything else', () => {
    expect(criticalityFromSolveTime(29, press)).toBe('Low');
    expect(criticalityFromSolveTime(45, press)).toBe('Medium');
    expect(criticalityFromSolveTime(90, press)).toBe('High');

    // The same 45 minutes on a sander is still Low.
    expect(criticalityFromSolveTime(45, other)).toBe('Low');
    expect(criticalityFromSolveTime(90, other)).toBe('Medium');
    expect(criticalityFromSolveTime(150, other)).toBe('High');
  });

  it('puts a boundary value in the lower band', () => {
    // Exactly 30 minutes on a press is Low. A repair timed at the threshold
    // should not inflate the High count on a rounding artefact.
    expect(criticalityFromSolveTime(30, press)).toBe('Low');
    expect(criticalityFromSolveTime(60, press)).toBe('Medium');
    expect(criticalityFromSolveTime(60, other)).toBe('Low');
    expect(criticalityFromSolveTime(120, other)).toBe('Medium');
  });

  it('has no answer for an unfinished repair', () => {
    // This is the whole reason it cannot rank a live queue: at the moment
    // somebody picks which of four stopped machines to walk to, all four
    // answer null.
    expect(criticalityFromSolveTime(null, press)).toBeNull();
    expect(criticalityFromSolveTime(undefined, press)).toBeNull();
  });

  it('reads the thresholds it is given, not the defaults', () => {
    // V5 §16 makes them admin-editable, and the trial exists partly to find
    // out whether 30 minutes was the right guess.
    const strict = { lowMaxMinutes: 10, mediumMaxMinutes: 20 };
    expect(criticalityFromSolveTime(15, strict)).toBe('Medium');
    expect(criticalityFromSolveTime(15, press)).toBe('Low');
  });
});

describe('the two functions compose', () => {
  it('classifies a repair that spent most of its wall clock waiting', () => {
    // Started 08:00, finished 12:00, three of those hours waiting for a part.
    // That is a one-hour repair on a press: Medium, not High.
    const iso = (h: number) => new Date(Date.UTC(2026, 8, 7, h)).toISOString();
    const minutes = solveTimeMinutes({
      correctionStartedAt: iso(8),
      correctionCompleteAt: iso(12),
      pendingWindows: [{ kind: 'material', startedAt: iso(9), endedAt: iso(12) }],
    });

    expect(minutes).toBe(60);
    expect(criticalityFromSolveTime(minutes, press)).toBe('Medium');
  });
});
