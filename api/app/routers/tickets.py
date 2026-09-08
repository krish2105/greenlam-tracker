"""Ticket lifecycle, the exception feed, shift handover, and root-cause quality.

Event-sourced: `POST /tickets/{id}/events` appends an immutable row and the
ticket projection is updated from it. One endpoint rather than seven
`/acknowledge`, `/resolve`, `/close` routes, because the sync engine in Phase 2
will replay exactly this shape from an offline outbox.

`event_id` is client-supplied and unique-constrained, so a retry over a flaky
connection is a no-op instead of a duplicate.
"""

from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import select

from .. import analytics, classify, lifecycle, notify, worker
from ..deps import (
    CanRaise,
    Operational,
    PrincipalDep,
    SessionDep,
)
from ..models import (
    Category,
    Machine,
    Section,
    Shift,
    Ticket,
    TicketEvent,
    TicketMaterial,
    TicketPendingWindow,
    User,
    utcnow,
)
from ..schemas_tickets import (
    Analytics,
    BoardSummary,
    EscalationRead,
    ExceptionFeed,
    ExceptionItem,
    HandoverRead,
    HandoverTicket,
    RootCauseQualityRead,
    SectionSummary,
    TicketCreate,
    TicketEventCreate,
    TicketRead,
)
from ..tenancy import Principal, assert_visible, scope

router = APIRouter(prefix="/tickets", tags=["tickets"])

# Module-level singletons so the Query() call is not evaluated in a default
# argument position, which ruff flags (B008).
_SHIFT_Q = Query(None)
_DAYS_Q = Query(90, ge=7, le=365)
_ON_Q = Query(None)

# Which stage each event moves the ticket to. Forward only — the guard below
# refuses a backwards move, except REOPENED, which is the one explicit
# exception in the domain rules.
STAGE_FOR_EVENT = {
    "ACKNOWLEDGED": 1,
    "MATERIAL_RECORDED": 2,
    "REPAIR_STARTED": 3,
    "RESOLVED": 4,
    "DIAGNOSED": 5,
    "CLOSED": 6,
    "REOPENED": 3,
}


def _new_uuid() -> UUID:
    """UUIDv7 where available, so ids sort by creation time.

    Falls back to uuid4 rather than failing: an id that sorts badly is a minor
    annoyance, a ticket that cannot be raised is a stopped machine.
    """
    try:
        import uuid_utils

        return UUID(str(uuid_utils.uuid7()))
    except Exception:  # noqa: BLE001
        return uuid4()


def _repeat_counts(session: SessionDep, principal: Principal) -> dict[tuple[int, int | None], int]:
    """Breakdowns per machine+category in the trailing 30 days.

    One grouped query rather than a count per ticket — the exception feed reads
    this for every open ticket, and N+1 here would be felt on a cold Render
    instance.
    """
    since = utcnow() - timedelta(days=30)
    # session.execute, not session.exec: SQLModel's exec() unwraps a single
    # scalar per row, which silently mangles a multi-column aggregate.
    rows = session.execute(
        scope(Ticket, principal)
        .where(Ticket.raised_at >= since)
        .with_only_columns(Ticket.machine_id, Ticket.category_id, func.count())
        .group_by(Ticket.machine_id, Ticket.category_id)
    ).all()
    return {(machine_id, category_id): count for machine_id, category_id, count in rows}


def _machine_index(session: SessionDep, principal: Principal):
    machines = {m.id: m for m in session.exec(scope(Machine, principal)).all()}
    sections = {s.id: s for s in session.exec(scope(Section, principal)).all()}
    return machines, sections


def _pending_read(session, ticket_ids: list) -> dict:
    """Minutes waited, and any open wait, for each ticket.

    Batched deliberately. The ticket list renders up to five hundred rows and a
    per-row query for the pending clock would be five hundred round trips to
    show a number that is zero on most of them.
    """
    if not ticket_ids:
        return {}
    rows = session.exec(
        select(TicketPendingWindow).where(TicketPendingWindow.ticket_id.in_(ticket_ids))
    ).all()
    out: dict = {}
    for w in rows:
        entry = out.setdefault(w.ticket_id, {"minutes": 0.0, "kind": None})
        if w.ended_at is None:
            # An open window has no length yet — the wait is still happening,
            # and growing the subtraction every second would make Solve Time
            # move on a screen nobody is touching.
            entry["kind"] = w.kind
        else:
            entry["minutes"] += w.minutes or 0
    return {
        tid: {"pending_minutes": round(v["minutes"], 1), "hold_kind": v["kind"]}
        for tid, v in out.items()
    }


