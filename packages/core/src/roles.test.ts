/**
 * Six access areas, and the boundaries between them.
 *
 * These replaced a suite that tested two levels, which had itself replaced one
 * testing ten roles across three axes. Each time the model changed the old
 * tests were deleted rather than adapted: a green suite proving rules the
 * product no longer has is worse than no suite, because it is believed.
 */

import { describe, expect, it } from 'vitest';

import {
  AREAS,
  CAPABILITIES,
  can,
  capabilitiesOf,
  homeRouteFor,
  isArea,
  isPendingApproval,
  seesDashboard,
} from './roles';

describe('access areas', () => {
  it('has exactly the six V5 names', () => {
    expect(AREAS).toEqual([
      'hpl_production',
      'maintenance',
      'supervisor',
      'manager',
      'dashboard',
      'admin',
    ]);
  });

  it('takes the union of everything held', () => {
    const both = ['hpl_production', 'maintenance'];
    expect(can(both, 'logProduction')).toBe(true);
    expect(can(both, 'workTicket')).toBe(true);
  });

  it('inherits nothing', () => {
    // Somebody who reads the board and nothing else is a plant head, and that
    // is a real account rather than a misconfiguration.
    expect(can(['dashboard'], 'viewDashboard')).toBe(true);
    expect(can(['dashboard'], 'workTicket')).toBe(false);
    expect(can(['dashboard'], 'raiseTicket')).toBe(false);
  });

  it('lets anyone with an area report a breakdown', () => {
    // The one rule that must never acquire an exception: a machine that
    // stopped is a fact, not a privilege.
    for (const area of AREAS) {
      if (area === 'dashboard') continue; // reads the board, is not on the floor
      expect(CAPABILITIES[area].raiseTicket).toBe(true);
    }
  });

  it('gives nobody without an area anything', () => {
    expect(capabilitiesOf([])).toEqual(capabilitiesOf(undefined));
    expect(can([], 'raiseTicket')).toBe(false);
    expect(can(undefined, 'viewDashboard')).toBe(false);
  });

  it('opens reopening wider than working', () => {
    // V5 §5.4 — the only real safety net against a premature close is somebody
    // noticing the machine is still broken, so the net is kept wide.
    for (const area of ['maintenance', 'supervisor', 'manager', 'admin']) {
      expect(can([area], 'reopenTicket')).toBe(true);
    }
    expect(can(['hpl_production'], 'reopenTicket')).toBe(false);
    expect(can(['supervisor'], 'workTicket')).toBe(false);
  });

  it('ignores an unknown area rather than throwing', () => {
    expect(isArea('warehouse')).toBe(false);
    expect(can(['warehouse'], 'raiseTicket')).toBe(false);
    expect(can(['warehouse', 'maintenance'], 'workTicket')).toBe(true);
  });

  it('sends people to the screen they can actually use', () => {
    expect(homeRouteFor(['dashboard'])).toBe('/board');
    expect(homeRouteFor(['hpl_production'])).toBe('/floor');
    expect(homeRouteFor([])).toBe('/floor');
    expect(seesDashboard(['admin'])).toBe(false);
  });

  it('tells a pending account apart from a revoked one', () => {
    // Both hold nothing. Only one of them is waiting for somebody to look.
    expect(isPendingApproval({ areas: [], approved_at: null })).toBe(true);
    expect(isPendingApproval({ areas: [], approved_at: '2026-09-07T10:00:00Z' })).toBe(false);
  });
});
