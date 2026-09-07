"""Ticket lifecycle, escalation and root-cause scoring.

The Python half of `packages/core/src/tickets.ts`. Both copies must agree —
`tests/test_lifecycle.py` pins the shared cases.

Escalation is DERIVED on every read, never stored. Render's free tier has no
cron, so a job that "sets" escalation would be a moving part that can silently
stop, and a stalled escalator is worse than none: the board looks calm while a
press sits dead. Two timestamps compared on read cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import STAGES

CLOSED_STAGE = 6

# Minutes a ticket may sit unacknowledged before it escalates.
# PLACEHOLDER until Phase 0 confirms the real response expectation with the
# maintenance head. Deliberately loose: too tight and the board is permanently
# red, which trains everyone to ignore it.
ACK_SLA_MINUTES: dict[str, int] = {
    "Critical": 10,
    "High": 30,
    "Medium": 120,
    "Low": 480,
}

AGEING_DAYS = 3


@dataclass(frozen=True, slots=True)
class Escalation:
    level: str  # none | supervisor | plant_head
    waiting_minutes: float
    overdue_minutes: float


def escalation_of(
    *,
    priority: str,
    raised_at: datetime,
    acked_at: datetime | None,
    current_stage: int,
    now: datetime,
) -> Escalation:
    """Only the wait for acknowledgement escalates.

    Once a technician is on it, duration is a performance question rather than
    an alarm — and paging someone about a repair already in progress is how an
    alert channel gets muted in week one.
    """
    if acked_at is not None or current_stage > 0:
        return Escalation("none", -1.0, 0.0)

    waiting = (now - raised_at).total_seconds() / 60
    sla = ACK_SLA_MINUTES.get(priority, 120)
    overdue = waiting - sla
    if overdue <= 0:
        return Escalation("none", waiting, 0.0)

    # Doubling the SLA pulls in the plant head. One step, not a ladder — a
    # four-tier chain in a plant this size is just noise.
    level = "plant_head" if overdue >= sla else "supervisor"
    return Escalation(level, waiting, overdue)


def flags_for(
    *,
    priority: str,
    raised_at: datetime,
    acked_at: datetime | None,
    current_stage: int,
    reopen_count: int,
    repeat_count: int,
    now: datetime,
) -> list[str]:
    """What makes a ticket worth surfacing to someone not already working it.

    This is the basis of the exception feed. A plant head does not want 33
    machines; they want the three going wrong in a way nobody has noticed.
    """
    flags: list[str] = []
    closed = current_stage >= CLOSED_STAGE

    if not closed:
        esc = escalation_of(
            priority=priority,
            raised_at=raised_at,
            acked_at=acked_at,
            current_stage=current_stage,
            now=now,
        )
        if esc.level != "none":
            flags.append("escalated")
        if now - raised_at > timedelta(days=AGEING_DAYS):
            flags.append("ageing")

    if reopen_count > 0:
        flags.append("reopened")
    if repeat_count > 1:
        flags.append("repeat")
    # Running again but the analysis never landed. This is where root-cause
    # data quietly dies: the machine works, so nobody finishes the write-up.
    if current_stage == 4:
        flags.append("awaiting_root_cause")
    return flags


_PRIORITY_WEIGHT = {"Critical": 40, "High": 25, "Medium": 10, "Low": 5}
_FLAG_WEIGHT = {
    "repeat": 15,
    "reopened": 15,
    "ageing": 10,
    "awaiting_root_cause": 5,
    "escalated": 0,  # already counted via the escalation level below
}


def severity_score(
    *,
    priority: str,
    raised_at: datetime,
    acked_at: datetime | None,
    current_stage: int,
    reopen_count: int,
    repeat_count: int,
    now: datetime,
) -> int:
    """Ranking for the exception feed. Higher is more urgent."""
    score = _PRIORITY_WEIGHT.get(priority, 10)
    esc = escalation_of(
        priority=priority,
        raised_at=raised_at,
        acked_at=acked_at,
        current_stage=current_stage,
        now=now,
    )
    if esc.level == "plant_head":
        score += 40
    elif esc.level == "supervisor":
        score += 20

    for flag in flags_for(
        priority=priority,
        raised_at=raised_at,
        acked_at=acked_at,
        current_stage=current_stage,
        reopen_count=reopen_count,
        repeat_count=repeat_count,
        now=now,
    ):
        score += _FLAG_WEIGHT.get(flag, 0)
    return score


# ---------------------------------------------------------------------------
# Root-cause quality — addendum §4.2, review 5
# ---------------------------------------------------------------------------

MIN_WHY_LENGTH = 12

# The entries that actually show up by week three.
EMPTY_PHRASES = {
    "machine stopped",
    "not working",
    "belt issue",
    "problem",
    "issue",
    "fault",
    "error",
    "breakdown",
    "same as before",
    "repaired",
    "fixed",
    "ok now",
}


def _normalise(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _is_substantive(text: str | None) -> bool:
    if not text:
        return False
    clean = _normalise(text)
    if len(clean) < MIN_WHY_LENGTH:
        return False
    return clean.rstrip(".") not in EMPTY_PHRASES


@dataclass(frozen=True, slots=True)
class QualityScore:
    score: int
    usable: bool
    reasons: list[str]


def score_root_cause(
    *,
    why_1: str | None,
    why_2: str | None,
    why_3: str | None,
    preventive_action: str | None,
    previous_for_machine: str | None = None,
) -> QualityScore:
    """Score one root-cause entry.

    Not to grade a technician — to watch the TEAM-level percentage of usable
    entries over time. When that number starts falling the analytics are about
    to become worthless, and you get three weeks of warning instead of
    discovering it at the quarterly review.
    """
    reasons: list[str] = []
    score = 0

    substantive = sum(1 for w in (why_1, why_2, why_3) if _is_substantive(w))
    score += substantive * 20
    if substantive == 0:
        reasons.append("No why-level was filled in usefully.")
    elif substantive < 3:
        reasons.append(f"Only {substantive} of 3 why-levels answered.")

    if _is_substantive(preventive_action):
        score += 25
    else:
        reasons.append("No distinct preventive action — a fix is not a prevention.")

    # Four breakdowns with four identical root causes is the signature of a
    # field being filled rather than answered.
    if previous_for_machine and why_1 and _normalise(previous_for_machine) == _normalise(why_1):
        score -= 30
        reasons.append("Identical to the previous entry for this machine.")

    if preventive_action and why_3 and _normalise(preventive_action) == _normalise(why_3):
        score -= 10
        reasons.append("Preventive action repeats the final why.")

    score += 15  # baseline for a completed, non-empty submission
    clamped = max(0, min(100, score))
    return QualityScore(clamped, clamped >= 60, reasons)


def render_root_cause(why_1: str | None, why_2: str | None, why_3: str | None) -> str:
    """Flatten the why-levels into the single column the Excel register uses.

    The plant's existing register has one root-cause column and leadership's
    pivots point at it. Keeping the headers intact was an explicit requirement,
    so the structured whys render down rather than replacing it.
    """
    parts = [w.strip() for w in (why_1, why_2, why_3) if w and w.strip()]
    return " → ".join(parts)


def stage_name(current_stage: int) -> str:
    return STAGES[max(0, min(current_stage, len(STAGES) - 1))]


# ---------------------------------------------------------------------------
# Criticality — calculated from the repair, not chosen before it
# ---------------------------------------------------------------------------

# The Python half of `criticalityFromSolveTime` in packages/core/src/tickets.ts.
# `tests/test_criticality.py` reads the TypeScript source and asserts the
# numbers below still match it, so the two copies cannot drift apart quietly.
#
# Keyed by machine class rather than section name: V5 §5.8 splits the plant
# into "Press" and "all other machines", and a section is renamed far more
# often than that distinction changes.
DEFAULT_CRITICALITY_THRESHOLDS: dict[str, tuple[int, int]] = {
    "press": (30, 60),
    "other": (60, 120),
}

CRITICALITY_SETTING_KEYS: dict[str, tuple[str, str]] = {
    "press": ("criticality.press.low_max", "criticality.press.medium_max"),
    "other": ("criticality.other.low_max", "criticality.other.medium_max"),
}


def solve_minutes(
    *,
    correction_started_at: datetime | None,
    correction_complete_at: datetime | None,
    pending_minutes: float,
) -> float | None:
    """(complete − started) − pending. None until the repair is finished.

    Measured from when work STARTED, so the wait before somebody picked up a
    spanner is not counted as slow repair work — that is Repair Start Delay,
    its own KPI with its own owner.
    """
    if correction_started_at is None or correction_complete_at is None:
        return None
    gross = (correction_complete_at - correction_started_at).total_seconds() / 60
    # Clock skew between a queued device timestamp and a server one can push
    # the subtraction past the elapsed time. A negative repair is not a thing.
    return max(0.0, round(gross - pending_minutes, 1))


def criticality_from_solve_time(
    minutes: float | None, thresholds: tuple[int, int]
) -> str | None:
    """Low / Medium / High, or None while the repair is unfinished.

    None is the normal answer for every open ticket, which is exactly why this
    cannot order a live queue — see `machines.criticality` for that job.

    The boundary value falls in the LOWER band: exactly 30 minutes on a press
    is Low. V5 §5.8 reads "Under 30 min / 30 min – 1 hr", which puts it in the
    upper one, and this is the single case where the two differ — a repair
    timed at exactly the threshold should not inflate the High count on what is
    effectively a rounding artefact.
    """
    if minutes is None:
        return None
    low_max, medium_max = thresholds
    if minutes <= low_max:
        return "Low"
    if minutes <= medium_max:
        return "Medium"
    return "High"


def machine_class(section_name: str | None) -> str:
    """"press" or "other" — the only two classes V5 §5.8 recognises."""
    return "press" if (section_name or "").strip().lower().startswith("press") else "other"


# How urgent an OPEN ticket is, before anybody has repaired anything.
#
# V5 §5.8 removes the priority a person used to pick at raise time, and puts a
# calculated criticality in its place — but that one only exists once the
# repair is over. Something still has to answer "which of these four stopped
# machines first", and the honest answer is the one fact known in advance: how
# much this machine matters. That is `machines.criticality`, A/B/C, set during
# machine setup.
#
# Mapped onto the existing urgency words rather than threading a second
# vocabulary through escalation, flags and scoring. "Critical" is deliberately
# unreachable: there is no class above A, and a band nothing can enter is a
# band that misleads whoever reads the legend.
_MACHINE_URGENCY = {"A": "High", "B": "Medium", "C": "Low"}


def urgency_of_machine(criticality: str | None) -> str:
    """A/B/C from the machine master to the urgency word the SLA table uses.

    Read from the machine at query time, not copied onto the ticket when it was
    raised. A machine reclassified from B to A during setup should change how
    its open tickets rank immediately — a snapshot taken at raise time would
    keep sorting last week's tickets by last week's answer.
    """
    return _MACHINE_URGENCY.get((criticality or "").strip().upper(), "Medium")


# ---------------------------------------------------------------------------
# Corrections (V5 §7)
# ---------------------------------------------------------------------------

# How long the person who owns a record may fix it themselves.
#
# Different numbers because the two records go stale at different speeds. A
# ticket is fully closed only once the RCA is written, and by then the engineer
# has usually moved on — five hours is enough to catch a slip they notice on
# re-reading. A production entry is submitted at the end of a shift and the
# person who typed it is often still on site when somebody queries the count,
# so ten hours covers the rest of that shift and the handover after it.
#
# Past the window the record does not become uneditable; it becomes an admin's
# decision. That is the difference the window exists to draw.
TICKET_SELF_CORRECT_HOURS = 5
PRODUCTION_SELF_CORRECT_HOURS = 10


def within_self_correct_window(
    anchor: datetime | None, now: datetime, hours: int
) -> bool:
    """Whether a record is still inside its own correction window.

    `anchor` is the moment the record became final — `closed_at` for a ticket,
    submission for a production entry. None means it never did, and an
    unfinished record is freely editable by its owner as ordinary work in
    progress, which is not this workflow at all.
    """
    if anchor is None:
        return False
    return now - anchor <= timedelta(hours=hours)


# Fields a correction may touch, and nothing else.
#
# An allowlist rather than a denylist. The failure mode of a denylist here is
# that a column added next year is silently editable over the API — including
# `plant_id`, which would move a ticket to another plant, or `owner_id`, which
# would rewrite who fixed a machine. Neither is a correction.
CORRECTABLE_TICKET_FIELDS: frozenset[str] = frozenset(
    {
        "description",
        "immediate_correction",
        "why_1",
        "why_2",
        "why_3",
        "preventive_action",
        "category_id",
        "shift_id",
        "downtime_type",
        # Timestamps are correctable ONLY here. §5.5 forbids typing them during
        # normal work precisely so nobody can quietly backdate a response time;
        # this path is the sanctioned exception, and it is always logged with
        # the previous value and the person who changed it.
        "raised_at",
        "acked_at",
        "repair_at",
        "resolved_at",
    }
)

# Deliberately absent from the list above:
#
#   closed_at   V5 §7 is explicit that a correction leaves the ticket Closed
#               and does not move this. Moving it would restart the very
#               window that authorises the correction.
#   status,
#   current_stage,
#   reopen_count
#               Changing where a ticket sits in its lifecycle is Reopen's job.
#               A clerical fix that flipped a ticket back to an active status
#               would put it in the live Pending count and could fire the
#               repeat-failure flag for a breakdown that never happened.
#   solve_minutes,
#   criticality_calculated
#               Derived. Correct the timestamps and they are recomputed; typing
#               them directly would let somebody choose their own verdict.

CORRECTABLE_PRODUCTION_FIELDS: frozenset[str] = frozenset(
    {
        "load_no",
        "produced_qty",
        "rejected_qty",
        "reject_reason_id",
        "shift_id",
        "log_date",
        "design_id",
        "size_id",
        "texture_id",
        "thickness_id",
    }
)