def _to_read(
    ticket: Ticket,
    machine: Machine,
    section: Section,
    raiser_name: str,
    repeat: int,
    now: datetime,
    editor_name: str | None = None,
    pending_minutes: float = 0.0,
    hold_kind: str | None = None,
) -> TicketRead:
    # Ranked by how much the MACHINE matters, not by a priority somebody
    # picked at raise time — V5 §5.8 removed that judgement call, and the
    # calculated criticality that replaced it does not exist until the repair
    # is finished. See lifecycle.urgency_of_machine.
    urgency = lifecycle.urgency_of_machine(machine.criticality)
    esc = lifecycle.escalation_of(
        priority=urgency,
        raised_at=ticket.raised_at,
        acked_at=ticket.acked_at,
        current_stage=ticket.current_stage,
        now=now,
    )
    flags = lifecycle.flags_for(
        priority=urgency,
        raised_at=ticket.raised_at,
        acked_at=ticket.acked_at,
        current_stage=ticket.current_stage,
        reopen_count=ticket.reopen_count,
        repeat_count=repeat,
        now=now,
    )
    downtime = None
    if ticket.resolved_at is not None:
        downtime = (ticket.resolved_at - ticket.raised_at).total_seconds() / 60

    return TicketRead(
        id=ticket.id,
        ticket_no=ticket.ticket_no,
        machine_id=ticket.machine_id,
        machine_code=machine.code,
        section_id=ticket.section_id,
        section_name=section.name,
        category_id=ticket.category_id,
        priority=urgency,
        solve_minutes=ticket.solve_minutes,
        criticality_calculated=ticket.criticality_calculated,
        status=ticket.status,
        description=ticket.description,
        location=ticket.location,
        downtime_type=ticket.downtime_type,
        raised_via=ticket.raised_via,
        current_stage=ticket.current_stage,
        stage=lifecycle.stage_name(ticket.current_stage),
        raised_at=ticket.raised_at,
        acked_at=ticket.acked_at,
        resolved_at=ticket.resolved_at,
        closed_at=ticket.closed_at,
        raised_by=ticket.raised_by,
        raised_by_name=raiser_name,
        immediate_correction=ticket.immediate_correction,
        why_1=ticket.why_1,
        why_2=ticket.why_2,
        why_3=ticket.why_3,
        preventive_action=ticket.preventive_action,
        root_cause=ticket.root_cause,
        sheets_after_sanding=ticket.sheets_after_sanding,
        reopen_count=ticket.reopen_count,
        rating=ticket.rating,
        last_edited_at=ticket.last_edited_at,
        last_edited_by_name=editor_name,
        pending_minutes=pending_minutes,
        hold_kind=hold_kind,
        material_needed=ticket.material_at is not None,
        escalation=EscalationRead(
            level=esc.level,
            waiting_minutes=round(esc.waiting_minutes, 1),
            overdue_minutes=round(esc.overdue_minutes, 1),
        ),
        flags=flags,
        repeat_count=repeat,
        downtime_minutes=round(downtime, 1) if downtime is not None else None,
    )


def _next_ticket_no(session: SessionDep, section: Section, raised_at: datetime) -> str:
    """PR-2608-0142 — section, year-month, sequence.

    Nobody reads a UUID aloud across a press hall. Assigned server-side so the
    sequence stays dense even when tickets arrive out of order from an offline
    device.
    """
    prefix = "".join(ch for ch in section.name.upper() if ch.isalpha())[:2] or "XX"
    stamp = raised_at.strftime("%y%m")
    pattern = f"{prefix}-{stamp}-%"
    used = session.exec(
        select(func.count()).select_from(Ticket).where(Ticket.ticket_no.like(pattern))
    ).one()
    return f"{prefix}-{stamp}-{used + 1:04d}"


# ---------------------------------------------------------------------------
# Raise and read
# ---------------------------------------------------------------------------


