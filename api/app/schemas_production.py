"""Production logging shapes.

Same split as tickets: `ProductionRead` is a row and therefore operational
detail, while `ProductionAnalytics` is aggregates every tier may read.
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProductionCreate(BaseModel):
    machine_id: int
    shift_id: int | None = None
    log_date: date | None = None
    # Legacy free text. Retained so the Excel round-trip and existing rows
    # keep working; the *_id fields below are what any GROUP BY should use.
    size: str = Field(min_length=1, max_length=80)
    texture: str = Field(min_length=1, max_length=80)
    thickness: str | None = Field(default=None, max_length=40)

    design_id: int | None = None
    size_id: int | None = None
    texture_id: int | None = None
    thickness_id: int | None = None
    # The roll these sheets came from, by number rather than by id — the
    # operator reads a number off the roll, and asking the client to resolve it
    # first would mean a lookup on a phone that may be offline.
    roll_no: str | None = Field(default=None, max_length=64)

    produced_qty: int = Field(ge=0)
    rejected_qty: int = Field(default=0, ge=0)
    reject_reason_id: int | None = None
    target_qty: int | None = Field(default=None, ge=0)


class ProductionRead(BaseModel):
    id: UUID
    log_date: date
    machine_code: str
    shift_name: str | None
    size: str
    texture: str
    produced_qty: int
    rejected_qty: int
    reject_reason: str | None
    target_qty: int | None
    reject_percent: float
    logged_by_name: str


class RejectSlice(BaseModel):
    label: str
    quantity: int
    percent: float
    cumulative_percent: float


class SegmentRow(BaseModel):
    """One slice of a dimension — a texture, a shift, a machine.

    Sorted worst-first by the caller. Segments are where root causes hide: a
    texture rejecting at twice the rate of the others is a finding you can only
    see because the dimension was recorded.
    """

    label: str
    produced: int
    rejected: int
    reject_percent: float


class ProductionAnalytics(BaseModel):
    generated_at: datetime
    period_days: int
    period_start: date
    resolution: str

    total_produced: int
    total_rejected: int
    reject_percent: float
    target_total: int | None
    output_vs_target_percent: float | None

    reject_pareto: list[RejectSlice]
    by_texture: list[SegmentRow]
    by_shift: list[SegmentRow]
    by_machine: list[SegmentRow]
    by_section: list[SegmentRow]
    daily: list[dict]

    # Spec §6.1's "one derived metric worth building": reject-rate lift in the
    # ±48h around a machine's breakdowns. A leading indicator, if it holds.
    breakdown_correlation: list[dict]


class MachinePerformance(BaseModel):
    """One machine, both halves of its story on the same row.

    A machine can be the worst on the board for two completely different
    reasons — it stops a lot, or it makes scrap — and the fix, the owner and
    the budget differ. Splitting them across separate charts made the reader do
    the join by memory.

    The quality fields are nullable rather than zero, because "no sheets
    logged" and "no sheets rejected" are different facts. An impregnator has no
    reject rate at all; showing 0% would read as perfect.
    """

    machine_id: int
    machine_code: str
    section_name: str

    downtime_minutes: float
    breakdowns: int
    mttr_minutes: float | None
    mtbf_hours: float | None

    produced: int
    rejected: int
    reject_percent: float | None

    # Impregnators only.
    rolls: int
    avg_rc: float | None
    avg_vc: float | None
    out_of_spec_rolls: int


class RollQualityRead(BaseModel):
    """Reject rate on in-spec paper against out-of-spec paper.

    Reported as a comparison, never as a claim. If out-of-spec paper does not
    reject more, the hypothesis is wrong and the number should say so.
    """

    linked_runs: int
    in_spec_reject_percent: float | None
    out_of_spec_reject_percent: float | None
    lift_percent: float | None
    # False when either bucket is too thin to mean anything. A two-roll
    # coincidence must not become a slide.
    enough_data: bool
