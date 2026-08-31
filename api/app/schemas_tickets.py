"""Ticket request and response shapes.

Kept apart from `schemas.py` because the ticket surface is where the redaction
rules live: a corporate role gets counts and rollups, a floor role gets the
ticket. Two read models, chosen by resolution, rather than one model with
fields conditionally blanked — a blanked field is one refactor away from
leaking.
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TicketCreate(BaseModel):
    # Client-generated UUIDv7 so a ticket can be raised offline and retried
    # without duplicating. Optional while the PWA outbox is Phase 3.
    id: UUID | None = None
    machine_id: int
    category_id: int | None = None
    priority: str = Field(default="Medium", pattern=r"^(Low|Medium|High|Critical)$")
    description: str = Field(min_length=1)
    location: str | None = Field(default=None, max_length=160)
    downtime_type: str = Field(
        default="breakdown", pattern=r"^(breakdown|planned|changeover|no_downtime)$"
    )
    raised_via: str = Field(default="manual", pattern=r"^(qr|manual|web)$")
    shift_id: int | None = None
    input_language: str | None = Field(default=None, pattern=r"^(en|hi|hi-Latn)$")
    client_ts: datetime | None = None


class TicketEventCreate(BaseModel):
    """One immutable step. The server derives ticket state by replaying these."""

    event_id: UUID | None = None
    type: str = Field(
        pattern=r"^(ACKNOWLEDGED|MATERIAL_RECORDED|REPAIR_STARTED|RESOLVED|"
        r"DIAGNOSED|CLOSED|REOPENED)$"
    )
    client_ts: datetime | None = None
    device_id: str | None = Field(default=None, max_length=100)

    # --- RESOLVED ---
    immediate_correction: str | None = None

    # --- DIAGNOSED: three prompted levels, not one free-text box ---
    why_1: str | None = None
    why_2: str | None = None
    why_3: str | None = None
    preventive_action: str | None = None
    sheets_after_sanding: str | None = Field(default=None, max_length=80)

    # --- MATERIAL_RECORDED ---
    material_source: str | None = Field(default=None, pattern=r"^(store|purchase|none)$")
    material_name: str | None = Field(default=None, max_length=200)
    material_qty: float | None = None
    material_cost: float | None = None
    material_bin: str | None = Field(default=None, max_length=80)
    material_vendor: str | None = Field(default=None, max_length=160)
    material_po: str | None = Field(default=None, max_length=80)

    # --- CLOSED ---
    rating: int | None = Field(default=None, ge=1, le=5)

    # --- REOPENED ---
    reason: str | None = None


class EscalationRead(BaseModel):
    level: str
    waiting_minutes: float
    overdue_minutes: float


class TicketRead(BaseModel):
    """Full operational detail. Gated behind `require_operational`."""

    id: UUID
    ticket_no: str | None
    machine_id: int
    machine_code: str
    section_id: int
    section_name: str
    category_id: int | None
    priority: str
    description: str
    location: str | None
    downtime_type: str
    raised_via: str
    current_stage: int
    stage: str

    raised_at: datetime
    acked_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None

    raised_by: int
    raised_by_name: str

    immediate_correction: str | None
    why_1: str | None
    why_2: str | None
    why_3: str | None
    preventive_action: str | None
    root_cause: str | None
    sheets_after_sanding: str | None

    reopen_count: int
    rating: int | None

    # Derived on read, never stored.
    escalation: EscalationRead
    flags: list[str]
    repeat_count: int
    downtime_minutes: float | None


class TicketSummary(BaseModel):
    """What a corporate role sees instead of a ticket.

    No description, no names, no free text. A CXO gets the shape of the
    problem; the ticket itself stays on the floor.
    """

    machine_code: str
    section_name: str
    priority: str
    stage: str
    open_minutes: float
    flags: list[str]


class SectionSummary(BaseModel):
    section_id: int
    section_name: str
    sort_order: int
    open_count: int
    closed_count: int
    downtime_minutes: float


class BoardSummary(BaseModel):
    """Aggregates every tier may read, including the corporate ones.

    This exists because the alternative was worse: the board used to derive its
    totals from the ticket list, which 403s for a corporate role, so a CXO saw
    "no closed tickets" when there were six. A dashboard that reports zero
    downtime to the person most able to act on it is worse than no dashboard —
    "you may not see this" and "there is nothing here" must never render the
    same way.

    No ticket ids, no descriptions, no names. Counts and minutes only.
    """

    generated_at: datetime
    scope_label: str
    resolution: str
    open_total: int
    escalated_total: int
    closed_total: int
    downtime_minutes: float
    mttr_minutes: float | None
    sections: list[SectionSummary]


class ExceptionItem(BaseModel):
    """One line in the "what needs you" feed."""

    ticket_id: UUID | None
    kind: str  # escalated | ageing | repeat | reopened | awaiting_root_cause | pm_due
    severity: int
    machine_code: str
    section_name: str
    headline: str
    detail: str
    # The parts `headline`/`detail` were built from, so a client can re-render
    # the same sentence in its own language instead of showing this English one.
    params: dict[str, str | int] = {}
    since: datetime | None
    # Only populated for roles that may see it. None for corporate tiers.
    priority: str | None = None


class ExceptionFeed(BaseModel):
    generated_at: datetime
    scope_label: str
    resolution: str
    items: list[ExceptionItem]
    open_total: int
    escalated_total: int


class HandoverTicket(BaseModel):
    ticket_no: str | None
    machine_code: str
    stage: str
    priority: str
    open_minutes: float
    note: str


class HandoverRead(BaseModel):
    """What the outgoing shift leaves for the incoming one."""

    handover_date: date
    shift_id: int | None
    shift_name: str | None
    prepared_at: datetime
    raised_in_shift: int
    closed_in_shift: int
    still_open: list[HandoverTicket]
    awaiting_root_cause: list[HandoverTicket]
    downtime_minutes: float
    acknowledged_by: int | None = None
    acknowledged_at: datetime | None = None


class RootCauseQualityRead(BaseModel):
    """Team-level only. Addendum §4.1 — never per technician upward."""

    period_start: date
    period_end: date
    closed_tickets: int
    scored_tickets: int
    usable_tickets: int
    usable_percent: float
    average_score: float
    top_reasons: list[str]


# ---------------------------------------------------------------------------
# Analytics — the board's charts and full KPI set
# ---------------------------------------------------------------------------
class KpiSet(BaseModel):
    downtime_minutes: float
    mttr_minutes: float | None
    mtta_minutes: float | None
    mtbf_hours: float | None
    availability_percent: float | None
    first_time_fix_percent: float | None
    reopen_percent: float | None
    root_cause_usable_percent: float | None
    open_total: int
    escalated_total: int
    closed_total: int
    breakdown_total: int
    # "calendar" until Greenlam supplies scheduled operating hours. The UI says
    # so on the tile rather than presenting an assumption as a measurement.
    availability_basis: str
    # Rupees lost to downtime. None while any machine that actually went down
    # is unpriced — the counts below let the board say how far off it is
    # rather than showing a total that is silently low.
    downtime_cost: float | None = None
    cost_priced_machines: int = 0
    cost_total_machines: int = 0
    ageing: dict[str, int]
    downtime_delta: float | None
    mttr_delta: float | None
    mtta_delta: float | None


class ParetoSlice(BaseModel):
    label: str
    minutes: float
    count: int
    cumulative_percent: float


class TrendPoint(BaseModel):
    date: str
    values: list[float]


class DowntimeTrend(BaseModel):
    series: list[str]
    points: list[TrendPoint]


class MachineLoad(BaseModel):
    machine_code: str
    section_name: str
    minutes: float
    count: int
    failures: int
    mtbf_hours: float | None
    last_failure: str | None


class MonthPoint(BaseModel):
    month: str
    count: int
    downtime_minutes: float
    mttr_minutes: float | None
    mtta_minutes: float | None


class Analytics(BaseModel):
    """Everything the board draws, in one response.

    One round trip on purpose: Render's free tier cold-starts in 30-60s, and
    five parallel requests against a sleeping instance is five chances to time
    out instead of one.
    """

    generated_at: datetime
    period_days: int
    period_start: date
    resolution: str
    scope_label: str
    machine_count: int
    kpis: KpiSet
    pareto_by_cause: list[ParetoSlice]
    downtime_trend: DowntimeTrend
    top_machines: list[MachineLoad]
    monthly: list[MonthPoint]
    sparklines: dict[str, list[float]]