@router.post(
    "", response_model=TicketRead, status_code=status.HTTP_201_CREATED, summary="Raise a breakdown"
)
def raise_ticket(body: TicketCreate, principal: CanRaise, session: SessionDep) -> TicketRead:
    """Create a ticket and its RAISED event.

    Under 30 seconds is the design target — everything optional is optional.
    """
    machine = session.get(Machine, body.machine_id)
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Machine not found")
    assert_visible(machine, principal)

    section = session.get(Section, machine.section_id)
    now = utcnow()
    raised_at = body.client_ts or now
    # Phones on the floor have wrong clocks. Reject anything implausible rather
    # than letting it poison MTTR (spec §3.2).
    if raised_at > now + timedelta(hours=24):
        raised_at = now

    ticket = Ticket(
        id=body.id or _new_uuid(),
        plant_id=machine.plant_id,
        unit_id=machine.unit_id,
        section_id=machine.section_id,
        machine_id=machine.id,
        shift_id=body.shift_id,
        category_id=body.category_id,
        raised_by=principal.user_id,
        # Derived from the machine, not taken from `body.priority`.
        #
        # V5 §5.8 removed the priority question from the raise form, and the
        # app already stopped asking it — but a value the client still sends is
        # a value the client can get wrong, and a machine reclassified B->A in
        # setup would leave every ticket raised before that carrying the old
        # answer. Storing it keeps the Excel export and the register importer
        # working; `_to_read` recomputes it live for anything on screen.
        priority=lifecycle.urgency_of_machine(machine.criticality),
        description=body.description.strip(),
        location=body.location,
        downtime_type=body.downtime_type,
        raised_via=body.raised_via,
        input_language=body.input_language,
        current_stage=0,
        raised_at=raised_at,
        ticket_no=_next_ticket_no(session, section, raised_at),
    )
    session.add(ticket)
    session.add(
        TicketEvent(
            event_id=_new_uuid(),
            ticket_id=ticket.id,
            plant_id=ticket.plant_id,
            unit_id=ticket.unit_id,
            type="RAISED",
            actor_id=principal.user_id,
            payload={"priority": body.priority, "raised_via": body.raised_via},
            client_ts=raised_at,
        )
    )
    # Does this repeat something on the same machine that was only just fixed?
    #
    # Linked at raise time rather than found later by the worker: the SOP says
    # a recurrence inside the window should have been a Reopen, so knowing it
    # is a repeat is most useful at the moment somebody is about to work it.
    ticket.repeats_ticket_id = worker.find_repeat(session, ticket)

    session.commit()
    session.refresh(ticket)

    # After the commit, and unable to fail the request. Somebody reporting a
    # stopped press is doing the most important thing this system supports; a
    # push service having a bad afternoon is not a reason to refuse it.
    notify.ticket_raised(
        session,
        machine_code=machine.code,
        description=ticket.description,
        by=principal.user_id,
    )
    if ticket.repeats_ticket_id is not None:
        notify.ticket_flagged(
            session,
            machine_code=machine.code,
            reason="Down again soon after the last repair.",
            by=principal.user_id,
        )
    session.commit()

    raiser = session.get(User, principal.user_id)
    return _to_read(ticket, machine, section, raiser.name, 1, now)


@router.get("", response_model=list[TicketRead], summary="Tickets in your scope")
def list_tickets(
    principal: Operational,
    session: SessionDep,
    state: str = Query("open", pattern=r"^(open|closed|all)$"),
    section_id: int | None = Query(None),
    machine_id: int | None = Query(None),
    limit: int = Query(100, le=500),
) -> list[TicketRead]:
    """Operational roles only. Corporate tiers use `/tickets/exceptions`."""
    stmt = scope(Ticket, principal).order_by(Ticket.raised_at.desc()).limit(limit)
    if state == "open":
        stmt = stmt.where(Ticket.current_stage < lifecycle.CLOSED_STAGE)
    elif state == "closed":
        stmt = stmt.where(Ticket.current_stage >= lifecycle.CLOSED_STAGE)
    if section_id is not None:
        stmt = stmt.where(Ticket.section_id == section_id)
    if machine_id is not None:
        stmt = stmt.where(Ticket.machine_id == machine_id)

    tickets = session.exec(stmt).all()
    machines, sections = _machine_index(session, principal)
    repeats = _repeat_counts(session, principal)
    names = {u.id: u.name for u in session.exec(scope(User, principal)).all()}
    pending = _pending_read(session, [t.id for t in tickets])
    now = utcnow()

    return [
        _to_read(
            t,
            machines[t.machine_id],
            sections[t.section_id],
            names.get(t.raised_by, "—"),
            repeats.get((t.machine_id, t.category_id), 1),
            now,
            names.get(t.last_edited_by) if t.last_edited_by else None,
            **pending.get(t.id, {}),
        )
        for t in tickets
        if t.machine_id in machines and t.section_id in sections
    ]


