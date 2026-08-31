/**
 * Capability model — the client half of `api/app/roles.py`.
 *
 * Both copies must agree, and `api/tests/test_roles.py` asserts it. This copy
 * hides controls a person cannot use; that is a courtesy, not a gate. The
 * server is the only thing that actually refuses.
 *
 * TWO LEVELS
 *   app        everyone on the floor — tickets and production logging
 *   dashboard  a named handful — all of the above plus the board, the Excel
 *              import, the master lists and user management
 *
 * The previous ten-role, three-axis model (capability × scope × resolution)
 * was deleted rather than disabled. See the Python file for why.
 */

export const ROLES = ['app', 'dashboard'] as const;
export type Role = (typeof ROLES)[number];

export interface Capabilities {
  raiseTicket: boolean;
  workTicket: boolean;
  verifyClose: boolean;
  logProduction: boolean;
  viewDashboard: boolean;
  editMasters: boolean;
  manageUsers: boolean;
  unlockUsers: boolean;
  exportData: boolean;
  importData: boolean;
}

const NONE: Capabilities = {
  raiseTicket: false,
  workTicket: false,
  verifyClose: false,
  logProduction: false,
  viewDashboard: false,
  editMasters: false,
  manageUsers: false,
  unlockUsers: false,
  exportData: false,
  importData: false,
};

export const CAPABILITIES: Record<Role, Capabilities> = {
  app: {
    ...NONE,
    raiseTicket: true,
    workTicket: true,
    verifyClose: true,
    logProduction: true,
  },
  dashboard: {
    raiseTicket: true,
    workTicket: true,
    verifyClose: true,
    logProduction: true,
    viewDashboard: true,
    editMasters: true,
    manageUsers: true,
    unlockUsers: true,
    exportData: true,
    importData: true,
  },
};

export function isRole(value: unknown): value is Role {
  return typeof value === 'string' && (ROLES as readonly string[]).includes(value);
}

export function capabilitiesOf(role: string): Capabilities {
  return isRole(role) ? CAPABILITIES[role] : NONE;
}

export function can(role: string, capability: keyof Capabilities): boolean {
  return capabilitiesOf(role)[capability];
}

export function seesDashboard(role: string): boolean {
  return can(role, 'viewDashboard');
}

/** Where a person lands after signing in. */
export function homeRouteFor(role: string): string {
  return seesDashboard(role) ? '/board' : '/floor';
}
