/**
 * API client.
 *
 * Same-origin by design: requests go to `/api/*` on this very host, which Vite
 * proxies in development and Render rewrites in production. That is what makes
 * the refresh cookie first-party, and therefore what makes it survive Safari's
 * cross-site cookie restrictions on iPhone.
 *
 * The access token is held in memory only — never localStorage, never a
 * readable cookie. If an XSS bug ever lands, it can reach at most a 30-minute
 * token from the current tab, not a 30-day session that survives a reload.
 *
 * Phase 1 keeps this deliberately thin. Phase 2 adds the Dexie outbox and the
 * retry/backoff behaviour; nothing here should grow into a sync engine.
 */

import type { Area, ThemePreference } from '@greenlam/core';

export interface ApiUser {
  id: number;
  employee_id: string;
  name: string;
  /**
   * Every access area this person holds (V5 §3). Combinable, and an empty list
   * is meaningful: either the account is waiting in the approval queue, or its
   * access was revoked. `approved_at` tells those apart.
   */
  areas: Area[];
  approved_at: string | null;
  plant_id: number;
  unit_id: number | null;
  section_id: number | null;
  preferred_language: string;
  preferred_theme: ThemePreference;
}

export interface Machine {
  id: number;
  section_id: number;
  code: string;
  name: string;
  name_hi: string | null;
  criticality: string;
  /** Which production form this machine gets. The floor dispatches on it. */
  production_form: 'press' | 'resin' | 'impregnation' | 'ac_room' | 'general';
  hourly_downtime_cost: number | null;
  qr_short_code: string;
  is_active: boolean;
}

export interface Section {
  id: number;
  name: string;
  name_hi: string | null;
  /** Latin-script Hindi. Absent from the type before; the API always sent it. */
  name_hi_latn: string | null;
  sort_order: number;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly retryAfter?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const BASE = '/api';

// Module-scoped, not exported. Nothing outside this file can read the token.
let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

// Render's free tier cold-starts in 30–60s. A shorter timeout would surface a
// sleeping service as an error; offline-first means we can afford to wait.
const TIMEOUT_MS = 90_000;

async function request<T>(
  path: string,
  init: RequestInit = {},
  { retryOnUnauthorized = true }: { retryOnUnauthorized?: boolean } = {},
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      signal: controller.signal,
      // Sends the httpOnly refresh cookie on the auth routes it is scoped to.
      credentials: 'same-origin',
      headers: {
        // A FormData body must NOT get an explicit Content-Type: the browser
        // has to set it itself so it can append the multipart boundary. Setting
        // it here makes every file upload fail with a parse error on the
        // server, and the error says nothing about the real cause.
        ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...init.headers,
      },
    });
  } catch (error) {
    clearTimeout(timer);
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(0, 'The server took too long to answer.');
    }
    throw new ApiError(0, 'No connection.');
  }
  clearTimeout(timer);

  // One transparent refresh attempt, then give up. Retrying a refresh that
  // already failed would trip the reuse detection and log the user out of
  // every device.
  if (response.status === 401 && retryOnUnauthorized && path !== '/auth/refresh') {
    const refreshed = await refresh().catch(() => null);
    if (refreshed) {
      return request<T>(path, init, { retryOnUnauthorized: false });
    }
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: { detail?: string }) => body.detail)
      .catch(() => undefined);
    const retryAfter = Number(response.headers.get('Retry-After')) || undefined;
    throw new ApiError(response.status, detail ?? 'Request failed.', retryAfter);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

interface TokenResponse {
  access_token: string;
  expires_at: string;
  user: ApiUser;
}

export async function login(
  employeeId: string,
  pin: string,
  deviceUid?: string,
): Promise<ApiUser> {
  const body = await request<TokenResponse>(
    '/auth/login',
    {
      method: 'POST',
      body: JSON.stringify({
        employee_id: employeeId,
        pin,
        device_uid: deviceUid,
        platform: navigator.platform || undefined,
      }),
    },
    { retryOnUnauthorized: false },
  );
  setAccessToken(body.access_token);
  return body.user;
}

// Single-flight. Refresh rotates the token and revokes its predecessor, so two
// concurrent refreshes are self-defeating: the second presents a token the
// first just revoked, the server reads that as a stolen token being replayed,
// and it revokes the whole family — logging the user out of every device.
//
// This is not hypothetical. Any two API calls that 401 together would race, and
// React StrictMode reproduces it on every mount in development. Sharing one
// in-flight promise means N callers cause exactly one rotation.
let refreshInFlight: Promise<ApiUser | null> | null = null;