@router.get("/analytics", response_model=Analytics, summary="KPIs and chart series")
def board_analytics(principal: PrincipalDep, session: SessionDep, days: int = _DAYS_Q) -> Analytics:
    """Everything the board draws, in one response.

    Readable by every tier, corporate included. The payload is aggregates only
    — no ticket id, no description, no name — so there is nothing here to
    withhold, and a CXO seeing real numbers matters more than a purity rule
    that would show them zeroes.
    """
    now = utcnow()
    start, previous_start, _ = analytics.period_bounds(now, days)

    machines = {m.id: m for m in session.exec(scope(Machine, principal)).all()}
    sections = {s.id: s for s in session.exec(scope(Section, principal)).all()}
    categories = {c.id: c.name for c in session.exec(scope(Category, principal)).all()}

    rows = session.exec(scope(Ticket, principal).where(Ticket.raised_at >= previous_start)).all()

    def to_facts(t: Ticket) -> analytics.TicketFacts | None:
        machine = machines.get(t.machine_id)
        section = sections.get(t.section_id)
        if machine is None or section is None:
            return None
        return analytics.TicketFacts(
            machine_id=t.machine_id,
            machine_code=machine.code,
            section_id=t.section_id,
            section_name=section.name,
            category=categories.get(t.category_id, "Uncategorised"),
            priority=lifecycle.urgency_of_machine(machine.criticality),
            criticality_calculated=t.criticality_calculated,
            downtime_type=t.downtime_type,
            current_stage=t.current_stage,
            raised_at=t.raised_at,
            acked_at=t.acked_at,
            resolved_at=t.resolved_at,
            closed_at=t.closed_at,
            reopen_count=t.reopen_count,
            root_cause_score=t.root_cause_score,
            root_cause_usable=t.root_cause_usable,
        )

    all_facts = [f for f in (to_facts(t) for t in rows) if f is not None]
    current = [f for f in all_facts if f.raised_at >= start]
    previous = [f for f in all_facts if f.raised_at < start]

    scheduled_hours = {
        m.id: float(m.scheduled_hours_per_day)
        for m in machines.values()
        if m.scheduled_hours_per_day is not None
    }

    kpis = analytics.compute_kpis(
        current,
        now=now,
        period_days=days,
        machine_count=len(machines),
        previous=previous,
        # The two Phase 0 answers, once somebody has entered them on the
        # machine setup screen. Both are sparse dicts: only machines that have
        # a value appear, and compute_kpis decides what a partial answer means
        # for each (a partial cost is withheld, a partial schedule falls back
        # to calendar).
        # `machines` is a dict keyed by id, so iterate its VALUES — iterating
        # the dict yields the int keys, which is what the first version did and
        # why every analytics call 500'd on 'int' has no attribute.
        hourly_costs={
            m.id: float(m.hourly_downtime_cost)
            for m in machines.values()
            if m.hourly_downtime_cost is not None
        },
        scheduled_hours=scheduled_hours,
    )

    plant_count = len(principal.plant_ids)
    return Analytics(
        generated_at=now,
        period_days=days,
        period_start=start.date(),
        resolution="operational",
        scope_label=f"{plant_count} plant{'s' if plant_count != 1 else ''}",
        machine_count=len(machines),
        kpis=asdict(kpis),
        pareto_by_cause=analytics.pareto_by_cause(current),
        downtime_trend=analytics.downtime_trend(current, start=start.date(), end=now.date()),
        top_machines=analytics.top_machines(
            current,
            period_days=days,
            scheduled_hours=scheduled_hours,
            machine_count=len(machines),
        ),
        monthly=analytics.monthly_trend(all_facts),
        sparklines={
            metric: analytics.sparkline(current, start=start.date(), end=now.date(), metric=metric)
            for metric in ("downtime", "mttr", "mtta")
        },
    )


@router.get("/summary", response_model=BoardSummary, summary="Aggregates for the board")
def board_summary(principal: PrincipalDep, session: SessionDep) -> BoardSummary:
    """Section-level totals, readable by every tier including corporate.

    Deliberately NOT behind `require_operational`. Corporate roles cannot list
    tickets, so if the board derived its totals from the ticket list they would
    see zeroes and read them as "no downtime" — the most dangerous possible
    failure mode for a leadership dashboard. Aggregates carry no ticket id, no
    description and no name, so there is nothing here to withhold.
    """
    now = utcnow()
    tickets = session.exec(scope(Ticket, principal)).all()
    machines, sections = _machine_index(session, principal)

    open_total = escalated_total = closed_total = 0
    downtime_total = 0.0
    per_section: dict[int, dict[str, float]] = defaultdict(
        lambda: {"open": 0, "closed": 0, "minutes": 0.0}
    )

    for t in tickets:
        bucket = per_section[t.section_id]
        if t.current_stage >= lifecycle.CLOSED_STAGE:
            closed_total += 1
            bucket["closed"] += 1
        else:
            open_total += 1
            bucket["open"] += 1
            if (
                lifecycle.escalation_of(
                    priority=lifecycle.urgency_of_machine(
                        m.criticality if (m := machines.get(t.machine_id)) else None
                    ),
                    raised_at=t.raised_at,
                    acked_at=t.acked_at,
                    current_stage=t.current_stage,
                    now=now,
                ).level
                != "none"
            ):
                escalated_total += 1

        if t.resolved_at is not None:
            minutes = (t.resolved_at - t.raised_at).total_seconds() / 60
            downtime_total += minutes
            bucket["minutes"] += minutes

    resolved_count = sum(1 for t in tickets if t.resolved_at is not None)
    plant_count = len(principal.plant_ids)

    rows = [
        SectionSummary(
            section_id=sid,
            section_name=sections[sid].name,
            sort_order=sections[sid].sort_order,
            open_count=int(v["open"]),
            closed_count=int(v["closed"]),
            downtime_minutes=round(v["minutes"], 1),
        )
        for sid, v in per_section.items()
        if sid in sections
    ]
    rows.sort(key=lambda r: r.downtime_minutes, reverse=True)

    return BoardSummary(
        generated_at=now,
        scope_label=f"{plant_count} plant{'s' if plant_count != 1 else ''}",
        resolution="operational",
        open_total=open_total,
        escalated_total=escalated_total,
        closed_total=closed_total,
        downtime_minutes=round(downtime_total, 1),
        mttr_minutes=round(downtime_total / resolved_count, 1) if resolved_count else None,
        sections=rows,
    )


