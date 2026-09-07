"""Production logging and quality analytics.

The other half of the system. Maintenance answers "why did it stop"; this
answers "what did we make and what did we throw away", and the spec's most
valuable derived metric lives across the two: reject-rate spikes on a machine
within ±48 h of a breakdown (§6.1). If Sanding-2's reject rate climbs before it
fails, that is a leading indicator, and finding one is what justifies the whole
project to leadership.

Same access model as tickets: aggregates are readable by every tier because
they carry no name and no ticket, while the individual log rows are
operational detail.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from pydantic import Field as PField
from sqlmodel import select

from ..deps import CanLogProduction, Operational, PrincipalDep, SessionDep
from ..models import (
    ImpregnationLog,
    Machine,
    ProductionLog,
    RejectReason,
    ResinBatch,
    Section,
    Shift,
    Ticket,
    User,
    utcnow,
)
from ..schemas_production import (
    MachinePerformance,
    ProductionAnalytics,
    ProductionCreate,
    ProductionRead,
    RejectSlice,
    RollQualityRead,
    SegmentRow,
)
from ..tenancy import assert_visible, scope

router = APIRouter(prefix="/production", tags=["production"])

# Analytics windows. Seven days is the floor because an MTTR or a reject rate
# over three days is noise dressed as a trend.
_DAYS_Q = Query(90, ge=7, le=365)

# The row list is a different question — "what has been logged today" is the
# one the daily entry log (V5 §6.4) asks at every handover, and it is asked of
# rows rather than of an average, so a single day is a legitimate answer.
_LIST_DAYS_Q = Query(90, ge=1, le=365)
_LIMIT_Q = Query(100, le=500)

# Window either side of a breakdown in which a reject spike is considered
# related. ±48h is the spec's figure; it is a starting hypothesis, not a law.
CORRELATION_HOURS = 48


@router.post(
    "",
    response_model=ProductionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Log production for a shift",
)
def log_production(
    body: ProductionCreate, principal: CanLogProduction, session: SessionDep
) -> ProductionRead:
    """One row per machine per shift per product.

    A rejection without a reason is refused — the database CHECK enforces it
    too. A Pareto with an "unknown" bar larger than every named cause tells
    nobody anything, and once operators learn they can skip the field they
    always will.
    """
    machine = session.get(Machine, body.machine_id)
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Machine not found")
    assert_visible(machine, principal)

    if body.rejected_qty > 0 and body.reject_reason_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose a reject reason — a rejection with no reason cannot be acted on.",
        )
    if body.rejected_qty > body.produced_qty:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Rejected cannot be more than produced.",
        )

    # The Load No. is what the press cycle is planned around, and it is the
    # only handle a finished sheet has back to the load it belongs to. Missing
    # it at the press breaks the chain for every downstream row that references
    # the same load, so this is the one place it is required.
    #
    # Everywhere else it is optional: cutting and sanding carry it where the
    # operator has it, and forcing it there would only teach people to type
    # something.
    load_no = (body.load_no or "").strip() or None
    if machine.production_form == "press" and load_no is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A press entry needs its Load No. — it is what ties these sheets to the load.",
        )

    # Resolve the roll number to a roll, if one was given. Unknown numbers are
    # accepted as "no roll" rather than refused: a press operator typing a roll
    # that has not been logged yet is a sequencing problem on the floor, and
    # rejecting their production entry over it would lose the sheet count too.
    roll_id = None
    if body.roll_no:
        roll = session.exec(
            scope(ImpregnationLog, principal).where(
                ImpregnationLog.roll_no == body.roll_no.strip()
            )
        ).first()
        roll_id = roll.id if roll else None

    row = ProductionLog(
        id=uuid4(),
        plant_id=machine.plant_id,
        unit_id=machine.unit_id,
        section_id=machine.section_id,
        machine_id=machine.id,
        shift_id=body.shift_id,
        log_date=body.log_date or utcnow().date(),
        size=body.size.strip(),
        texture=body.texture.strip(),
        thickness=body.thickness,
        design_id=body.design_id,
        size_id=body.size_id,
        texture_id=body.texture_id,
        thickness_id=body.thickness_id,
        impregnation_log_id=roll_id,
        load_no=load_no,
        produced_qty=body.produced_qty,
        rejected_qty=body.rejected_qty,
        reject_reason_id=body.reject_reason_id,
        target_qty=body.target_qty,
        logged_by=principal.user_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_read(row, session, principal)


def _to_read(row: ProductionLog, session: SessionDep, principal) -> ProductionRead:
    machine = session.get(Machine, row.machine_id) if row.machine_id else None
    shift = session.get(Shift, row.shift_id) if row.shift_id else None
    reason = session.get(RejectReason, row.reject_reason_id) if row.reject_reason_id else None
    logger = session.get(User, row.logged_by)
    editor = session.get(User, row.last_edited_by) if row.last_edited_by else None
    total = row.produced_qty + row.rejected_qty
    return ProductionRead(
        id=row.id,
        log_date=row.log_date,
        machine_code=machine.code if machine else "—",
        shift_name=shift.name if shift else None,
        load_no=row.load_no,
        size=row.size,
        texture=row.texture,
        produced_qty=row.produced_qty,
        rejected_qty=row.rejected_qty,
        reject_reason=reason.name if reason else None,
        target_qty=row.target_qty,
        # Rejected over TOTAL made, not over good output. Dividing by produced
        # alone flatters the number, and the two diverge exactly when things
        # are going badly.
        reject_percent=round(100 * row.rejected_qty / total, 2) if total else 0.0,
        logged_by_name=logger.name if logger else "—",
        last_edited_at=row.last_edited_at,
        last_edited_by_name=editor.name if editor else None,
    )


@router.get("", response_model=list[ProductionRead], summary="Production log")
def list_production(
    principal: Operational,
    session: SessionDep,
    days: int = _LIST_DAYS_Q,
    limit: int = _LIMIT_Q,
) -> list[ProductionRead]:
    """Individual rows. Operational roles only — corporate uses /analytics."""
    since = (utcnow() - timedelta(days=days)).date()
    rows = session.exec(
        scope(ProductionLog, principal)
        .where(ProductionLog.log_date >= since)
        .order_by(ProductionLog.log_date.desc())
        .limit(limit)
    ).all()
    return [_to_read(r, session, principal) for r in rows]


@router.get(
    "/analytics", response_model=ProductionAnalytics, summary="Quality and output analytics"
)
def production_analytics(
    principal: PrincipalDep, session: SessionDep, days: int = _DAYS_Q
) -> ProductionAnalytics:
    """Reject Pareto and segment breakdowns. Readable by every tier.

    Segments are where root causes hide (spec §6.1): a texture that rejects at
    twice the rate of the others, or a shift that does, is a finding you can
    only see if the dimension was recorded from day one.
    """
    now = utcnow()
    since = (now - timedelta(days=days)).date()

    rows = session.exec(
        scope(ProductionLog, principal).where(ProductionLog.log_date >= since)
    ).all()

    machines = {m.id: m for m in session.exec(scope(Machine, principal)).all()}
    sections = {s.id: s for s in session.exec(scope(Section, principal)).all()}
    shifts = {s.id: s for s in session.exec(scope(Shift, principal)).all()}
    reasons = {r.id: r for r in session.exec(scope(RejectReason, principal)).all()}

    produced = sum(r.produced_qty for r in rows)
    rejected = sum(r.rejected_qty for r in rows)
    target = sum(r.target_qty or 0 for r in rows)
    total_made = produced + rejected

    # --- reject Pareto by reason ---
    by_reason: dict[int | None, int] = defaultdict(int)
    for r in rows:
        if r.rejected_qty:
            by_reason[r.reject_reason_id] += r.rejected_qty

    ordered = sorted(by_reason.items(), key=lambda kv: kv[1], reverse=True)
    running = 0
    pareto = []
    for reason_id, qty in ordered:
        running += qty
        pareto.append(
            RejectSlice(
                label=reasons[reason_id].name if reason_id in reasons else "Unrecorded",
                quantity=qty,
                percent=round(100 * qty / rejected, 1) if rejected else 0.0,
                cumulative_percent=round(100 * running / rejected, 1) if rejected else 0.0,
            )
        )

    def segment(key_fn, label_fn) -> list[SegmentRow]:
        agg: dict[object, list[int]] = defaultdict(lambda: [0, 0])
        for r in rows:
            k = key_fn(r)
            if k is None:
                continue
            agg[k][0] += r.produced_qty
            agg[k][1] += r.rejected_qty
        out = []
        for k, (made, bad) in agg.items():
            total = made + bad
            out.append(
                SegmentRow(
                    label=label_fn(k),
                    produced=made,
                    rejected=bad,
                    reject_percent=round(100 * bad / total, 2) if total else 0.0,
                )
            )
        return sorted(out, key=lambda s: s.reject_percent, reverse=True)

    daily: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        daily[r.log_date][0] += r.produced_qty
        daily[r.log_date][1] += r.rejected_qty

    return ProductionAnalytics(
        generated_at=now,
        period_days=days,
        period_start=since,
        resolution="operational",
        total_produced=produced,
        total_rejected=rejected,
        reject_percent=round(100 * rejected / total_made, 2) if total_made else 0.0,
        target_total=target or None,
        output_vs_target_percent=round(100 * produced / target, 1) if target else None,
        reject_pareto=pareto,
        by_texture=segment(lambda r: r.texture, lambda k: str(k)),
        by_shift=segment(lambda r: r.shift_id, lambda k: shifts[k].name if k in shifts else "—"),
        by_machine=segment(
            lambda r: r.machine_id, lambda k: machines[k].code if k in machines else "—"
        )[:10],
        by_section=segment(
            lambda r: r.section_id, lambda k: sections[k].name if k in sections else "—"
        ),
        daily=[
            {
                "date": day.isoformat(),
                "produced": v[0],
                "rejected": v[1],
                "reject_percent": round(100 * v[1] / (v[0] + v[1]), 2) if (v[0] + v[1]) else 0.0,
            }
            for day, v in sorted(daily.items())
        ],
        breakdown_correlation=_correlate(rows, session, principal, since, now),
    )


def _correlate(
    rows: list[ProductionLog], session: SessionDep, principal, since: date, now: datetime
) -> list[dict]:
    """Reject rate near a breakdown vs away from one, per machine.

    Spec §6.1: "the one derived metric worth building". If a machine's reject
    rate is materially higher in the ±48h around its breakdowns than the rest
    of the time, quality is degrading before the failure — which turns this
    from a logbook into an early-warning system.

    Deliberately conservative: machines with too little data are skipped rather
    than reported with a noisy ratio, and the payload says how many breakdowns
    the finding rests on so a reader can judge it.
    """
    tickets = session.exec(
        scope(Ticket, principal).where(
            Ticket.raised_at >= datetime.combine(since, datetime.min.time(), tzinfo=UTC),
            Ticket.downtime_type == "breakdown",
        )
    ).all()
    if not tickets:
        return []

    failure_days: dict[int, set[date]] = defaultdict(set)
    for t in tickets:
        day = t.raised_at.date()
        span = CORRELATION_HOURS // 24
        for offset in range(-span, span + 1):
            failure_days[t.machine_id].add(day + timedelta(days=offset))

    machines = {m.id: m for m in session.exec(scope(Machine, principal)).all()}
    near: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    away: dict[int, list[int]] = defaultdict(lambda: [0, 0])

    for r in rows:
        if r.machine_id is None:
            continue
        bucket = near if r.log_date in failure_days.get(r.machine_id, set()) else away
        bucket[r.machine_id][0] += r.produced_qty
        bucket[r.machine_id][1] += r.rejected_qty

    findings = []
    for machine_id, (made_n, bad_n) in near.items():
        made_a, bad_a = away.get(machine_id, [0, 0])
        total_n, total_a = made_n + bad_n, made_a + bad_a
        # Too little either side and the ratio is noise, not a finding.
        if total_n < 2000 or total_a < 2000:
            continue
        rate_near = 100 * bad_n / total_n
        rate_away = 100 * bad_a / total_a
        if rate_away <= 0:
            continue
        lift = round(100 * (rate_near - rate_away) / rate_away, 1)
        if abs(lift) < 10:  # within noise; not worth a line on a dashboard
            continue
        findings.append(
            {
                "machine_code": machines[machine_id].code if machine_id in machines else "—",
                "reject_percent_near_breakdown": round(rate_near, 2),
                "reject_percent_otherwise": round(rate_away, 2),
                "lift_percent": lift,
                "breakdowns": sum(1 for t in tickets if t.machine_id == machine_id),
            }
        )
    return sorted(findings, key=lambda f: f["lift_percent"], reverse=True)[:5]


# ---------------------------------------------------------------------------
# Machine performance — the question the whole system exists to answer
# ---------------------------------------------------------------------------
@router.get(
    "/machine-performance",
    response_model=list[MachinePerformance],
    summary="Downtime and quality per machine, side by side",
)
def machine_performance(
    principal: PrincipalDep, session: SessionDep, days: int = _DAYS_Q
) -> list[MachinePerformance]:
    """Is this machine worst because it BREAKS, or because it makes SCRAP?

    Those are different problems with different owners and different fixes, and
    until now a reader had to hold numbers from four separate charts in their
    head to tell them apart. One row per machine, both sides on it.

    Impregnators get RC and VC instead of a reject rate, because they do not
    produce sheets — they produce the paper the sheets are pressed from, and
    their quality signal is the spec window, not scrap.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    since_day = since.date()

    machines = {m.id: m for m in session.exec(scope(Machine, principal)).all()}
    sections = {s.id: s.name for s in session.exec(scope(Section, principal)).all()}

    downtime: dict[int, list[float]] = defaultdict(list)
    breakdowns: dict[int, int] = defaultdict(int)
    for t in session.exec(
        scope(Ticket, principal)
        .where(Ticket.raised_at >= since)
        .where(Ticket.downtime_type == "breakdown")
    ).all():
        if t.machine_id is None:
            continue
        breakdowns[t.machine_id] += 1
        if t.resolved_at and t.raised_at:
            downtime[t.machine_id].append(
                (t.resolved_at - t.raised_at).total_seconds() / 60
            )

    produced: dict[int, int] = defaultdict(int)
    rejected: dict[int, int] = defaultdict(int)
    for p in session.exec(
        scope(ProductionLog, principal).where(ProductionLog.log_date >= since_day)
    ).all():
        if p.machine_id is None:
            continue
        produced[p.machine_id] += p.produced_qty
        rejected[p.machine_id] += p.rejected_qty

    rc_sum: dict[int, float] = defaultdict(float)
    vc_sum: dict[int, float] = defaultdict(float)
    roll_n: dict[int, int] = defaultdict(int)
    off_spec: dict[int, int] = defaultdict(int)
    for r in session.exec(
        scope(ImpregnationLog, principal).where(ImpregnationLog.log_date >= since_day)
    ).all():
        roll_n[r.machine_id] += 1
        if r.rc_percent is not None:
            rc_sum[r.machine_id] += float(r.rc_percent)
        if r.vc_percent is not None:
            vc_sum[r.machine_id] += float(r.vc_percent)
        if r.out_of_spec:
            off_spec[r.machine_id] += 1

    # Same all-or-nothing rule as the plant dashboard: scheduled hours only
    # once EVERY machine has one. A table where some rows divide by 24 and
    # others by 16 ranks machines on two different denominators, and the row
    # that moved is the one somebody happened to fill in last.
    schedules = {
        mid: float(m.scheduled_hours_per_day)
        for mid, m in machines.items()
        if m.scheduled_hours_per_day is not None
    }
    on_schedule = bool(machines) and len(schedules) >= len(machines)

    rows: list[MachinePerformance] = []
    for machine_id, machine in machines.items():
        mins = downtime.get(machine_id, [])
        made = produced.get(machine_id, 0)
        scrapped = rejected.get(machine_id, 0)
        rolls = roll_n.get(machine_id, 0)
        if not mins and not made and not rolls:
            continue
        total_down = sum(mins)
        rows.append(
            MachinePerformance(
                machine_id=machine_id,
                machine_code=machine.code,
                section_name=sections.get(machine.section_id, "—"),
                downtime_minutes=round(total_down, 1),
                breakdowns=breakdowns.get(machine_id, 0),
                mttr_minutes=round(total_down / len(mins), 1) if mins else None,
                # Calendar hours until the plant supplies a schedule for every
                # machine, and labelled as such everywhere it is shown. Guessing
                # the hours would make this a number nobody can defend.
                mtbf_hours=(
                    round(
                        (days * (schedules[machine_id] if on_schedule else 24.0))
                        / breakdowns[machine_id],
                        1,
                    )
                    if breakdowns.get(machine_id)
                    else None
                ),
                produced=made,
                rejected=scrapped,
                reject_percent=round(100 * scrapped / made, 2) if made else None,
                rolls=rolls,
                avg_rc=round(rc_sum[machine_id] / rolls, 2) if rolls else None,
                avg_vc=round(vc_sum[machine_id] / rolls, 2) if rolls else None,
                out_of_spec_rolls=off_spec.get(machine_id, 0),
            )
        )

    rows.sort(key=lambda r: r.downtime_minutes, reverse=True)
    return rows


