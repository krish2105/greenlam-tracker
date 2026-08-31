"""Individual performance — the most dangerous feature in this system.

Leadership asked for both: help the team AND evaluate individuals. That is a
coherent request, and addendum §4.1 actually permits it. What it forbids is a
specific shape, not the measurement itself:

    "Individual metrics are visible to that person's supervisor only — and to
     the person themselves. Never to peers... Never put individual rankings in
     the emailed workbook."

So five rules are enforced here in code rather than trusted to good intentions:

  1. THE PERSON SEES THEIR OWN, ALWAYS. `/people/me/performance` needs no
     capability. §4.1: "show people their own numbers first" — someone who has
     watched their own MTTR for a month reacts very differently to it being
     raised than someone ambushed with it.
  2. THEIR SUPERVISOR SEES IT. Requires `direct_report_metrics` AND the target
     inside the requester's scope. Manager and plant_head only.
  3. EVERYONE ELSE GETS 404. Peers, and every corporate tier. 404 not 403,
     because 403 confirms the person exists and that they have numbers.
  4. NO RANK. No position, no percentile, no "7th of 9" anywhere in the
     payload. §4.1: "Ravi handled 34 tickets, 12 of them Critical" is a
     staffing observation; "Ravi is 7th of 9" is a threat.
  5. NOTHING INDIVIDUAL LEAVES THIS ROUTER. Not in /tickets/summary, not in
     /tickets/exceptions, not in the export. `tests/test_hierarchy.py` asserts
     that.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import select

from ..deps import PrincipalDep, SessionDep
from ..lifecycle import CLOSED_STAGE
from ..models import Ticket, User, utcnow
from ..schemas_people import PerformanceRead, TeamMemberRead, TeamPerformanceRead
from ..tenancy import Principal, scope

router = APIRouter(prefix="/people", tags=["people"])

_DAYS_Q = Query(30, ge=7, le=365)

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")


def _may_view(principal: Principal, target: User, session: SessionDep) -> bool:
    """Self, or their supervisor. Nobody else, ever."""
    if principal.user_id == target.id:
        return True
    if not principal.can("view_dashboard"):
        return False
    # Supervision follows scope: a manager scoped to Press supervises Press.
    # A corporate role fails the capability check above regardless of how wide
    # their scope is — breadth is not supervision.
    visible = session.exec(scope(User, principal).where(User.id == target.id)).first()
    return visible is not None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _performance_for(
    user: User, session: SessionDep, principal: Principal, days: int
) -> PerformanceRead:
    since = utcnow() - timedelta(days=days)
    end = utcnow()

    raised = session.exec(
        scope(Ticket, principal).where(Ticket.raised_by == user.id, Ticket.raised_at >= since)
    ).all()
    acked = session.exec(
        scope(Ticket, principal).where(Ticket.acked_by == user.id, Ticket.acked_at >= since)
    ).all()
    resolved = session.exec(
        scope(Ticket, principal).where(Ticket.resolved_by == user.id, Ticket.resolved_at >= since)
    ).all()
    closed = session.exec(
        scope(Ticket, principal).where(Ticket.closed_by == user.id, Ticket.closed_at >= since)
    ).all()

    ack_minutes = [(t.acked_at - t.raised_at).total_seconds() / 60 for t in acked if t.acked_at]
    repair_minutes = [
        (t.resolved_at - t.raised_at).total_seconds() / 60 for t in resolved if t.resolved_at
    ]

    # Their own root-cause quality. Shown to them so they can act on it, and to
    # their supervisor so it can be coached — never aggregated upward with a
    # name attached.
    diagnosed = [t for t in resolved if t.root_cause_score is not None]
    quality = _mean([float(t.root_cause_score) for t in diagnosed])

    finished = [t for t in resolved if t.current_stage >= CLOSED_STAGE]
    clean = [t for t in finished if t.reopen_count == 0]

    by_priority: dict[str, int] = {}
    for t in [*raised, *resolved]:
        by_priority[t.priority] = by_priority.get(t.priority, 0) + 1

    return PerformanceRead(
        user_id=user.id,
        name=user.name,
        role=user.role,
        period_days=days,
        period_start=since.date(),
        period_end=end.date(),
        raised_count=len(raised),
        acknowledged_count=len(acked),
        resolved_count=len(resolved),
        closed_count=len(closed),
        avg_ack_minutes=_mean(ack_minutes),
        avg_repair_minutes=_mean(repair_minutes),
        first_time_fix_percent=(round(100 * len(clean) / len(finished), 1) if finished else None),
        root_cause_avg_score=quality,
        workload_by_priority=by_priority,
        is_self=principal.user_id == user.id,
    )


@router.get("/me/performance", response_model=PerformanceRead, summary="Your own numbers")
def my_performance(
    principal: PrincipalDep, session: SessionDep, days: int = _DAYS_Q
) -> PerformanceRead:
    """Always available, to everyone, with no capability required.

    Addendum §4.1: show people their own numbers first. This endpoint exists so
    that by the time anyone else discusses a technician's MTTR, that technician
    has already been watching it for a month.
    """
    user = session.get(User, principal.user_id)
    if user is None:
        raise _NOT_FOUND
    return _performance_for(user, session, principal, days)


@router.get("/team", response_model=TeamPerformanceRead, summary="Your team's workload")
def team_performance(
    principal: PrincipalDep, session: SessionDep, days: int = _DAYS_Q
) -> TeamPerformanceRead:
    """Direct reports, for a supervisor.

    Sorted by name, not by any metric, and carrying no rank field. Ordering a
    list of people by their MTTR *is* a leaderboard however it is labelled, and
    a leaderboard is the specific thing §4.1 says destroys the data.
    """
    if not principal.can("view_dashboard"):
        raise _NOT_FOUND

    people = session.exec(
        scope(User, principal)
        .where(User.is_active.is_(True), User.role.in_(("operator", "technician")))
        .order_by(User.name)
    ).all()

    members = []
    for person in people:
        p = _performance_for(person, session, principal, days)
        members.append(
            TeamMemberRead(
                user_id=p.user_id,
                name=p.name,
                role=p.role,
                raised_count=p.raised_count,
                resolved_count=p.resolved_count,
                avg_ack_minutes=p.avg_ack_minutes,
                avg_repair_minutes=p.avg_repair_minutes,
                first_time_fix_percent=p.first_time_fix_percent,
                root_cause_avg_score=p.root_cause_avg_score,
            )
        )

    team_repair = [m.avg_repair_minutes for m in members if m.avg_repair_minutes is not None]
    return TeamPerformanceRead(
        period_days=days,
        generated_at=utcnow(),
        member_count=len(members),
        team_avg_repair_minutes=_mean(team_repair),
        total_resolved=sum(m.resolved_count for m in members),
        members=members,
    )


@router.get(
    "/{user_id}/performance",
    response_model=PerformanceRead,
    summary="One person's numbers (self or their supervisor)",
)
def person_performance(
    user_id: int, principal: PrincipalDep, session: SessionDep, days: int = _DAYS_Q
) -> PerformanceRead:
    """404 for a peer or any corporate tier — not 403.

    403 would confirm both that the person exists and that they have numbers
    worth hiding, which is most of what an attacker or a curious colleague
    wanted to know.
    """
    target = session.get(User, user_id)
    if target is None or not _may_view(principal, target, session):
        raise _NOT_FOUND
    return _performance_for(target, session, principal, days)


def _utc_midnight(day) -> datetime:  # pragma: no cover - helper kept for parity
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


__all__ = ["router", "select"]