@router.get("/exceptions", response_model=ExceptionFeed, summary="What needs you now")
def exception_feed(
    principal: PrincipalDep, session: SessionDep, limit: int = Query(20, le=100)
) -> ExceptionFeed:
    """The answer-first surface, scoped and redacted by role.

    Every tier gets this endpoint; what comes back differs. An operational role
    sees the ticket and its priority. A corporate role sees the machine, the
    section and the shape of the problem — no description, no names, no free
    text. Two shapes rather than one with fields blanked, because a blanked
    field is one refactor away from leaking.
    """
    now = utcnow()
    open_tickets = session.exec(
        scope(Ticket, principal).where(Ticket.current_stage < lifecycle.CLOSED_STAGE)
    ).all()
    machines, sections = _machine_index(session, principal)
    repeats = _repeat_counts(session, principal)

    scored: list[tuple[int, ExceptionItem]] = []
    escalated_total = 0

    for t in open_tickets:
        machine = machines.get(t.machine_id)
        section = sections.get(t.section_id)
        if machine is None or section is None:
            continue

        repeat = repeats.get((t.machine_id, t.category_id), 1)
        urgency = lifecycle.urgency_of_machine(machine.criticality)
        flags = lifecycle.flags_for(
            priority=urgency,
            raised_at=t.raised_at,
            acked_at=t.acked_at,
            current_stage=t.current_stage,
            reopen_count=t.reopen_count,
            repeat_count=repeat,
            now=now,
        )
        if not flags:
            continue
        if "escalated" in flags:
            escalated_total += 1

        severity = lifecycle.severity_score(
            priority=urgency,
            raised_at=t.raised_at,
            acked_at=t.acked_at,
            current_stage=t.current_stage,
            reopen_count=t.reopen_count,
            repeat_count=repeat,
            now=now,
        )
        open_min = (now - t.raised_at).total_seconds() / 60
        kind = flags[0]
        headline, detail, params = _describe(
            kind, machine.code, open_min, repeat, t.reopen_count
        )

        scored.append(
            (
                severity,
                ExceptionItem(
                    # A corporate tier gets no id to drill into — there is
                    # nothing for them to open.
                    ticket_id=t.id,
                    kind=kind,
                    severity=severity,
                    machine_code=machine.code,
                    section_name=section.name,
                    headline=headline,
                    params=params,
                    detail=detail,
                    since=t.raised_at,
                    priority=urgency,
                ),
            )
        )

    scored.sort(key=lambda pair: pair[0], reverse=True)
    plant_count = len(principal.plant_ids)
    return ExceptionFeed(
        generated_at=now,
        scope_label=f"{plant_count} plant{'s' if plant_count != 1 else ''}",
        resolution="operational",
        items=[item for _, item in scored[:limit]],
        open_total=len(open_tickets),
        escalated_total=escalated_total,
    )


