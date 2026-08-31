/**
 * Two access levels, and the boundary between them.
 *
 * These tests replaced a much larger suite that exercised the ten-role,
 * three-axis model — org tiers, section scoping, corporate redaction. That
 * model is gone (see roles.ts), and keeping its tests would have meant a
 * green suite proving rules the product no longer has.
 */

import { describe, expect, it } from 'vitest';

import { CAPABILITIES, ROLES, can, capabilitiesOf, homeRouteFor, isRole, seesDashboard } from './roles';

describe('roles', () => {
  it('has exactly two', () => {
    expect(ROLES).toEqual(['app', 'dashboard']);
  });

  it('lets everyone on the floor report a breakdown', () => {
    // The one rule that must never acquire an exception: a machine that
    // stopped is a fact, not a privilege.
    for (const role of ROLES) {
      expect(can(role, 'raiseTicket')).toBe(true);
      expect(can(role, 'logProduction')).toBe(true);
    }
  });

  it('keeps the dashboard, the import and the masters together', () => {
    // These three travel as a set: importing rewrites shared history, and it
    // is meaningless without the masters to map onto or the board to read the
    // result. Splitting them would let someone import against a vocabulary
    // they cannot correct.
    for (const capability of ['viewDashboard', 'importData', 'editMasters'] as const) {
      expect(can('app', capability)).toBe(false);
      expect(can('dashboard', capability)).toBe(true);
    }
  });

  it('sends each level to the surface built for it', () => {
    expect(homeRouteFor('app')).toBe('/floor');
    expect(homeRouteFor('dashboard')).toBe('/board');
  });

  it('treats an unknown role as having no capabilities at all', () => {
    // Fail closed. A role that fell out of a stale token or a hand-edited
    // database row must not inherit anything.
    expect(isRole('plant_head')).toBe(false);
    expect(seesDashboard('plant_head')).toBe(false);
    expect(Object.values(capabilitiesOf('nonsense')).every((v) => v === false)).toBe(true);
  });

  it('exposes every capability on every role, so a typo cannot read as false', () => {
    const keys = Object.keys(CAPABILITIES.dashboard).sort();
    for (const role of ROLES) {
      expect(Object.keys(CAPABILITIES[role]).sort()).toEqual(keys);
    }
  });
});
