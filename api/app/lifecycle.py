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
