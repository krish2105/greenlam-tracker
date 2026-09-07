"""Paper rolls through the impregnator.

WHY THIS ENDPOINT EXISTS AT ALL

Everything else in this system records what already went wrong. This records
the thing that causes it. Blistering appears at the press, so the press gets
blamed and re-plated — but it is mostly created here: residual volatiles in
the treated paper flash to vapour under the hot platen and lift the layers.

`vc_percent` is that number, and until this endpoint existed nothing in the
plant's data had it.

THE ALERT IS THE FEATURE, AND IT FIRES ON WRITE

The reading is judged against the grade's window at the moment it is saved,
and the verdict comes straight back in the response so the app can show it
while the roll is still on the floor. A chart that colours last week's VC red
is a post-mortem; a warning before the roll reaches the press is prevention,
and only one of those changes an outcome.

IT WARNS. IT NEVER BLOCKS.

An out-of-spec roll saves. It is flagged, it is visible, and the operator is
told — but the entry succeeds. The moment you force someone to choose between
an honest reading and getting on with their shift, they stop entering honest
readings, and the data this whole feature depends on quietly becomes fiction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import select

from ..deps import CanLogProduction, PrincipalDep, SessionDep
from ..models import (
    ImpregnationLog,
    Machine,
    PaperGrade,
    ProductionLog,
    ResinBatch,
    spec_breaches,
)
from ..schemas_impregnation import (
    ImpregnationCreate,
    ImpregnationRead,
    RollTraceRead,
)
from ..tenancy import assert_visible, scope

router = APIRouter(prefix="/impregnation", tags=["impregnation"])

_DAYS_Q = Query(30, ge=1, le=365)
_LIMIT_Q = Query(100, ge=1, le=500)


def _to_read(
    row: ImpregnationLog, grade: PaperGrade | None, batch_no: str | None = None
) -> ImpregnationRead:
    return ImpregnationRead(
        id=row.id,
        machine_id=row.machine_id,
        shift_id=row.shift_id,
        log_date=row.log_date,
        roll_no=row.roll_no,
        gsm=row.gsm,
        thickness_before=row.thickness_before,
        paper_grade_id=row.paper_grade_id,
        paper_grade_name=grade.name if grade else None,
        paper_company_id=row.paper_company_id,
        cut_size_id=row.cut_size_id,
        thickness_after=row.thickness_after,
        resin_batch_id=row.resin_batch_id,
        resin_batch_no=batch_no,
        rc_percent=row.rc_percent,
        vc_percent=row.vc_percent,
        out_of_spec=row.out_of_spec,
        spec_note=row.spec_note,
        rc_min=grade.rc_min if grade else None,
        rc_max=grade.rc_max if grade else None,
        vc_min=grade.vc_min if grade else None,
        vc_max=grade.vc_max if grade else None,
    )


@router.post(
    "",
    response_model=ImpregnationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Log a paper roll",
)
def create_roll(
    body: ImpregnationCreate, principal: CanLogProduction, session: SessionDep
) -> ImpregnationRead:
    machine = session.get(Machine, body.machine_id)
    assert_visible(machine, principal)

    existing = session.exec(
        scope(ImpregnationLog, principal).where(ImpregnationLog.roll_no == body.roll_no)
    ).first()
    if existing is not None:
        # Roll numbers are the join key for the whole traceability chain. Two
        # rolls sharing one number would make every reject traced to it
        # ambiguous, so this is a refusal rather than a warning.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Roll {body.roll_no} is already logged.",
        )

    grade = None
    if body.paper_grade_id is not None:
        grade = session.get(PaperGrade, body.paper_grade_id)
        assert_visible(grade, principal)

    batch = None
    if body.resin_batch_id is not None:
        batch = session.get(ResinBatch, body.resin_batch_id)
        if batch is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such resin batch.")
        # Scoped like everything else. A roll pointing at another plant's batch
        # would produce a trace that crosses plants and means nothing.
        assert_visible(batch, principal)

    breaches = spec_breaches(grade, body.rc_percent, body.vc_percent)

    row = ImpregnationLog(
        id=uuid4(),
        plant_id=machine.plant_id,
        unit_id=machine.unit_id,
        machine_id=machine.id,
        shift_id=body.shift_id,
        resin_batch_id=body.resin_batch_id,
        log_date=body.log_date,
        roll_no=body.roll_no.strip(),
        gsm=body.gsm,
        thickness_before=body.thickness_before,
        paper_grade_id=body.paper_grade_id,
        paper_company_id=body.paper_company_id,
        cut_size_id=body.cut_size_id,
        thickness_after=body.thickness_after,
        rc_percent=body.rc_percent,
        vc_percent=body.vc_percent,
        # Stored, not derived on read. If the grade's limits are edited later,
        # this roll keeps saying what the operator was actually told.
        out_of_spec=bool(breaches),
        spec_note="; ".join(breaches) or None,
        logged_by=principal.user_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_read(row, grade)


@router.get("", response_model=list[ImpregnationRead], summary="Recent rolls")
def list_rolls(
    principal: PrincipalDep,
    session: SessionDep,
    days: int = _DAYS_Q,
    limit: int = _LIMIT_Q,
    only_out_of_spec: bool = False,
) -> list[ImpregnationRead]:
    since = (datetime.now(UTC) - timedelta(days=days)).date()
    stmt = (
        scope(ImpregnationLog, principal)
        .where(ImpregnationLog.log_date >= since)
        .order_by(ImpregnationLog.log_date.desc(), ImpregnationLog.roll_no.desc())
        .limit(limit)
    )
    if only_out_of_spec:
        stmt = stmt.where(ImpregnationLog.out_of_spec.is_(True))
    rows = session.exec(stmt).all()
    grades = {
        g.id: g for g in session.exec(scope(PaperGrade, principal)).all()
    }
    return [_to_read(r, grades.get(r.paper_grade_id)) for r in rows]


@router.get(
    "/recent-rolls",
    response_model=list[str],
    summary="Roll numbers for the press form",
)
def recent_roll_numbers(
    principal: PrincipalDep, session: SessionDep, limit: int = _LIMIT_Q
) -> list[str]:
    """Newest first, because a press operator wants today's roll, not 2023's.

    A field people skip breaks the whole traceability chain, and the fastest
    way to make them skip it is a four-hundred-item list in arbitrary order.
    """
    rows = session.exec(
        scope(ImpregnationLog, principal)
        .order_by(ImpregnationLog.log_date.desc(), ImpregnationLog.roll_no.desc())
        .limit(limit)
    ).all()
    return [r.roll_no for r in rows]


@router.get(
    "/trace/{roll_no}",
    response_model=RollTraceRead,
    summary="Everything pressed from one roll",
)
def trace_roll(roll_no: str, principal: PrincipalDep, session: SessionDep) -> RollTraceRead:
    """Walk the chain forwards: roll → the sheets made from it.

    The backwards walk — from a bad batch to the paper — is the same join read
    the other way, and lives on the production row as `impregnation_log_id`.
    """
    roll = session.exec(
        scope(ImpregnationLog, principal).where(ImpregnationLog.roll_no == roll_no)
    ).first()
    if roll is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such roll.")

    runs = session.exec(
        select(ProductionLog).where(ProductionLog.impregnation_log_id == roll.id)
    ).all()
    produced = sum(r.produced_qty for r in runs)
    rejected = sum(r.rejected_qty for r in runs)
    grade = session.get(PaperGrade, roll.paper_grade_id) if roll.paper_grade_id else None
    # One step further back than the chain used to reach: the resin.
    batch = session.get(ResinBatch, roll.resin_batch_id) if roll.resin_batch_id else None

    return RollTraceRead(
        roll=_to_read(roll, grade, batch.batch_no if batch else None),
        resin_batch_no=batch.batch_no if batch else None,
        resin_batch_rejected=batch.rejected_qty if batch else None,
        runs=len(runs),
        produced=produced,
        rejected=rejected,
        reject_percent=round(100 * rejected / produced, 2) if produced else 0.0,
    )