export function refresh(): Promise<ApiUser | null> {
  refreshInFlight ??= doRefresh().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

async function doRefresh(): Promise<ApiUser | null> {
  try {
    const body = await request<TokenResponse>(
      '/auth/refresh',
      { method: 'POST' },
      { retryOnUnauthorized: false },
    );
    setAccessToken(body.access_token);
    return body.user;
  } catch {
    setAccessToken(null);
    return null;
  }
}

export async function logout(): Promise<void> {
  try {
    await request<void>('/auth/logout', { method: 'POST' }, { retryOnUnauthorized: false });
  } finally {
    setAccessToken(null);
  }
}

export function savePreferences(prefs: {
  preferred_theme?: ThemePreference;
  preferred_language?: string;
}): Promise<ApiUser> {
  return request<ApiUser>('/auth/me/preferences', {
    method: 'PATCH',
    body: JSON.stringify(prefs),
  });
}

/** Escape hatch for the outbox, which owns its own retry policy. */
export function postRaw(path: string, body: unknown): Promise<unknown> {
  return request<unknown>(path, { method: 'POST', body: JSON.stringify(body) }, {
    retryOnUnauthorized: true,
  });
}

export function listMachines(): Promise<Machine[]> {
  return request<Machine[]>('/masters/machines');
}

export function listSections(): Promise<Section[]> {
  return request<Section[]>('/masters/sections');
}

/** Issue categories — the labels on the downtime Pareto and the trend bands. */
export interface Vocab {
  id: number;
  name: string;
  name_hi: string | null;
  name_hi_latn: string | null;
  sort_order: number;
}

export function listCategories(): Promise<Vocab[]> {
  return request<Vocab[]>('/masters/categories');
}


// ---------------------------------------------------------------------------
// Tickets
// ---------------------------------------------------------------------------

export interface Escalation {
  level: 'none' | 'supervisor' | 'plant_head';
  waiting_minutes: number;
  overdue_minutes: number;
}

export interface Ticket {
  id: string;
  ticket_no: string | null;
  machine_id: number;
  machine_code: string;
  section_id: number;
  section_name: string;
  /**
   * How urgent this ticket is NOW. Derived server-side from how much the
   * machine matters (its A/B/C criticality), not from a priority anyone picked
   * — V5 §5.8 removed that field from the raise form.
   */
  priority: 'Low' | 'Medium' | 'High' | 'Critical';
  /**
   * The OUTCOME: how long the repair actually took, banded per V5 §5.8.
   * Null on every open ticket — which is exactly why `priority` above still
   * exists and does the ranking.
   */
  criticality_calculated: 'Low' | 'Medium' | 'High' | null;
  solve_minutes: number | null;
  status: string;
  description: string;
  current_stage: number;
  stage: string;
  raised_at: string;
  acked_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  raised_by_name: string;
  immediate_correction: string | null;
  why_1: string | null;
  why_2: string | null;
  why_3: string | null;
  preventive_action: string | null;
  root_cause: string | null;
  reopen_count: number;
  rating: number | null;
  /** Set once the record has been corrected (V5 §7). Null means never. */
  last_edited_at: string | null;
  last_edited_by_name: string | null;
  /**
   * Minutes this repair spent waiting rather than being repaired, and which
   * kind of wait is open right now (null when nobody is waiting).
   *
   * Solve Time subtracts this and criticality is banded on the result, so a
   * repair that looks like three hours on the wall and was twenty minutes of
   * work only reads correctly if the waiting is visible next to it.
   */
  pending_minutes: number;
  hold_kind: 'material' | 'correction_pending' | null;
  material_needed: boolean;
  escalation: Escalation;
  flags: string[];
  repeat_count: number;
  downtime_minutes: number | null;
}

export interface ExceptionItem {
  /** null for corporate roles — there is nothing for them to open. */
  ticket_id: string | null;
  kind: string;
  severity: number;
  machine_code: string;
  section_name: string;
  headline: string;
  detail: string;
  /** The parts the sentence was built from, so the client can re-render it. */
  params: Record<string, string | number>;
  since: string | null;
  priority: string | null;
}

export interface ExceptionFeed {
  generated_at: string;
  scope_label: string;
  resolution: 'portfolio' | 'summary' | 'operational';
  items: ExceptionItem[];
  open_total: number;
  escalated_total: number;
}

export interface HandoverTicket {
  ticket_no: string | null;
  machine_code: string;
  stage: string;
  priority: string;
  open_minutes: number;
  note: string;
}

export interface Handover {
  handover_date: string;
  shift_name: string | null;
  prepared_at: string;
  raised_in_shift: number;
  closed_in_shift: number;
  /** Machines actually still stopped. A half-closed ticket is not one. */
  machines_down: number;
  /** Fixed, write-up outstanding. A different backlog with a different owner. */
  rca_pending: number;
  still_open: HandoverTicket[];
  awaiting_root_cause: HandoverTicket[];
  downtime_minutes: number;
}

export interface RootCauseQuality {
  period_start: string;
  period_end: string;
  closed_tickets: number;
  scored_tickets: number;
  usable_tickets: number;
  usable_percent: number;
  average_score: number;
  top_reasons: string[];
}

export interface SectionSummary {
  section_id: number;
  section_name: string;
  sort_order: number;
  open_count: number;
  closed_count: number;
  downtime_minutes: number;
}

export interface BoardSummary {
  generated_at: string;
  scope_label: string;
  resolution: 'portfolio' | 'summary' | 'operational';
  open_total: number;
  escalated_total: number;
  closed_total: number;
  downtime_minutes: number;
  mttr_minutes: number | null;
  sections: SectionSummary[];
}

/**
 * Aggregates every tier can read, including corporate.
 *
 * The board must never derive its totals from `listTickets` — that 403s for a
 * corporate role, and the board would then render "no closed tickets" to a CXO
 * when there were six. "You may not see this" and "there is nothing here" must
 * not look the same.
 */
export function boardSummary(): Promise<BoardSummary> {
  return request<BoardSummary>('/tickets/summary');
}

export interface KpiSet {
  downtime_minutes: number;
  mttr_minutes: number | null;
  mtta_minutes: number | null;
  mtbf_hours: number | null;
  availability_percent: number | null;
  first_time_fix_percent: number | null;
  reopen_percent: number | null;
  root_cause_usable_percent: number | null;
  open_total: number;
  escalated_total: number;
  closed_total: number;
  breakdown_total: number;
  /** "calendar" until Greenlam supplies scheduled operating hours. */
  availability_basis: string;
  /** Rupees lost to downtime. Null while any machine that went down is unpriced. */
  downtime_cost: number | null;
  cost_priced_machines: number;
  cost_total_machines: number;
  ageing: Record<string, number>;
  /** How finished repairs came out: Low / Medium / High (V5 §5.8). */
  criticality_mix: Record<string, number>;
  /** Finished, but never measured — no Correction Started time was recorded. */
  criticality_unmeasured: number;
  downtime_delta: number | null;
  mttr_delta: number | null;
  mtta_delta: number | null;
}

export interface ParetoSlice {
  label: string;
  minutes: number;
  count: number;
  cumulative_percent: number;
}

export interface DowntimeTrend {
  series: string[];
  points: { date: string; values: number[] }[];
}

export interface MachineLoad {
  machine_code: string;
  section_name: string;
  minutes: number;
  count: number;
  failures: number;
  mtbf_hours: number | null;
  last_failure: string | null;
}

export interface MonthPoint {
  month: string;
  count: number;
  downtime_minutes: number;
  mttr_minutes: number | null;
  mtta_minutes: number | null;
}

export interface Analytics {
  generated_at: string;
  period_days: number;
  period_start: string;
  resolution: string;
  scope_label: string;
  machine_count: number;
  kpis: KpiSet;
  pareto_by_cause: ParetoSlice[];
  downtime_trend: DowntimeTrend;
  top_machines: MachineLoad[];
  monthly: MonthPoint[];
  sparklines: Record<string, number[]>;
}

/**
 * What the board is currently looking at (V5 §11.1).
 *
 * All optional, all independent, all combining freely. That is the whole point
 * of the section: the alternative is a fixed report per question, and the list
 * of questions never stops growing.
 *
 * `load_no` only reaches production — a maintenance ticket is raised against a
 * machine, not against a load, and pretending otherwise would silently empty
 * the maintenance half of the screen the moment somebody typed a load number.
 */
export interface BoardFilters {
  section_id?: number | null;
  machine_id?: number | null;
  shift_id?: number | null;
  /** Inclusive plant-local hours. 22→6 is a night window, and wraps. */
  hour_from?: number | null;
  hour_to?: number | null;
  load_no?: string | null;
}

function filterQuery(filters: BoardFilters | undefined, keys: (keyof BoardFilters)[]): string {
  if (!filters) return '';
  let out = '';
  for (const key of keys) {
    const value = filters[key];
    // 0 is a real hour. `!value` would drop midnight.
    if (value === null || value === undefined || value === '') continue;
    out += `&${key}=${encodeURIComponent(String(value))}`;
  }
  return out;
}

/** Everything the board draws, in one round trip. Readable by every tier. */
export function analytics(days = 90, filters?: BoardFilters): Promise<Analytics> {
  const q = filterQuery(filters, ['section_id', 'machine_id', 'shift_id', 'hour_from', 'hour_to']);
  return request<Analytics>(`/tickets/analytics?days=${days}${q}`);
}

export function listTickets(state: 'open' | 'closed' | 'all' = 'open'): Promise<Ticket[]> {
  return request<Ticket[]>(`/tickets?state=${state}`);
}

export function getTicket(id: string): Promise<Ticket> {
  return request<Ticket>(`/tickets/${id}`);
}

/** Available to every tier. What comes back is redacted by role. */
export function exceptions(): Promise<ExceptionFeed> {
  return request<ExceptionFeed>('/tickets/exceptions');
}

export function handover(): Promise<Handover> {
  return request<Handover>('/tickets/handover');
}

export function rootCauseQuality(days = 30): Promise<RootCauseQuality> {
  return request<RootCauseQuality>(`/tickets/root-cause-quality?days=${days}`);
}

export interface RaiseTicketInput {
  machine_id: number;
  description: string;
  raised_via?: string;
  /**
   * Not sent any more. The server derives urgency from the machine (V5 §5.8),
   * and still accepts this key so a ticket queued offline by an older build of
   * the app syncs rather than being rejected on a floor with no signal.
   */
  priority?: string;
}

export function raiseTicket(input: RaiseTicketInput): Promise<Ticket> {
  return request<Ticket>('/tickets', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export interface TicketEventInput {
  type: string;
  /** MATERIAL_RECORDED: 'none' means the repair needs nothing from stores. */
  material_source?: 'store' | 'purchase' | 'none';
  material_name?: string;
  material_bin?: string;
  immediate_correction?: string;
  why_1?: string;
  why_2?: string;
  why_3?: string;
  preventive_action?: string;
  rating?: number;
}

export function advanceTicket(id: string, event: TicketEventInput): Promise<Ticket> {
  return request<Ticket>(`/tickets/${id}/events`, {
    method: 'POST',
    body: JSON.stringify(event),
  });
}

// ---------------------------------------------------------------------------
// Individual performance
//
// The API refuses to return anyone else's numbers to a peer or to any
// corporate tier — 404, not 403 — so nothing here can leak what it never
// receives. See api/app/routers/people.py for the five enforced rules.
// ---------------------------------------------------------------------------

export interface Performance {
  user_id: number;
  name: string;
  role: string;
  period_days: number;
  period_start: string;
  period_end: string;
  raised_count: number;
  acknowledged_count: number;
  resolved_count: number;
  closed_count: number;
  avg_ack_minutes: number | null;
  avg_repair_minutes: number | null;
  first_time_fix_percent: number | null;
  root_cause_avg_score: number | null;
  workload_by_priority: Record<string, number>;
  is_self: boolean;
}

export interface TeamMember {
  user_id: number;
  name: string;
  role: string;
  raised_count: number;
  resolved_count: number;
  avg_ack_minutes: number | null;
  avg_repair_minutes: number | null;
  first_time_fix_percent: number | null;
  root_cause_avg_score: number | null;
}

export interface TeamPerformance {
  period_days: number;
  generated_at: string;
  member_count: number;
  team_avg_repair_minutes: number | null;
  total_resolved: number;
  members: TeamMember[];
}

/** Always available, to everyone, with no capability required. */
export function myPerformance(days = 30): Promise<Performance> {
  return request<Performance>(`/people/me/performance?days=${days}`);
}

export function teamPerformance(days = 30): Promise<TeamPerformance> {
  return request<TeamPerformance>(`/people/team?days=${days}`);
}

// ---------------------------------------------------------------------------
// Production
// ---------------------------------------------------------------------------

export interface SegmentRow {
  label: string;
  produced: number;
  rejected: number;
  reject_percent: number;
}

export interface RejectSlice {
  label: string;
  quantity: number;
  percent: number;
  cumulative_percent: number;
}

export interface ProductionAnalytics {
  generated_at: string;
  period_days: number;
  period_start: string;
  resolution: string;
  total_produced: number;
  total_rejected: number;
  reject_percent: number;
  target_total: number | null;
  output_vs_target_percent: number | null;
  reject_pareto: RejectSlice[];
  by_texture: SegmentRow[];
  by_shift: SegmentRow[];
  by_machine: SegmentRow[];
  by_section: SegmentRow[];
  daily: { date: string; produced: number; rejected: number; reject_percent: number }[];
  breakdown_correlation: {
    machine_code: string;
    reject_percent_near_breakdown: number;
    reject_percent_otherwise: number;
    lift_percent: number;
    breakdowns: number;
  }[];
}

export interface ProductionRow {
  id: string;
  log_date: string;
  machine_code: string;
  shift_name: string | null;
  load_no: string | null;
  size: string;
  texture: string;
  produced_qty: number;
  rejected_qty: number;
  reject_reason: string | null;
  target_qty: number | null;
  reject_percent: number;
  logged_by_name: string;
  /** NULL while it is a draft (V5 §6.3). */
  submitted_at: string | null;
  last_edited_at: string | null;
  last_edited_by_name: string | null;
}

/** A draft, plus the ids the form needs to come back the way it was left. */
export interface ProductionDraft extends ProductionRow {
  machine_id: number | null;
  shift_id: number | null;
  design_id: number | null;
  size_id: number | null;
  texture_id: number | null;
  thickness_id: number | null;
  reject_reason_id: number | null;
  roll_no: string | null;
}

export interface RejectReason {
  id: number;
  name: string;
  name_hi: string | null;
  name_hi_latn: string | null;
  sort_order: number;
}

export interface Shift {
  id: number;
  name: string;
  start_time: string;
  end_time: string;
}

/** Aggregates. Readable by every tier — no names, no individual rows. */
export function productionAnalytics(
  days = 90,
  filters?: BoardFilters,
): Promise<ProductionAnalytics> {
  const q = filterQuery(filters, ['section_id', 'machine_id', 'shift_id', 'load_no']);
  return request<ProductionAnalytics>(`/production/analytics?days=${days}${q}`);
}

export function listProduction(days = 30): Promise<ProductionRow[]> {
  return request<ProductionRow[]>(`/production?days=${days}`);
}

export function listRejectReasons(): Promise<RejectReason[]> {
  return request<RejectReason[]>('/masters/reject-reasons');
}

export function listShifts(): Promise<Shift[]> {
  return request<Shift[]>('/masters/shifts');
}

export interface LogProductionInput {
  machine_id: number;
  shift_id?: number | null;
  /**
   * Legacy free text, kept so the Excel import keeps round-tripping.
   *
   * Optional because not every process has them — the AC room conditions
   * treated paper for a load and makes neither a size nor a texture.
   */
  size?: string;
  texture?: string;
  /** What the analysis actually groups by. */
  design_id?: number | null;
  size_id?: number | null;
  texture_id?: number | null;
  thickness_id?: number | null;
  /** The roll these sheets were pressed from — the traceability link. */
  roll_no?: string | null;
  /**
   * The SAP load plan this output belongs to. Required at the press and
   * rejected there if absent; optional everywhere downstream.
   */
  load_no?: string | null;
  produced_qty: number;
  rejected_qty: number;
  reject_reason_id?: number | null;
  target_qty?: number | null;
  /**
   * Save without finishing (V5 §6.3).
   *
   * A draft is private to whoever started it, reaches no dashboard and no
   * workbook, and is never tagged "Edited" however often it changes. The
   * validation that protects the numbers runs at `submitProduction`, not here
   * — a rule applied to a half-filled form would refuse the exact state this
   * exists to hold.
   */
  draft?: boolean;
}

export function logProduction(input: LogProductionInput): Promise<ProductionRow> {
  return request<ProductionRow>('/production', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

/** My own unfinished entries. Nobody else's are ever returned. */
export function listDrafts(): Promise<ProductionDraft[]> {
  return request<ProductionDraft[]>('/production/drafts');
}

/** Change a draft. Freely, as often as you like — nothing is audited yet. */
export function updateDraft(
  id: string,
  changes: Partial<LogProductionInput>,
): Promise<ProductionDraft> {
  return request<ProductionDraft>(`/production/${id}`, {
    method: 'PUT',
    body: JSON.stringify(changes),
  });
}

/** The Done press. Everything deferred at save is checked here. */
export function submitProduction(id: string): Promise<ProductionRow> {
  return request<ProductionRow>(`/production/${id}/submit`, { method: 'POST' });
}

/** Throw a draft away. A submitted entry can never be deleted. */
export function discardDraft(id: string): Promise<void> {
  return request<void>(`/production/${id}`, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// QR
// ---------------------------------------------------------------------------

export interface ScanResolution {
  machine_id: number;
  machine_code: string;
  machine_name: string;
  section_id: number;
  section_name: string;
  short_code: string;
  criticality: string;
}

/** Accepts the full QR token or the short fallback code printed on the label. */
export function resolveScan(
  token: string,
  source: 'in_app' | 'native_camera' = 'in_app',
): Promise<ScanResolution> {
  return request<ScanResolution>(`/s/${encodeURIComponent(token)}?source=${source}`);
}

/** Closes the loop so the pilot review can quote QR adoption. Never blocks. */
export function recordScanOutcome(
  machineId: number,
  outcome: 'ticket' | 'production' | 'abandoned',
): Promise<{ recorded: boolean }> {
  return request<{ recorded: boolean }>(
    `/qr/scans/${machineId}/outcome?resulted_in=${outcome}`,
    { method: 'POST' },
  );
}


// ---------------------------------------------------------------------------
// Excel register import
// ---------------------------------------------------------------------------

export interface RowIssue {
  row: number;
  column: string;
  message: string;
  severity: 'error' | 'warning';
}

export interface PlannedRow {
  row: number;
  action: 'create' | 'update' | 'skip';
  machine_code: string;
  date: string;
  minutes: number;
  description: string;
  reason: string | null;
}

export interface ImportPlan {
  file_hash: string;
  sheet_name: string;
  rows_read: number;
  creates: number;
  updates: number;
  skips: number;
  errors: number;
  can_commit: boolean;
  missing_columns: string[];
  unknown_machines: string[];
  issues: RowIssue[];
  issues_total: number;
  sample: PlannedRow[];
  sample_total: number;
}

export interface ImportRun {
  id: number;
  filename: string;
  status: string;
  rows_read: number;
  created_count: number;
  updated_count: number;
  skipped_count: number;
  error_count: number;
  uploaded_by: string;
  created_at: string;
}

export interface ImportFreshness {
  last_import_at: string | null;
  stale: boolean;
  never: boolean;
  hours_ago?: number;
  rows?: number;
}

function fileBody(file: File): FormData {
  const form = new FormData();
  form.append('file', file);
  return form;
}

/** Dry run. Reports what importing would do and writes nothing. */
export function previewImport(file: File): Promise<ImportPlan> {
  return request<ImportPlan>('/imports/preview', { method: 'POST', body: fileBody(file) });
}

/** Applies the register. Only ever called after the user has seen a preview. */
export function commitImport(file: File): Promise<ImportPlan> {
  return request<ImportPlan>('/imports/commit', { method: 'POST', body: fileBody(file) });
}

export function importHistory(): Promise<ImportRun[]> {
  return request<ImportRun[]>('/imports');
}

export function importFreshness(): Promise<ImportFreshness> {
  return request<ImportFreshness>('/imports/freshness');
}

// ---------------------------------------------------------------------------
// Impregnation — paper rolls
// ---------------------------------------------------------------------------

export interface PaperGrade extends Vocab {
  rc_min: string | null;
  rc_max: string | null;
  vc_min: string | null;
  vc_max: string | null;
}

export interface ImpregnationRoll {
  id: string;
  machine_id: number;
  shift_id: number | null;
  log_date: string;
  roll_no: string;
  gsm: string | null;
  thickness_before: string | null;
  paper_grade_id: number | null;
  paper_grade_name: string | null;
  paper_company_id: number | null;
  cut_size_id: number | null;
  thickness_after: string | null;
  rc_percent: string | null;
  vc_percent: string | null;
  /** Decided by the server at write time, against the grade's window. */
  out_of_spec: boolean;
  spec_note: string | null;
  rc_min: string | null;
  rc_max: string | null;
  vc_min: string | null;
  vc_max: string | null;
}

export interface RollTrace {
  roll: ImpregnationRoll;
  runs: number;
  produced: number;
  rejected: number;
  reject_percent: number;
}

export interface MachinePerformanceRow {
  machine_id: number;
  machine_code: string;
  section_name: string;
  downtime_minutes: number;
  breakdowns: number;
  mttr_minutes: number | null;
  mtbf_hours: number | null;
  produced: number;
  rejected: number;
  reject_percent: number | null;
  rolls: number;
  avg_rc: number | null;
  avg_vc: number | null;
  out_of_spec_rolls: number;
}

export interface RollQuality {
  linked_runs: number;
  in_spec_reject_percent: number | null;
  out_of_spec_reject_percent: number | null;
  lift_percent: number | null;
  enough_data: boolean;
}

export function listPaperGrades(): Promise<PaperGrade[]> {
  return request<PaperGrade[]>('/masters/paper-grades');
}

export function listPaperCompanies(): Promise<Vocab[]> {
  return request<Vocab[]>('/masters/paper-companies');
}

export function listDesigns(): Promise<Vocab[]> {
  return request<Vocab[]>('/masters/designs');
}

export function listSizes(): Promise<Vocab[]> {
  return request<Vocab[]>('/masters/sizes');
}

export function listTextures(): Promise<Vocab[]> {
  return request<Vocab[]>('/masters/textures');
}

export function listThicknesses(): Promise<Vocab[]> {
  return request<Vocab[]>('/masters/thicknesses');
}

export interface ImpregnationInput {
  machine_id: number;
  shift_id?: number | null;
  log_date: string;
  roll_no: string;
  gsm?: number | null;
  thickness_before?: number | null;
  paper_grade_id?: number | null;
  paper_company_id?: number | null;
  cut_size_id?: number | null;
  thickness_after?: number | null;
  rc_percent?: number | null;
  vc_percent?: number | null;
  /** The resin batch this roll drew from. Completes the trace. */
  resin_batch_id?: string | null;
}

export interface ResinBatchInput {
  id?: string;
  machine_id: number;
  shift_id?: number | null;
  /** Optional — the resin register on the floor is not confirmed yet. */
  batch_no?: string | null;
  log_date?: string | null;
  quantity?: string | null;
  unit_of_measure?: string | null;
  accepted_qty?: string | null;
  rejected_qty?: string | null;
  reject_reason_id?: number | null;
  notes?: string | null;
}

export interface ResinBatch {
  id: string;
  machine_id: number;
  machine_code: string;
  batch_no: string | null;
  log_date: string;
  quantity: string | null;
  unit_of_measure: string | null;
  accepted_qty: string | null;
  rejected_qty: string | null;
}

/** Recent resin batches, for the roll form's picker. */
export function listResinBatches(limit = 50): Promise<ResinBatch[]> {
  return request(`/production/resin-batches?limit=${limit}`);
}

/** Record a batch out of a resin kettle. The batch number is what an
    impregnated roll will later point at, so the server refuses a duplicate. */
export function logResinBatch(body: ResinBatchInput): Promise<ResinBatch> {
  return request('/production/resin-batches', { method: 'POST', body: JSON.stringify(body) });
}

export function logRoll(body: ImpregnationInput): Promise<ImpregnationRoll> {
  return request<ImpregnationRoll>('/impregnation', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function listRolls(days = 30, onlyOutOfSpec = false): Promise<ImpregnationRoll[]> {
  return request<ImpregnationRoll[]>(
    `/impregnation?days=${days}&only_out_of_spec=${onlyOutOfSpec}`,
  );
}

export function recentRollNumbers(): Promise<string[]> {
  return request<string[]>('/impregnation/recent-rolls');
}

export function traceRoll(rollNo: string): Promise<RollTrace> {
  return request<RollTrace>(`/impregnation/trace/${encodeURIComponent(rollNo)}`);
}

export function machinePerformance(days = 90): Promise<MachinePerformanceRow[]> {
  return request<MachinePerformanceRow[]>(`/production/machine-performance?days=${days}`);
}

export function rollQuality(days = 90): Promise<RollQuality> {
  return request<RollQuality>(`/production/roll-quality?days=${days}`);
}

// ---------------------------------------------------------------------------
// The nightly workbook
// ---------------------------------------------------------------------------

export interface ExportStatus {
  available: boolean;
  stale: boolean;
  filename: string | null;
  built_at: string | null;
  size_kb: number | null;
  hours_ago: number | null;
}

export function exportStatus(): Promise<ExportStatus> {
  return request<ExportStatus>('/exports/status');
}

/**
 * Download the workbook.
 *
 * Fetched as a blob rather than pointed at with a plain `<a href>`, because
 * the file sits behind a bearer token — a raw link would send no Authorization
 * header and land on a 401 that the browser renders as a broken download with
 * no explanation. This way a failure is a message on the page.
 */
export async function downloadWorkbook(): Promise<void> {
  const fetchFile = () =>
    fetch(`${BASE}/exports/latest`, {
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
      credentials: 'same-origin',
    });

  let response = await fetchFile();
  // The same one transparent refresh every other call gets. Skipping it here
  // meant a 30-minute-old session failed the download outright — and the
  // person clicking is usually the one who has had the board open longest.
  // The refresh is single-flight, so this cannot trip reuse detection.
  if (response.status === 401) {
    const refreshed = await refresh().catch(() => null);
    if (refreshed) response = await fetchFile();
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .then((b: { detail?: string }) => b.detail)
      .catch(() => undefined);
    throw new ApiError(response.status, detail ?? 'Could not download the workbook.');
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const name =
    response.headers
      .get('Content-Disposition')
      ?.match(/filename="?([^"]+)"?/)?.[1] ?? 'greenlam-tracker.xlsx';

  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoking immediately can cancel the download in Safari; a tick is enough.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------------------------------------------------------------------------
// Editing the master vocabularies
// ---------------------------------------------------------------------------

export interface VocabWrite {
  name: string;
  name_hi?: string | null;
  name_hi_latn?: string | null;
  sort_order?: number;
}

export interface PaperGradeWrite extends VocabWrite {
  rc_min?: number | null;
  rc_max?: number | null;
  vc_min?: number | null;
  vc_max?: number | null;
}

/** One creator for the five identical vocabularies. */
export function createVocab(
  kind: 'designs' | 'sizes' | 'textures' | 'thicknesses' | 'paper-companies',
  body: VocabWrite,
): Promise<Vocab> {
  return request<Vocab>(`/masters/${kind}`, { method: 'POST', body: JSON.stringify(body) });
}

export function createPaperGrade(body: PaperGradeWrite): Promise<PaperGrade> {
  return request<PaperGrade>('/masters/paper-grades', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// Machine setup — the three Phase 0 answers
// ---------------------------------------------------------------------------

export interface MachineSetup {
  id: number;
  code: string;
  name: string;
  section_name: string;
  criticality: string;
  hourly_downtime_cost: number | null;
  scheduled_hours_per_day: string | null;
}

export function machineSetup(): Promise<MachineSetup[]> {
  return request<MachineSetup[]>('/masters/machines/setup');
}

/** Patches only what is sent — the three answers arrive from three people. */
export function updateMachineSetup(
  id: number,
  body: Partial<Record<'criticality' | 'hourly_downtime_cost' | 'scheduled_hours_per_day', unknown>>,
): Promise<MachineSetup> {
  return request<MachineSetup>(`/masters/machines/${id}/setup`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}


// ---------------------------------------------------------------------------
// Corrections (V5 §7)
// ---------------------------------------------------------------------------

export interface CorrectionEntry {
  field: string;
  old_value: string | null;
  new_value: string | null;
  reason: string | null;
  corrected_by_name: string;
  corrected_at: string;
  /** True when an admin made the change after the self-edit window closed. */
  outside_window: boolean;
}

export interface CorrectResult {
  ok: boolean;
  /** The fields that actually moved. `0` when the values sent matched what was there. */
  applied: string[] | number;
  outside_window?: boolean;
  repeat?: boolean;
  unchanged?: boolean;
}

/**
 * Fix a mistake on a record that is already final.
 *
 * NOT the same as reopening a ticket. This changes what a field says and
 * nothing else — the ticket stays closed, `closed_at` does not move, and the
 * previous value is kept. Reopen is `reopenTicket`, and the two are separate
 * buttons on purpose.
 */
export function correctTicket(
  ticketId: string,
  changes: Record<string, unknown>,
  reason?: string,
): Promise<CorrectResult> {
  return request<CorrectResult>(`/tickets/${ticketId}/correct`, {
    method: 'POST',
    // A client-generated id, so a retry over a dropped connection cannot apply
    // the same correction twice.
    body: JSON.stringify({ changes, reason, submission_id: crypto.randomUUID() }),
  });
}

export function ticketCorrections(ticketId: string): Promise<CorrectionEntry[]> {
  return request<CorrectionEntry[]>(`/tickets/${ticketId}/corrections`);
}

export function correctProduction(
  logId: string,
  changes: Record<string, unknown>,
  reason?: string,
): Promise<CorrectResult> {
  return request<CorrectResult>(`/production/${logId}/correct`, {
    method: 'POST',
    body: JSON.stringify({ changes, reason, submission_id: crypto.randomUUID() }),
  });
}

export function productionCorrections(logId: string): Promise<CorrectionEntry[]> {
  return request<CorrectionEntry[]>(`/production/${logId}/corrections`);
}


// ---------------------------------------------------------------------------
// Access areas, signup and approval (V5 §3)
// ---------------------------------------------------------------------------

export interface PendingUser {
  id: number;
  employee_id: string;
  name: string;
  phone: string | null;
  signed_up_at: string;
}

/** Creates an account holding nothing. It can sign in and must then wait. */
export function signup(body: {
  employee_id: string;
  name: string;
  pin: string;
  phone?: string | null;
}): Promise<ApiUser> {
  return request<ApiUser>('/auth/signup', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** Everyone at this plant. Admin only — the server refuses otherwise. */
export function listUsers(): Promise<ApiUser[]> {
  return request<ApiUser[]>('/masters/users');
}

export function pendingUsers(): Promise<PendingUser[]> {
  return request<PendingUser[]>('/access/pending');
}

export function approveUser(userId: number, areas: string[]): Promise<ApiUser> {
  return request<ApiUser>(`/access/users/${userId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ areas }),
  });
}

/**
 * The areas this person should hold afterwards — absolute, not a delta.
 * An empty list revokes their access entirely.
 */
export function setUserAreas(userId: number, areas: string[]): Promise<ApiUser> {
  return request<ApiUser>(`/access/users/${userId}/areas`, {
    method: 'PUT',
    body: JSON.stringify({ areas }),
  });
}


// ---------------------------------------------------------------------------
// Push notifications (V5 §9)
// ---------------------------------------------------------------------------

export interface PushStatus {
  /** Empty when the plant has not generated VAPID keys. */
  public_key: string;
  enabled: boolean;
  /** How many devices of this person currently hold a live subscription. */
  devices: number;
}

export interface PushSubscriptionBody {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

export function pushStatus(): Promise<PushStatus> {
  return request<PushStatus>('/push/status');
}

export function subscribeToPush(body: PushSubscriptionBody): Promise<unknown> {
  return request('/push/subscribe', { method: 'POST', body: JSON.stringify(body) });
}

export function unsubscribeFromPush(body: PushSubscriptionBody): Promise<unknown> {
  return request('/push/subscribe', { method: 'DELETE', body: JSON.stringify(body) });
}


// ---------------------------------------------------------------------------
// Reassigning a ticket (V5 §3, §15.5)
// ---------------------------------------------------------------------------

export interface Assignee {
  user_id: number;
  name: string;
  employee_id: string;
  /** Everything they hold that is not closed — assigned, in repair, or awaiting RCA. */
  open_tickets: number;
}

/** Everyone holding Maintenance, least loaded first. */
export function assignableTo(): Promise<Assignee[]> {
  return request<Assignee[]>('/tickets/assignable-to');
}

/**
 * Move a ticket to somebody else.
 *
 * Both an engineer passing their own on at changeover and a manager assigning
 * work they are not doing themselves — the server tells the two apart by
 * capability, so the client does not have to.
 */
export function handoffTicket(ticketId: string, toUserId: number): Promise<unknown> {
  return request(`/tickets/${ticketId}/handoff`, {
    method: 'POST',
    body: JSON.stringify({ to_user_id: toUserId, submission_id: crypto.randomUUID() }),
  });
}


// ---------------------------------------------------------------------------
// The pending clock — waiting for a part, or still broken (V5 §5.2)
// ---------------------------------------------------------------------------

/**
 * Stop the repair clock.
 *
 * `material` is waiting for a part. `correction_pending` is "I tried and it is
 * still broken", which V5 §5.4 requires a typed reason for — a claim that a fix
 * did not hold needs a sentence attached to it.
 *
 * This is what makes Solve Time mean anything. Without it every wait counts as
 * repair work, and a twenty-minute fix that waited three hours for a bearing is
 * banded as a three-hour repair.
 */
export function holdTicket(
  ticketId: string,
  kind: 'material' | 'correction_pending',
  reason?: string,
): Promise<unknown> {
  return request(`/tickets/${ticketId}/hold`, {
    method: 'POST',
    body: JSON.stringify({ kind, reason, submission_id: crypto.randomUUID() }),
  });
}

/** Start it again. Closes whichever window is open. */
export function resumeTicket(ticketId: string): Promise<unknown> {
  return request(`/tickets/${ticketId}/resume`, {
    method: 'POST',
    body: JSON.stringify({ submission_id: crypto.randomUUID() }),
  });
}


// ---------------------------------------------------------------------------
// Photos (V5 §5.4, §6.2)
// ---------------------------------------------------------------------------

export type PhotoKind = 'material' | 'part_arrived' | 'pack_order' | 'other';

export interface Photo {
  id: number;
  kind: PhotoKind | null;
  mime_type: string | null;
  size_bytes: number | null;
  uploaded_at: string;
  uploaded_by_name: string | null;
}

/**
 * Upload a photo against a ticket.
 *
 * `part_arrived` is the one the server insists on: a parts hold cannot end
 * without one taken during that hold (V5 §5.4), because ending it restarts the
 * repair clock and nobody else witnesses the claim.
 */
export function uploadTicketPhoto(
  ticketId: string,
  kind: PhotoKind,
  photo: Blob,
): Promise<Photo> {
  const form = new FormData();
  form.append('file', photo, 'photo.jpg');
  // No Content-Type header — the browser has to set the multipart boundary,
  // and naming it here produces a body the server cannot parse.
  return request<Photo>(`/photos/ticket/${ticketId}?kind=${kind}`, {
    method: 'POST',
    body: form,
  });
}

export function uploadProductionPhoto(logId: string, photo: Blob): Promise<Photo> {
  const form = new FormData();
  form.append('file', photo, 'photo.jpg');
  return request<Photo>(`/photos/production/${logId}?kind=pack_order`, {
    method: 'POST',
    body: form,
  });
}

export function ticketPhotos(ticketId: string): Promise<Photo[]> {
  return request<Photo[]>(`/photos/ticket/${ticketId}`);
}

/** Where the bytes are. Immutable, so the browser caches it hard. */
export function photoUrl(photoId: number): string {
  return `${BASE}/photos/${photoId}`;
}