@router.get(
    "/roll-quality",
    response_model=RollQualityRead,
    summary="Does out-of-spec paper actually produce more rejects?",
)
def roll_quality(
    principal: PrincipalDep, session: SessionDep, days: int = _DAYS_Q
) -> RollQualityRead:
    """The hypothesis, tested against the plant's own numbers.

    This is the single most important figure the system can produce, and it is
    deliberately reported as a comparison rather than a claim: here is the
    reject rate on sheets pressed from paper that was inside its spec window,
    and here it is on paper that was outside. If the second is not higher, the
    theory is wrong and the board should be told that plainly.
    """
    since_day = (datetime.now(UTC) - timedelta(days=days)).date()

    rolls = {
        r.id: r
        for r in session.exec(
            scope(ImpregnationLog, principal).where(ImpregnationLog.log_date >= since_day)
        ).all()
    }
    buckets = {True: [0, 0], False: [0, 0]}  # out_of_spec -> [produced, rejected]
    linked = 0
    for p in session.exec(
        scope(ProductionLog, principal).where(ProductionLog.log_date >= since_day)
    ).all():
        roll = rolls.get(p.impregnation_log_id) if p.impregnation_log_id else None
        if roll is None:
            continue
        linked += 1
        bucket = buckets[roll.out_of_spec]
        bucket[0] += p.produced_qty
        bucket[1] += p.rejected_qty

    def rate(pair: list[int]) -> float | None:
        return round(100 * pair[1] / pair[0], 2) if pair[0] else None

    in_spec = rate(buckets[False])
    out_spec = rate(buckets[True])
    return RollQualityRead(
        linked_runs=linked,
        in_spec_reject_percent=in_spec,
        out_of_spec_reject_percent=out_spec,
        lift_percent=(
            round(100 * (out_spec - in_spec) / in_spec, 1)
            if in_spec and out_spec
            else None
        ),
        # Small samples make a big-looking lift meaningless. Say so rather than
        # letting a two-roll coincidence become a slide.
        enough_data=buckets[True][0] >= 500 and buckets[False][0] >= 500,
    )


