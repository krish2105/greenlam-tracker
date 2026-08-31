/**
 * Ticket state, escalation and root-cause quality.
 *
 * Pure functions on purpose. The same rules have to hold on a phone that has
 * been offline for six hours, on the API, and in the nightly export — three
 * implementations would drift, and the first symptom would be a KPI nobody
 * trusts.
 */

import { CLOSED_STAGE, STAGES, type Priority, type Stage } from './domain';

export interface TicketLike {
  currentStage: number;
  priority: Priority;
  raisedAt: string;
  ackedAt?: string | null;
  resolvedAt?: string | null;
  closedAt?: string | null;
  reopenCount?: number;
}

// ---------------------------------------------------------------------------
// Escalation
// ---------------------------------------------------------------------------

/**
 * Minutes a ticket may sit unacknowledged before it escalates.
 *
 * PLACEHOLDER until Phase 0 confirms the real response expectation with the
 * maintenance head. These are deliberately conservative: too tight and the
 * board is permanently red, which trains everyone to ignore it.
 */
export const ACK_SLA_MINUTES: Record<Priority, number> = {
  Critical: 10,
  High: 30,
  Medium: 120,
  Low: 480,
};

/** Who a breach has reached. Recomputed on read — no scheduler required. */
export type EscalationLevel = 'none' | 'due' | 'supervisor' | 'plant_head';

export interface Escalation {
  level: EscalationLevel;
  /** Minutes waiting for acknowledgement. Negative once acknowledged. */
  waitingMinutes: number;
  /** Minutes past the SLA. 0 when inside it. */
  overdueMinutes: number;
}

export function minutesBetween(fromIso: string, toIso: string): number {
  return (new Date(toIso).getTime() - new Date(fromIso).getTime()) / 60000;
}

/**
 * Escalation is derived, never stored.
 *
 * Render's free tier has no cron, so a background job that "sets" escalation
 * would be a moving part that can silently stop — and a stalled escalator is
 * worse than none, because the board looks calm while a press sits dead.
 * Computing it from timestamps on every read cannot drift.
 */
export function escalationOf(ticket: TicketLike, nowIso: string): Escalation {
  // Only the wait for acknowledgement escalates. Once a technician is on it,
  // duration is a performance question, not an alarm.
  if (ticket.ackedAt || ticket.currentStage > 0) {
    return { level: 'none', waitingMinutes: -1, overdueMinutes: 0 };
  }

  const waiting = minutesBetween(ticket.raisedAt, nowIso);
  const sla = ACK_SLA_MINUTES[ticket.priority];
  const overdue = waiting - sla;

  if (overdue <= 0) {
    return { level: 'none', waitingMinutes: waiting, overdueMinutes: 0 };
  }
  // Doubling the SLA pulls in the plant head. One step, not a ladder — a
  // four-tier escalation chain in a plant of this size just adds noise.
  const level: EscalationLevel = overdue >= sla ? 'plant_head' : 'supervisor';
  return { level, waitingMinutes: waiting, overdueMinutes: overdue };
}

// ---------------------------------------------------------------------------
// Ticket health, for the exception feed
// ---------------------------------------------------------------------------

export type TicketFlag =
  | 'escalated'
  | 'ageing'
  | 'reopened'
  | 'repeat'
  | 'awaiting_root_cause';

export const AGEING_DAYS = 3;

export interface TicketHealthInput extends TicketLike {
  /** Times this machine + category has failed in the trailing 30 days. */
  repeatCount?: number;
}

/**
 * What makes a ticket worth surfacing to a human who is not already working it.
 *
 * This is the whole basis of the exception feed. A plant head does not want 33
 * machines; they want the three that are going wrong in a way nobody has
 * noticed yet.
 */
export function flagsFor(ticket: TicketHealthInput, nowIso: string): TicketFlag[] {
  const flags: TicketFlag[] = [];
  const closed = ticket.currentStage >= CLOSED_STAGE;

  if (!closed && escalationOf(ticket, nowIso).level !== 'none') {
    flags.push('escalated');
  }
  if (!closed && minutesBetween(ticket.raisedAt, nowIso) > AGEING_DAYS * 24 * 60) {
    flags.push('ageing');
  }
  if ((ticket.reopenCount ?? 0) > 0) {
    flags.push('reopened');
  }
  if ((ticket.repeatCount ?? 0) > 1) {
    flags.push('repeat');
  }
  // Running again but the analysis never landed. This is where root-cause data
  // quietly dies: the machine works, so nobody goes back to finish the write-up.
  if (ticket.currentStage === 4) {
    flags.push('awaiting_root_cause');
  }
  return flags;
}

