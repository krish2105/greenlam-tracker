/**
 * Shared logic for the floor app, the dashboard, and the later Expo port.
 *
 * Hard rule: nothing in this package touches the DOM, React, or a browser API.
 * The state machine, sync reducer and KPI math land here in Phases 2 and 5 and
 * must stay portable (spec §4.1).
 */

export * from './brand';
export * from './domain';
export * from './roles';
export * from './sync';
export * from './theme';
export * from './tickets';
export * from './xlsx';