# ---------------------------------------------------------------------------
# Resin batches
# ---------------------------------------------------------------------------


class ResinBatchCreate(BaseModel):
    """A batch out of a resin kettle.

    `batch_no` is the identifier an impregnated roll will later reference. It
    is OPTIONAL: the resin register kept on the floor has not been confirmed
    (V5 §6.2, §16), and a required field the operator cannot answer gets filled
    with something rather than left empty. Where a number is given it must be
    unique in the plant, because a roll points at it by name.

    Everything else is optional too — a kettle operator with a clipboard should
    be able to record the batch now and the inspection result when it is known.
    """

    id: UUID | None = None  # UUIDv7 from the client, so a retry is a no-op
    machine_id: int
    shift_id: int | None = None
    batch_no: str | None = PField(default=None, max_length=64)
    log_date: date | None = None
    quantity: Decimal | None = PField(default=None, ge=0)
    unit_of_measure: str | None = PField(default=None, max_length=16)
    accepted_qty: Decimal | None = PField(default=None, ge=0)
    rejected_qty: Decimal | None = PField(default=None, ge=0)
    reject_reason_id: int | None = None
    notes: str | None = None


class ResinBatchRead(BaseModel):
    id: UUID
    machine_id: int
    machine_code: str
    batch_no: str | None
    log_date: date
    quantity: Decimal | None
    unit_of_measure: str | None
    accepted_qty: Decimal | None
    rejected_qty: Decimal | None


