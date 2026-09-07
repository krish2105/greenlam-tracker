/**
 * Access areas — the client half of `api/app/roles.py`.
 *
 * Both copies must agree, and `api/tests/test_access_areas.py` asserts it by
 * reading this file. This copy hides controls a person cannot use; that is a
 * courtesy, not a gate. The server is the only thing that actually refuses.
 *
 * SIX AREAS, HELD IN ANY COMBINATION (V5 §3)
 *
 *   hplProduction  raise tickets, submit production data, read the daily log
 *   maintenance    acknowledge, work and close tickets; the ticket summary
 *   supervisor     notified about flagged tickets; reopen; reassign
 *   manager        the same, plus handing a ticket to a named person
 *   dashboard      the analytics dashboards and their exports
 *   admin          approve accounts, grant areas, edit the master lists
 *
 * A person holds a SET, and their capabilities are the union. Nothing is
 * inherited: an account with `dashboard` alone reads every number and cannot
 * touch a ticket, which is what a plant head usually wants.
 *
 * The previous model was one `role` string of two values. It was right while
 * the only question was "does this person need the board", and wrong the moment
 * V5 asked for a supervisor who is notified about flagged tickets but does not
 * work them.
 */

export const AREAS = [
  'hpl_production',
  'maintenance',
  'supervisor',
  'manager',
  'dashboard',
  'admin',
] as const;
export type Area = (typeof AREAS)[number];

export interface Capabilities {
  raiseTicket: boolean;
  workTicket: boolean;
  reopenTicket: boolean;
  /** Handing a ticket to a named person on somebody else's behalf (V5 §15.5). */
  reassignTicket: boolean;
  logProduction: boolean;
  viewDashboard: boolean;
  editMasters: boolean;
  approveUsers: boolean;
  manageUsers: boolean;
  unlockUsers: boolean;
  exportData: boolean;
  importData: boolean;
}

const NONE: Capabilities = {
  raiseTicket: false,
  workTicket: false,
  reopenTicket: false,
  reassignTicket: false,
  logProduction: false,
  viewDashboard: false,
  editMasters: false,
  approveUsers: false,
  manageUsers: false,
  unlockUsers: false,
  exportData: false,
  importData: false,
};

/**
 * Raising a breakdown is on every area on purpose. A machine that stopped is a
 * fact, not a privilege, and the person standing next to it is whoever happens
 * to be standing next to it. The one account that cannot raise a ticket holds
 * no areas at all — a signup nobody has approved, or one deliberately emptied.
 */
export const CAPABILITIES: Record<Area, Capabilities> = {
  hpl_production: { ...NONE, raiseTicket: true, logProduction: true },
  maintenance: { ...NONE, raiseTicket: true, workTicket: true, reopenTicket: true },
  supervisor: { ...NONE, raiseTicket: true, reopenTicket: true, reassignTicket: true },
  manager: { ...NONE, raiseTicket: true, reopenTicket: true, reassignTicket: true },
  dashboard: { ...NONE, viewDashboard: true, exportData: true },
  admin: {
    ...NONE,
    raiseTicket: true,
    reopenTicket: true,
    reassignTicket: true,
    editMasters: true,
    approveUsers: true,
    manageUsers: true,
    unlockUsers: true,
    importData: true,
  },
};

const KEYS = Object.keys(NONE) as (keyof Capabilities)[];

export function isArea(value: unknown): value is Area {
  return typeof value === 'string' && (AREAS as readonly string[]).includes(value);
}

/** The union over every area held. Unknown names contribute nothing. */
export function capabilitiesOf(areas: readonly string[] | undefined): Capabilities {
  const held = (areas ?? []).filter(isArea).map((a) => CAPABILITIES[a]);
  if (held.length === 0) return NONE;
  return Object.fromEntries(
    KEYS.map((k) => [k, held.some((c) => c[k])]),
  ) as unknown as Capabilities;
}

export function can(
  areas: readonly string[] | undefined,
  capability: keyof Capabilities,
): boolean {
  return capabilitiesOf(areas)[capability];
}

export function seesDashboard(areas: readonly string[] | undefined): boolean {
  return can(areas, 'viewDashboard');
}

/**
 * Whether this account is waiting to be let in.
 *
 * Holding nothing is not enough to tell: an account whose access was revoked
 * also holds nothing, and it has already been dealt with. `approvedAt` is what
 * separates the two.
 */
export function isPendingApproval(user: {
  areas?: readonly string[];
  approved_at?: string | null;
}): boolean {
  return !user.approved_at;
}

/** Where a person lands after signing in. */
export function homeRouteFor(areas: readonly string[] | undefined): string {
  return seesDashboard(areas) ? '/board' : '/floor';
}