def _describe(
    kind: str, machine_code: str, open_minutes: float, repeat: int, reopens: int
) -> tuple[str, str, dict[str, str | int]]:
    """Plain-language headline and detail, plus the parts they were built from.

    WHY THE PARAMETERS COME BACK TOO

    These two strings were the last untranslated text in the product. Every
    label in the interface goes through i18next, but the exception feed — the
    single most-read block on both the floor and the board — was assembled here
    in English and shipped as finished prose. Switching the app to Hindi left
    "Press-4 has no acknowledgement" sitting in the middle of a Hindi screen.

    Rendering it server-side in the reader's language would mean sending a
    locale with every request, duplicating the entire message catalogue in
    Python, and keeping two copies in step forever. So the server keeps doing
    what it is good at — deciding WHICH message applies and computing the
    numbers in it — and hands back `kind` plus its parameters. The client owns
    the wording, in whatever language that client is set to.

    `headline` and `detail` stay populated, unchanged. They are the fallback if
    the client has no string for a `kind`, and they are what the nightly Excel
    workbook uses, which is English by leadership's own request.
    """
    waited = lifecycle_duration(open_minutes)
    params: dict[str, str | int] = {
        "machine": machine_code,
        "waited": waited,
        "repeat": repeat,
        "reopens": reopens,
    }
    match kind:
        case "escalated":
            return (
                f"{machine_code} has no acknowledgement",
                f"Down {waited} and nobody has picked it up.",
                params,
            )
        case "ageing":
            return (
                f"{machine_code} has been open {waited}",
                "Older than three days. Close it or say why it is stuck.",
                params,
            )
        case "repeat":
            return (
                f"{machine_code} has failed {repeat} times this month",
                "Same machine and category. Worth a preventive action, not another repair.",
                params,
            )
        case "reopened":
            return (
                f"{machine_code} was reopened {reopens}×",
                "The first fix did not hold. Check the root cause before closing again.",
                params,
            )
        case "awaiting_root_cause":
            return (
                f"{machine_code} is running, write-up pending",
                "Machine is back up but the why-why was never finished.",
                params,
            )
        case _:
            return (f"{machine_code} needs attention", f"Open {waited}.", params)


def lifecycle_duration(minutes: float) -> str:
    m = max(0, round(minutes))
    if m < 1:
        return "<1 min"
    if m < 60:
        return f"{m} min"
    h, rem = divmod(m, 60)
    if h < 24:
        return f"{h}h {rem}m"
    d, rh = divmod(h, 24)
    return f"{d}d {rh}h"


@router.get("/handover", response_model=HandoverRead, summary="Shift handover digest")
def handover(
    principal: Operational,
    session: SessionDep,
    shift_id: int | None = _SHIFT_Q,
    on: date | None = _ON_Q,
) -> HandoverRead:
    """What the outgoing shift is leaving behind.

    Built to attach to a ritual that already happens. People are already stood
    together swapping notes at shift change; a digest they read there becomes
    part of the routine, while a screen nobody is scheduled to open becomes a
    chore by week two.
    """
    now = utcnow()
    on = on or now.date()
    window_start = datetime.combine(on, datetime.min.time(), tzinfo=UTC)
    window_end = window_start + timedelta(days=1)

    base = scope(Ticket, principal)
    if shift_id is not None:
        base = base.where(Ticket.shift_id == shift_id)

    raised = session.exec(
        base.where(Ticket.raised_at >= window_start, Ticket.raised_at < window_end)
    ).all()
    closed = session.exec(
        base.where(Ticket.closed_at >= window_start, Ticket.closed_at < window_end)
    ).all()
    still_open = session.exec(base.where(Ticket.current_stage < lifecycle.CLOSED_STAGE)).all()

    machines, _ = _machine_index(session, principal)

    def line(t: Ticket, note: str) -> HandoverTicket:
        machine = machines.get(t.machine_id)
        return HandoverTicket(
            ticket_no=t.ticket_no,
            machine_code=machine.code if machine else "—",
            stage=lifecycle.stage_name(t.current_stage),
            priority=lifecycle.urgency_of_machine(machine.criticality if machine else None),
            open_minutes=round((now - t.raised_at).total_seconds() / 60, 1),
            note=note,
        )

    downtime = sum(
        (t.resolved_at - t.raised_at).total_seconds() / 60
        for t in closed
        if t.resolved_at is not None
    )

    shift = session.get(Shift, shift_id) if shift_id else None
    return HandoverRead(
        handover_date=on,
        shift_id=shift_id,
        shift_name=shift.name if shift else None,
        prepared_at=now,
        raised_in_shift=len(raised),
        closed_in_shift=len(closed),
        # Split deliberately. `still_open` below is everything not fully
        # closed, which is the right list to hand to the next shift — but as a
        # COUNT it says a machine is down when it is already running again.
        machines_down=sum(1 for t in still_open if t.status not in ("resolved", "closed")),
        rca_pending=sum(1 for t in still_open if t.status == "resolved"),
        still_open=[
            line(t, "Still open — pick this up first.")
            for t in sorted(still_open, key=lambda x: x.raised_at)[:10]
        ],
        awaiting_root_cause=[
            line(t, "Running again, write-up not done.") for t in still_open if t.current_stage == 4
        ][:10],
        downtime_minutes=round(downtime, 1),
    )