/** Ranking for the exception feed. Higher is more urgent. */
export function severityScore(ticket: TicketHealthInput, nowIso: string): number {
  const priorityWeight: Record<Priority, number> = {
    Critical: 40,
    High: 25,
    Medium: 10,
    Low: 5,
  };
  let score = priorityWeight[ticket.priority];
  const esc = escalationOf(ticket, nowIso);
  if (esc.level === 'plant_head') score += 40;
  else if (esc.level === 'supervisor') score += 20;

  for (const flag of flagsFor(ticket, nowIso)) {
    if (flag === 'repeat') score += 15;
    if (flag === 'reopened') score += 15;
    if (flag === 'ageing') score += 10;
    if (flag === 'awaiting_root_cause') score += 5;
  }
  return score;
}

// ---------------------------------------------------------------------------
// Root-cause quality — addendum §4.2, review 5
// ---------------------------------------------------------------------------

export interface RootCauseInput {
  why1?: string | null;
  why2?: string | null;
  why3?: string | null;
  preventiveAction?: string | null;
  /** This technician's previous root cause for this machine, if any. */
  previousForMachine?: string | null;
}

export interface QualityScore {
  /** 0–100. Reported at TEAM level only — never per technician upward. */
  score: number;
  usable: boolean;
  reasons: string[];
}

const MIN_WHY_LENGTH = 12;

/** Words that fill the box without saying anything. */
const EMPTY_PHRASES = [
  'machine stopped',
  'not working',
  'belt issue',
  'problem',
  'issue',
  'fault',
  'error',
  'breakdown',
  'same as before',
  'repaired',
  'fixed',
  'ok now',
];

function normalise(text: string): string {
  return text.trim().toLowerCase().replace(/\s+/g, ' ');
}

function isSubstantive(text: string | null | undefined): boolean {
  if (!text) return false;
  const clean = normalise(text);
  if (clean.length < MIN_WHY_LENGTH) return false;
  return !EMPTY_PHRASES.some((phrase) => clean === phrase || clean === phrase + '.');
}

/**
 * Score a root-cause entry.
 *
 * The point is not to grade a technician. It is to watch the TEAM-level
 * percentage of usable entries over time: when it starts falling, the
 * analytics are about to become worthless, and you get three weeks of warning
 * instead of discovering it at the quarterly review.
 */
export function scoreRootCause(input: RootCauseInput): QualityScore {
  const reasons: string[] = [];
  let score = 0;

  const whys = [input.why1, input.why2, input.why3];
  const substantive = whys.filter(isSubstantive).length;

  // Three prompted why-levels rather than one free-text box is the whole
  // reason this is scoreable at all.
  score += substantive * 20;
  if (substantive === 0) reasons.push('No why-level was filled in usefully.');
  else if (substantive < 3) reasons.push(`Only ${substantive} of 3 why-levels answered.`);

  if (isSubstantive(input.preventiveAction)) {
    score += 25;
  } else {
    reasons.push('No distinct preventive action — a fix is not a prevention.');
  }

  // Copy-paste detection. Four breakdowns with four identical root causes is
  // the signature of a field being filled rather than answered.
  if (
    input.previousForMachine &&
    input.why1 &&
    normalise(input.previousForMachine) === normalise(input.why1)
  ) {
    score -= 30;
    reasons.push('Identical to the previous entry for this machine.');
  }

  // A preventive action that just restates the last why adds nothing.
  if (
    input.preventiveAction &&
    input.why3 &&
    normalise(input.preventiveAction) === normalise(input.why3)
  ) {
    score -= 10;
    reasons.push('Preventive action repeats the final why.');
  }

  score += 15; // baseline for a completed, non-empty submission
  const clamped = Math.max(0, Math.min(100, score));
  return { score: clamped, usable: clamped >= 60, reasons };
}

// ---------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------

export function stageOf(currentStage: number): Stage {
  return STAGES[Math.max(0, Math.min(currentStage, STAGES.length - 1))] ?? 'raised';
}

export function isOpen(currentStage: number): boolean {
  return currentStage < CLOSED_STAGE;
}

/** "14 min", "2h 10m", "3d 4h" — never a raw minute count on screen. */
export function formatDuration(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  if (m < 1) return '<1 min';
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}
