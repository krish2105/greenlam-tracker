"""Individual performance shapes.

Note what is NOT here: no rank, no percentile, no position-of-N, no comparison
against a peer. Addendum §4.1 is specific that "Ravi handled 34 tickets, 12 of
them Critical" is a staffing observation while "Ravi is ranked 7th of 9" is a
threat — and the difference is a field on a schema.

If a future change adds a `rank` here, it should be argued for in a review, not
slipped in.
"""

from datetime import date, datetime

from pydantic import BaseModel


class PerformanceRead(BaseModel):
    user_id: int
    name: str
    role: str

    period_days: int
    period_start: date
    period_end: date

    # Workload, framed as volume rather than score.
    raised_count: int
    acknowledged_count: int
    resolved_count: int
    closed_count: int

    avg_ack_minutes: float | None
    avg_repair_minutes: float | None
    first_time_fix_percent: float | None
    # Their own root-cause quality, so they can act on it before anyone raises
    # it with them.
    root_cause_avg_score: float | None

    workload_by_priority: dict[str, int]

    # Lets the UI say "your numbers" rather than "their numbers", and lets it
    # frame a supervisor's view as support rather than assessment.
    is_self: bool


class TeamMemberRead(BaseModel):
    user_id: int
    name: str
    role: str
    raised_count: int
    resolved_count: int
    avg_ack_minutes: float | None
    avg_repair_minutes: float | None
    first_time_fix_percent: float | None
    root_cause_avg_score: float | None


class TeamPerformanceRead(BaseModel):
    """A supervisor's direct reports.

    `team_avg_repair_minutes` is the comparison point on purpose: an individual
    against the team average is a coaching conversation, an individual against
    a ranked list is a performance review nobody agreed to.
    """

    period_days: int
    generated_at: datetime
    member_count: int
    team_avg_repair_minutes: float | None
    total_resolved: int
    members: list[TeamMemberRead]
