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

// ---------------------------------------------------------------------------
// Solve time, repair start delay, and the reopen window
//
// Round 2 decisions document, "Resolved: Solve Time formula".
// ---------------------------------------------------------------------------

/** One paused stretch of a repair. Both kinds stop the clock. */
export interface PendingWindow {
  kind: 'material' | 'correction_pending';
  startedAt: string;
  /** Null while the wait is still running. */
  endedAt?: string | null;
}

export interface SolveTimeInput {
  /** `repair_at` on the row. The moment someone actually started work. */
  correctionStartedAt?: string | null;
  /** `resolved_at` on the row. The moment the machine ran again. */
  correctionCompleteAt?: string | null;
  pendingWindows?: PendingWindow[];
}

/**
 * Minutes of pending time, counting only windows that have closed.
 *
 * An open window is deliberately excluded rather than run to `now`: while the
 * plant is still waiting for a part, the repair has no solve time yet, and
 * growing the subtraction every second would make the number move on a
 * dashboard nobody is touching.
 */
export function pendingMinutes(windows: PendingWindow[] | undefined): number {
  if (!windows?.length) return 0;
  return windows.reduce(
    (total, w) => (w.endedAt ? total + minutesBetween(w.startedAt, w.endedAt) : total),
    0,
  );
}

/**
 * Solve time = (correction complete − correction started) − pending time.
 *
 * Measured from the moment work STARTED, not from acknowledgement. The wait
 * before someone picks up a spanner is a real problem, but it is a different
 * problem with a different owner, and folding it in here made a fast repair on
 * a busy shift look like a slow one. It is reported separately as
 * `repairStartDelay` below.
 *
 * Returns null until the repair is complete — an unfinished job has no
 * duration, and returning 0 would drag every average down.
 */
export function solveTimeMinutes(input: SolveTimeInput): number | null {
  const { correctionStartedAt, correctionCompleteAt } = input;
  if (!correctionStartedAt || !correctionCompleteAt) return null;

  const gross = minutesBetween(correctionStartedAt, correctionCompleteAt);
  const net = gross - pendingMinutes(input.pendingWindows);
  // Clock skew between a queued device timestamp and a server one can put the
  // subtraction slightly ahead of the elapsed time. Zero is the honest floor;
  // a negative repair duration is not a thing.
  return Math.max(0, Math.round(net * 10) / 10);
}

/**
 * How long a ticket sat acknowledged before work began.
 *
 * Kept as its own KPI precisely because it is no longer inside solve time —
 * this is the number that shows a team acknowledging quickly to stop the SLA
 * clock and then not starting.
 */
export function repairStartDelayMinutes(
  ackedAt?: string | null,
  correctionStartedAt?: string | null,
): number | null {
  if (!ackedAt || !correctionStartedAt) return null;
  return Math.max(0, Math.round(minutesBetween(ackedAt, correctionStartedAt) * 10) / 10);
}

/**
 * The reopen bracket: 48 hours from the last fix.
 *
 * Inside it, the same problem coming back is the SAME ticket reopened. Outside
 * it, it is a new ticket. One rule, so two shifts do not record the same
 * recurrence two different ways and split it across two metrics.
 */
export const REOPEN_WINDOW_HOURS = 48;

/**
 * Whether a recurrence now should reopen the existing ticket or start a new
 * one. The SOP sentence, as a function, so the app and the training slide
 * cannot drift apart.
 */
export function shouldReopenRatherThanRaise(
  correctionCompleteAt: string | null | undefined,
  nowIso: string,
): boolean {
  if (!correctionCompleteAt) return false;
  return minutesBetween(correctionCompleteAt, nowIso) <= REOPEN_WINDOW_HOURS * 60;
}

// ---------------------------------------------------------------------------
// Criticality — the outcome, not the guess
// ---------------------------------------------------------------------------

/** Low, Medium or High. Assigned by the clock, never by a person. */
export type CalculatedCriticality = 'Low' | 'Medium' | 'High';

/**
 * The two boundaries that split solve time into three bands, in minutes.
 *
 * Held as data rather than constants because V5 §16 makes them admin-editable:
 * the defaults below are a hypothesis about this plant, and the trial exists
 * partly to test it.
 */
export interface CriticalityThresholds {
  /** At or under this many minutes: Low. */
  lowMaxMinutes: number;
  /** Above `lowMaxMinutes` and at or under this: Medium. Above it: High. */
  mediumMaxMinutes: number;
}

/**
 * V5 §5.8's defaults. A press stopping is worth more per minute than anything
 * else on the floor, so its bands are half as wide.
 */
export const DEFAULT_CRITICALITY_THRESHOLDS: Record<'press' | 'other', CriticalityThresholds> = {
  press: { lowMaxMinutes: 30, mediumMaxMinutes: 60 },
  other: { lowMaxMinutes: 60, mediumMaxMinutes: 120 },
};

/**
 * Classify a finished repair by how long the work actually took.
 *
 * The input is SOLVE time, not elapsed time — waiting for a part is not slow
 * work, and a repair that took twenty minutes across two days of waiting for a
 * bearing is a twenty-minute repair. `solveTimeMinutes` above does that
 * subtraction; this only reads the result.
 *
 * Returns null while the repair is unfinished. That is the whole reason this
 * cannot rank a live queue: at the moment somebody is deciding which of four
 * open tickets to walk to, every one of them answers null here. Machine
 * criticality (A/B/C) is what ranks those.
 *
 * Boundaries are inclusive at the bottom of each band: exactly 30 minutes on a
 * press is Low, not Medium. V5 §5.8 writes "Under 30 min / 30 min – 1 hr",
 * which puts the boundary value in the upper band — but a repair timed at
 * exactly the threshold is the one case where the two readings differ, and
 * classifying it as the gentler of the two is the choice that does not inflate
 * the High count on a rounding artefact.
 */
export function criticalityFromSolveTime(
  solveMinutes: number | null | undefined,
  thresholds: CriticalityThresholds,
): CalculatedCriticality | null {
  if (solveMinutes === null || solveMinutes === undefined) return null;
  if (solveMinutes <= thresholds.lowMaxMinutes) return 'Low';
  if (solveMinutes <= thresholds.mediumMaxMinutes) return 'Medium';
  return 'High';
}