@router.post(
    "/resin-batches",
    response_model=ResinBatchRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a resin batch",
)
def log_resin_batch(
    body: ResinBatchCreate, principal: CanLogProduction, session: SessionDep
) -> ResinBatchRead:
    machine = session.get(Machine, body.machine_id)
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Machine not found")
    assert_visible(machine, principal)

    batch_no = (body.batch_no or "").strip() or None
    if batch_no is not None:
        existing = session.exec(
            select(ResinBatch).where(
                ResinBatch.plant_id == machine.plant_id, ResinBatch.batch_no == batch_no
            )
        ).first()
        if existing is not None:
            # 409 rather than a silent overwrite: the number is what a roll
            # will point at, and quietly merging two batches under one number
            # would make a later trace wrong without anyone noticing.
            #
            # Only reachable when a number was given. Two unnumbered batches
            # are two batches, not a collision — they simply cannot be traced
            # to, which is the honest consequence of not having a number.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"Batch {batch_no} is already recorded on {machine.code}.",
            )

    if (
        body.rejected_qty is not None
        and body.quantity is not None
        and body.rejected_qty > body.quantity
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Rejected cannot be more than the batch quantity.",
        )
    if body.rejected_qty and body.reject_reason_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose a reject reason — a rejection with no reason cannot be acted on.",
        )

    batch = ResinBatch(
        id=body.id or uuid4(),
        plant_id=machine.plant_id,
        unit_id=machine.unit_id,
        machine_id=machine.id,
        shift_id=body.shift_id,
        batch_no=batch_no,
        log_date=body.log_date or datetime.now(UTC).date(),
        quantity=body.quantity,
        unit_of_measure=body.unit_of_measure,
        accepted_qty=body.accepted_qty,
        rejected_qty=body.rejected_qty,
        reject_reason_id=body.reject_reason_id,
        notes=body.notes,
        logged_by=principal.user_id,
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return ResinBatchRead(
        id=batch.id,
        machine_id=batch.machine_id,
        machine_code=machine.code,
        batch_no=batch.batch_no,
        log_date=batch.log_date,
        quantity=batch.quantity,
        unit_of_measure=batch.unit_of_measure,
        accepted_qty=batch.accepted_qty,
        rejected_qty=batch.rejected_qty,
    )


@router.get("/resin-batches", response_model=list[ResinBatchRead], summary="Recent resin batches")
def list_resin_batches(
    principal: PrincipalDep, session: SessionDep, limit: int = 50
) -> list[ResinBatchRead]:
    rows = session.exec(
        scope(ResinBatch, principal).order_by(ResinBatch.created_at.desc()).limit(limit)
    ).all()
    codes = {m.id: m.code for m in session.exec(scope(Machine, principal)).all()}
    return [
        ResinBatchRead(
            id=b.id,
            machine_id=b.machine_id,
            machine_code=codes.get(b.machine_id, "—"),
            batch_no=b.batch_no,
            log_date=b.log_date,
            quantity=b.quantity,
            unit_of_measure=b.unit_of_measure,
            accepted_qty=b.accepted_qty,
            rejected_qty=b.rejected_qty,
        )
        for b in rows
    ]