@router.get(
    "/root-cause-quality",
    response_model=RootCauseQualityRead,
    summary="Root-cause quality, team level",
)
def root_cause_quality(
    principal: PrincipalDep, session: SessionDep, days: int = Query(30, ge=7, le=365)
) -> RootCauseQualityRead:
    """The percentage of closed tickets with a usable root cause.

    TEAM level only — never broken out per technician, and never sent upward
    with a name attached (addendum §4.1). Watch this number: when it starts
    falling, the analytics are three weeks from worthless, and that warning is
    the entire reason the metric exists.
    """
    end = utcnow().date()
    start = end - timedelta(days=days)
    since = datetime.combine(start, datetime.min.time(), tzinfo=UTC)

    closed = session.exec(
        scope(Ticket, principal).where(
            Ticket.current_stage >= lifecycle.CLOSED_STAGE, Ticket.closed_at >= since
        )
    ).all()
    scored = [t for t in closed if t.root_cause_score is not None]
    usable = [t for t in scored if t.root_cause_usable]

    reasons: dict[str, int] = defaultdict(int)
    for t in scored:
        if t.root_cause_usable:
            continue
        result = lifecycle.score_root_cause(
            why_1=t.why_1,
            why_2=t.why_2,
            why_3=t.why_3,
            preventive_action=t.preventive_action,
        )
        for reason in result.reasons:
            reasons[reason] += 1

    return RootCauseQualityRead(
        period_start=start,
        period_end=end,
        closed_tickets=len(closed),
        scored_tickets=len(scored),
        usable_tickets=len(usable),
        usable_percent=round(100 * len(usable) / len(scored), 1) if scored else 0.0,
        average_score=round(sum(t.root_cause_score for t in scored) / len(scored), 1)
        if scored
        else 0.0,
        top_reasons=[r for r, _ in sorted(reasons.items(), key=lambda kv: -kv[1])[:3]],
    )


@router.get("/{ticket_id}", response_model=TicketRead, summary="One ticket")
def get_ticket(ticket_id: UUID, principal: Operational, session: SessionDep) -> TicketRead:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(ticket, principal)

    machine = session.get(Machine, ticket.machine_id)
    section = session.get(Section, ticket.section_id)
    raiser = session.get(User, ticket.raised_by)
    repeats = _repeat_counts(session, principal)
    return _to_read(
        ticket,
        machine,
        section,
        raiser.name if raiser else "—",
        repeats.get((ticket.machine_id, ticket.category_id), 1),
        utcnow(),
        (e.name if (e := session.get(User, ticket.last_edited_by)) else None)
        if ticket.last_edited_by
        else None,
        **_pending_read(session, [ticket.id]).get(ticket.id, {}),
    )


# ---------------------------------------------------------------------------
# Advance
# ---------------------------------------------------------------------------


@router.post("/{ticket_id}/events", response_model=TicketRead, summary="Advance a ticket")
def append_event(
    ticket_id: UUID, body: TicketEventCreate, principal: PrincipalDep, session: SessionDep
) -> TicketRead:
    """Append one immutable event and update the projection.

    Stages move forward only. A duplicate transition is recorded as a NOOP
    rather than rejected, so it stays visible in the audit trail — two devices
    acknowledging the same ticket offline is a normal thing that happened, not
    an error.
    """
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(ticket, principal)

    # V5 §5.4 settles both halves of what `verify_close` used to gate. Every
    # ticket is self-closed by the person who solved it, with no approval step,
    # so closing is part of working it. Reopening is deliberately wider —
    # Maintenance, Supervisor, Manager and Admin all hold it, because the only
    # real safety net against a premature close is somebody noticing the
    # machine is still broken.
    needed = "reopen_ticket" if body.type == "REOPENED" else "work_ticket"
    if not principal.can(needed):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Your role does not have access to this."
        )

    event_id = body.event_id or _new_uuid()
    if session.get(TicketEvent, event_id) is not None:
        # Idempotent retry over a flaky connection. Not an error.
        return get_ticket(ticket_id, principal, session)

    now = utcnow()
    client_ts = body.client_ts or now
    if client_ts > now + timedelta(hours=24):
        client_ts = now

    target = STAGE_FOR_EVENT[body.type]
    is_noop = body.type != "REOPENED" and target <= ticket.current_stage

    session.add(
        TicketEvent(
            event_id=event_id,
            ticket_id=ticket.id,
            plant_id=ticket.plant_id,
            unit_id=ticket.unit_id,
            type="NOOP" if is_noop else body.type,
            actor_id=principal.user_id,
            device_id=body.device_id,
            payload=body.model_dump(exclude_none=True, exclude={"event_id", "client_ts"}),
            client_ts=client_ts,
        )
    )

    if not is_noop:
        _apply(ticket, body, principal, session, client_ts)

    session.add(ticket)
    session.commit()
    return get_ticket(ticket_id, principal, session)


