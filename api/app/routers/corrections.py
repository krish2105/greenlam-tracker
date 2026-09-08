"""Correct a record, and keep what it used to say (V5 §7).

WHAT THIS IS NOT

Not Reopen. Reopen says the machine is still broken and sends the ticket back
to Correction Pending; Correct says a keystroke was wrong and changes nothing
else. They are separate endpoints with separate words on separate buttons, and
that separation is load-bearing: a clerical fix that flipped a ticket back to
an active status would reappear in the live Pending count and could fire the
repeat-failure flag for a breakdown that never happened.

Not ordinary editing either. While a ticket is still open — including sitting
half-closed in "Resolved, RCA Pending" — its owner revises it freely through
the normal endpoints and nothing is tagged. This path begins the moment a
record is final, and everything it touches is marked "Edited" wherever it is
shown.

WHO, AND FOR HOW LONG

The person who owns the record may fix it for five hours after a ticket fully
closes, or ten after a production entry is submitted. After that it takes an
admin, and the correction is stamped `outside_window` so the difference is
visible later. Both numbers are in `lifecycle.py` with the reasoning.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from .. import classify, lifecycle
from ..deps import PrincipalDep, SessionDep
from ..models import (
    ProductionCorrection,
    ProductionLog,
    Ticket,
    TicketCorrection,
    TicketEvent,
    User,
    utcnow,
)
from ..tenancy import Principal, assert_visible

router = APIRouter(tags=["corrections"])

# Admin, in the vocabulary this codebase currently has. V5 §3 makes Admin one
# of six independent access areas; until that lands (build plan, Step 4) the
# `dashboard` role is the only one holding `edit_masters`, and it is the same
# set of people.
_ADMIN_CAPABILITY = "edit_masters"


class CorrectIn(BaseModel):
    """The fields to change, and why.

    `changes` is a sparse map — send only what is wrong. Omitting a field
    leaves it alone; sending it as null clears it, which is a real correction
    (a category chosen by mistake) and not the same thing.
    """

    changes: dict[str, Any]
    reason: str | None = None
    # V5 §13: every correction carries a client-generated id so a retry over a
    # dropped connection cannot apply the same change twice.
    submission_id: UUID | None = None


class CorrectionRead(BaseModel):
    field: str
    old_value: str | None
    new_value: str | None
    reason: str | None
    corrected_by_name: str
    corrected_at: datetime
    outside_window: bool


def _render(value: Any) -> str | None:
    """A value as the log stores it.

    NULL stays NULL rather than becoming the string "None" — the difference
    between a field that was cleared and one that was set to the word None is
    exactly the kind of thing an audit trail is asked about years later.
    """
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _coerce(field: str, value: Any, model: Any) -> Any:
    """Fit an incoming JSON value to the column it is going into.

    Pydantic cannot do this for us: `changes` is deliberately a free-form map
    so that one endpoint serves every correctable field, which means the typing
    happens here instead.
    """
    if value is None:
        return None
    current_type = type(getattr(model, field))
    try:
        if field.endswith("_at"):
            return datetime.fromisoformat(str(value))
        if field == "log_date":
            return date.fromisoformat(str(value))
        if current_type is int or field.endswith(("_id", "_qty")):
            return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field} is not in a form this field accepts.",
        ) from exc
    return value


def _validate_allowed(changes: dict[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(set(changes) - allowed)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"These cannot be corrected here: {', '.join(unknown)}.",
        )
    if not changes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nothing to correct."
        )


def _authorise(
    *,
    principal: Principal,
    owner_id: int | None,
    anchor: datetime | None,
    hours: int,
    noun: str,
) -> bool:
    """Return whether this correction is happening outside the self-edit window.

    Raises 403 when it is not allowed at all. An admin is always allowed and
    the return value tells the caller to stamp the row.
    """
    is_admin = principal.can(_ADMIN_CAPABILITY)
    inside = lifecycle.within_self_correct_window(anchor, utcnow(), hours)

    if is_admin:
        return not inside

    if owner_id != principal.user_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"Only the person who logged this {noun}, or an admin, can correct it.",
        )
    if anchor is None:
        # Still open. Revising it is ordinary work through the normal
        # endpoints, and routing it through here would tag it "Edited" for no
        # reason.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"This {noun} is not finished yet — edit it directly instead.",
        )
    if not inside:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=(
                f"The {hours}-hour window for correcting this {noun} has passed. "
                "An admin can still make the change."
            ),
        )
    return False


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------


@router.post("/tickets/{ticket_id}/correct", summary="Fix a mistake on a closed ticket")
def correct_ticket(
    ticket_id: UUID, body: CorrectIn, principal: PrincipalDep, session: SessionDep
) -> dict:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(ticket, principal)

    if body.submission_id and session.get(TicketEvent, body.submission_id) is not None:
        return {"ok": True, "applied": 0, "repeat": True}

    _validate_allowed(body.changes, lifecycle.CORRECTABLE_TICKET_FIELDS)
    outside = _authorise(
        principal=principal,
        # Handoff moves ownership, so the current owner is the person who
        # finished the job — which is who V5 §7 means by "the person who owns
        # the ticket", not whoever first acknowledged it.
        owner_id=ticket.owner_id or ticket.resolved_by or ticket.acked_by,
        anchor=ticket.closed_at,
        hours=lifecycle.TICKET_SELF_CORRECT_HOURS,
        noun="ticket",
    )

    applied = _apply_changes(
        record=ticket,
        changes=body.changes,
        log=lambda field, old, new: session.add(
            TicketCorrection(
                plant_id=ticket.plant_id,
                ticket_id=ticket.id,
                field=field,
                old_value=old,
                new_value=new,
                reason=body.reason,
                corrected_by=principal.user_id,
                outside_window=outside,
            )
        ),
    )
    if not applied:
        return {"ok": True, "applied": 0, "unchanged": True}

    # A timestamp moved means the measured repair moved with it. Leaving the
    # old verdict standing would be a half-applied fix: the visible number
    # right, the derived one quietly wrong.
    if {"repair_at", "resolved_at"} & set(applied):
        classify.classify(ticket, session)

    _mark_edited(ticket, principal.user_id)
    session.add(
        TicketEvent(
            event_id=body.submission_id or uuid4(),
            ticket_id=ticket.id,
            plant_id=ticket.plant_id,
            unit_id=ticket.unit_id,
            type="CORRECTED",
            actor_id=principal.user_id,
            payload={"fields": applied, "reason": body.reason, "outside_window": outside},
            client_ts=utcnow(),
        )
    )
    session.add(ticket)
    session.commit()
    return {"ok": True, "applied": applied, "outside_window": outside}


@router.get(
    "/tickets/{ticket_id}/corrections",
    response_model=list[CorrectionRead],
    summary="What has been changed on this ticket",
)
def ticket_corrections(
    ticket_id: UUID, principal: PrincipalDep, session: SessionDep
) -> list[CorrectionRead]:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(ticket, principal)

    rows = session.exec(
        select(TicketCorrection)
        .where(TicketCorrection.ticket_id == ticket_id)
        .order_by(TicketCorrection.corrected_at.desc())
    ).all()
    return _to_reads(rows, session)


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------


@router.post("/production/{log_id}/correct", summary="Fix a mistake on a production entry")
def correct_production(
    log_id: UUID, body: CorrectIn, principal: PrincipalDep, session: SessionDep
) -> dict:
    row = session.get(ProductionLog, log_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(row, principal)

    _validate_allowed(body.changes, lifecycle.CORRECTABLE_PRODUCTION_FIELDS)
    outside = _authorise(
        principal=principal,
        owner_id=row.logged_by,
        # The Done press, not the first save (V5 §6.3). An entry started on
        # Monday and finished on Wednesday would otherwise arrive with its
        # ten-hour window already spent. A draft has no anchor at all, and
        # `_authorise` answers that with "edit it directly instead", which is
        # exactly right — PUT /production/{id} is that edit.
        anchor=row.submitted_at,
        hours=lifecycle.PRODUCTION_SELF_CORRECT_HOURS,
        noun="entry",
    )

    # Validated BEFORE anything is written, against the values the row WOULD
    # have. The same rules that refused the entry at creation — without them,
    # Correct is a hole straight through every one of them, and the numbers it
    # would let through are the ones the whole reject analysis rests on.
    #
    # Checking after mutating would also work, because an HTTPException leaves
    # the session uncommitted and SQLAlchemy rolls it back on close. That is
    # true today and is not a thing to depend on: it survives only until
    # somebody adds a commit above it.
    prospective = {
        field: _coerce(field, raw, row) for field, raw in body.changes.items()
    }

    def after(field: str) -> Any:
        return prospective.get(field, getattr(row, field))

    if after("rejected_qty") > after("produced_qty"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Rejected cannot be more than produced.",
        )
    if after("rejected_qty") > 0 and after("reject_reason_id") is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose a reject reason — a rejection with no reason cannot be acted on.",
        )

    applied = _apply_changes(
        record=row,
        changes=body.changes,
        log=lambda field, old, new: session.add(
            ProductionCorrection(
                plant_id=row.plant_id,
                production_log_id=row.id,
                field=field,
                old_value=old,
                new_value=new,
                reason=body.reason,
                corrected_by=principal.user_id,
                outside_window=outside,
            )
        ),
    )
    if not applied:
        return {"ok": True, "applied": 0, "unchanged": True}

    _mark_edited(row, principal.user_id)
    session.add(row)
    session.commit()
    return {"ok": True, "applied": applied, "outside_window": outside}


@router.get(
    "/production/{log_id}/corrections",
    response_model=list[CorrectionRead],
    summary="What has been changed on this entry",
)
def production_corrections(
    log_id: UUID, principal: PrincipalDep, session: SessionDep
) -> list[CorrectionRead]:
    row = session.get(ProductionLog, log_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(row, principal)

    rows = session.exec(
        select(ProductionCorrection)
        .where(ProductionCorrection.production_log_id == log_id)
        .order_by(ProductionCorrection.corrected_at.desc())
    ).all()
    return _to_reads(rows, session)


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


def _apply_changes(*, record: Any, changes: dict[str, Any], log: Any) -> list[str]:
    """Write the changes onto the record, logging each one. Returns what moved.

    A field sent with the value it already has is not a correction and is not
    logged — otherwise re-saving a form would fill the audit trail with rows
    saying nothing changed, and the log's usefulness is inversely proportional
    to how much of it is noise.
    """
    applied: list[str] = []
    for field, raw in changes.items():
        old = getattr(record, field)
        new = _coerce(field, raw, record)
        if old == new:
            continue
        log(field, _render(old), _render(new))
        setattr(record, field, new)
        applied.append(field)
    return applied


def _mark_edited(record: Any, user_id: int) -> None:
    record.last_edited_at = utcnow()
    record.last_edited_by = user_id


def _to_reads(rows: list[Any], session: SessionDep) -> list[CorrectionRead]:
    names = {
        u.id: u.name
        for u in session.exec(
            select(User).where(User.id.in_({r.corrected_by for r in rows} or {0}))
        ).all()
    }
    return [
        CorrectionRead(
            field=r.field,
            old_value=r.old_value,
            new_value=r.new_value,
            reason=r.reason,
            corrected_by_name=names.get(r.corrected_by, "—"),
            corrected_at=r.corrected_at,
            outside_window=r.outside_window,
        )
        for r in rows
    ]
