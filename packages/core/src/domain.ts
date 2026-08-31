/**
 * Domain vocabulary, shared by the floor app and the dashboard.
 *
 * These constants mirror `api/app/models/` and the CHECK constraints in
 * migration 0001. If you change one side, change the other — the migration is
 * the enforcing copy.
 */

// Roles moved to ./roles.ts when the org hierarchy landed. A single rank
// ordering could not express it: a shareholder sits at the top of the chart
// and sees the least operational detail, so access needed capability, scope
// and resolution as separate axes rather than one number.

/**
 * The 7-stage lifecycle from the reference prototype. Index is the stored
 * `current_stage`. Stages move forward only, except an explicit REOPENED event.
 */
export const STAGES = [
  'raised',
  'ack',
  'material',
  'repair',
  'resolved',
  'diagnosis',
  'closed',
] as const;
export type Stage = (typeof STAGES)[number];

export const CLOSED_STAGE = 6;

export const PRIORITIES = ['Low', 'Medium', 'High', 'Critical'] as const;
export type Priority = (typeof PRIORITIES)[number];

/**
 * Planned downtime and changeovers are downtime but not failures. Mixing them
 * into MTBF makes the metric meaningless (spec §5.2).
 */
export const DOWNTIME_TYPES = [
  'breakdown',
  'planned',
  'changeover',
  'no_downtime',
] as const;
export type DowntimeType = (typeof DOWNTIME_TYPES)[number];

export function countsTowardMtbf(type: DowntimeType): boolean {
  return type === 'breakdown';
}

/** Locales. Only `en` has a translation file in Phase 1; the rest land in Phase 7. */
export const LOCALES = ['en', 'hi', 'hi-Latn'] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = 'en';

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (LOCALES as readonly string[]).includes(value);
}

/** A machine gets flagged for preventive maintenance at this many breakdowns. */
export const PM_THRESHOLD = 3;