def _apply(
    ticket: Ticket,
    body: TicketEventCreate,
    principal: Principal,
    session: SessionDep,
    ts: datetime,
) -> None:
    """Fold one event into the ticket projection."""
    match body.type:
        case "ACKNOWLEDGED":
            ticket.current_stage = 1
            ticket.status = "acknowledged"
            ticket.acked_at = ts
            ticket.acked_by = principal.user_id

        case "MATERIAL_RECORDED":
            ticket.current_stage = 2
            ticket.material_at = ts
            if body.material_source in {"store", "purchase"} and body.material_name:
                session.add(
                    TicketMaterial(
                        plant_id=ticket.plant_id,
                        unit_id=ticket.unit_id,
                        ticket_id=ticket.id,
                        source=body.material_source,
                        name=body.material_name,
                        qty=body.material_qty,
                        cost=body.material_cost,
                        bin_location=body.material_bin,
                        vendor=body.material_vendor,
                        po_number=body.material_po,
                    )
                )

        case "REPAIR_STARTED":
            ticket.current_stage = 3
            ticket.status = "in_progress"
            ticket.repair_at = ts

        case "RESOLVED":
            if not (body.immediate_correction or "").strip():
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Describe what got it running again.",
                )
            ticket.current_stage = 4
            # The HALF-CLOSE. The machine is back in service from this instant:
            # it leaves the Pending count and both closure-integrity flags key
            # off this moment, not off the eventual full close, which can lag
            # by days if the engineer got pulled onto another breakdown.
            ticket.status = "resolved"
            ticket.resolved_at = ts
            ticket.resolved_by = principal.user_id
            ticket.immediate_correction = body.immediate_correction.strip()
            classify.classify(ticket, session)
            # V5 §9 sends a High result to Supervisors and Managers for
            # awareness — no action is asked of them, so the wording asks for
            # none. Fired here rather than by the worker because the number
            # exists exactly now and is never recomputed.
            if ticket.criticality_calculated == "High":
                machine = session.get(Machine, ticket.machine_id)
                notify.ticket_flagged(
                    session,
                    machine_code=machine.code if machine else "—",
                    reason=(
                        f"Repair took {ticket.solve_minutes:.0f} minutes of actual work."
                        if ticket.solve_minutes is not None
                        else "The repair came out High."
                    ),
                    by=principal.user_id,
                )

        case "DIAGNOSED":
            if not (body.why_1 or "").strip():
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Answer at least the first why.",
                )
            ticket.current_stage = 5
            ticket.diagnosis_at = ts
            ticket.why_1 = (body.why_1 or "").strip() or None
            ticket.why_2 = (body.why_2 or "").strip() or None
            ticket.why_3 = (body.why_3 or "").strip() or None
            ticket.preventive_action = (body.preventive_action or "").strip() or None
            ticket.sheets_after_sanding = body.sheets_after_sanding
            ticket.root_cause = lifecycle.render_root_cause(
                ticket.why_1, ticket.why_2, ticket.why_3
            )

            # Compare against this technician's own previous entry for this
            # machine. Four breakdowns with four identical root causes is the
            # signature of a field being filled rather than answered.
            previous = session.exec(
                select(Ticket.why_1)
                .where(
                    Ticket.machine_id == ticket.machine_id,
                    Ticket.id != ticket.id,
                    Ticket.why_1.is_not(None),
                )
                .order_by(Ticket.diagnosis_at.desc())
                .limit(1)
            ).first()

            result = lifecycle.score_root_cause(
                why_1=ticket.why_1,
                why_2=ticket.why_2,
                why_3=ticket.why_3,
                preventive_action=ticket.preventive_action,
                previous_for_machine=previous,
            )
            ticket.root_cause_score = result.score
            ticket.root_cause_usable = result.usable

        case "CLOSED":
            if body.rating is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Rate the resolution before closing.",
                )
            ticket.current_stage = 6
            ticket.status = "closed"
            ticket.closed_at = ts
            ticket.closed_by = principal.user_id
            ticket.rating = body.rating

        case "REOPENED":
            # The one backwards move in the system, and it is explicit.
            ticket.current_stage = 3
            ticket.status = "correction_pending"
            ticket.reopen_count += 1
            ticket.resolved_at = None
            ticket.diagnosis_at = None
            ticket.closed_at = None
            ticket.rating = None
            # The previous verdict described a repair that did not hold. Left
            # in place it would keep reporting a 20-minute Low on a machine
            # that is broken again; the fresh Correction Complete recomputes it
            # over the whole of the second attempt.
            ticket.solve_minutes = None
            ticket.criticality_calculated = None

