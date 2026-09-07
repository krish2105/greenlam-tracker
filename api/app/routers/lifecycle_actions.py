"""The Round 2 ticket actions: claim, hold, resume, handoff, reopen.

These live apart from the generic `POST /tickets/{id}/events` endpoint because
each one carries a rule that a generic "append an event" cannot express:

  * claim must settle a race between two people atomically
  * hold and resume open and close a pending window, which is what stops the
    Solve Time clock
  * handoff is legal from any active status, not at one step
  * reopen demands a typed reason and records who asked for it

Every one of them takes a client-supplied `submission_id`, so a retry over a
dropped connection is a no-op rather than a second hold or a second reopen.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from pydantic import Field as PField
from sqlalchemy import update
from sqlmodel import select

from .. import notify
from ..deps import PrincipalDep, SessionDep
from ..models import Machine, Ticket, TicketEvent, TicketPendingWindow, User
from ..models.base import utcnow
from ..models.maintenance import PENDING_KINDS
from ..tenancy import assert_visible

router = APIRouter(prefix="/tickets", tags=["tickets"])

# A ticket is "active" while somebody owns it and it is not yet closed. Handoff
# is legal across all of these, which is the point of the Round 2 decision.
ACTIVE_STATUSES = {"acknowledged", "in_progress", "on_hold_material", "correction_pending"}


class ClaimIn(BaseModel):
    submission_id: UUID | None = None
    client_ts: datetime | None = None
    # True when the action was taken in a dead zone and queued. Then the moment
    # it happened on-device is what is true, and the server must not re-stamp
    # it with the later sync time.
    offline: bool = False


class HoldIn(ClaimIn):
    kind: str = PField(pattern="^(material|correction_pending)$")
    # Required for correction_pending: that status asserts the machine is still
    # broken after an attempt, and that claim needs a sentence on it. A
    # material hold does not - the photo of the part is the record.
    reason: str | None = None


class HandoffIn(ClaimIn):
    to_user_id: int


class ReopenIn(ClaimIn):
    reason: str = PField(min_length=3)


def _load(ticket_id: UUID, principal, session) -> Ticket:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(ticket, principal)
    return ticket


def _require(principal, capability: str) -> None:
    if not principal.can(capability):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Your role does not have access to this."
        )


def _stamp(body: ClaimIn) -> tuple[datetime, str]:
    """Return the timestamp to record and which clock it came from.

    Online is the normal case and the server owns it - that is what stops
    someone backdating an acknowledgement to look quick. Offline is the
    exception the plant actually has, and there the device clock is the only
    witness to when the action happened.
    """
    now = utcnow()
    if not body.offline or body.client_ts is None:
        return now, "server"
    ts = body.client_ts
    # A device a day into the future is a broken clock, not a dead zone.
    if ts > now + timedelta(hours=24):
        return now, "server"
    return ts, "device"


def _already_done(session, submission_id: UUID | None) -> bool:
    return submission_id is not None and session.get(TicketEvent, submission_id) is not None


def _record(session, ticket: Ticket, principal, kind: str, ts, source, payload) -> None:
    session.add(
        TicketEvent(
            event_id=payload.pop("_event_id"),
            ticket_id=ticket.id,
            plant_id=ticket.plant_id,
            unit_id=ticket.unit_id,
            type=kind,
            actor_id=principal.user_id,
            payload=payload or None,
            client_ts=ts,
            ts_source=source,
        )
    )


def _name(session, user_id: int | None) -> str:
    if user_id is None:
        return "someone"
    user = session.get(User, user_id)
    return user.name if user else "someone"


@router.post("/{ticket_id}/claim", summary="Acknowledge — first tap wins")
def claim(ticket_id: UUID, body: ClaimIn, principal: PrincipalDep, session: SessionDep) -> dict:
    """Take ownership of an open ticket.

    The race is settled by the database, not by this function. Two technicians
    tapping inside the same second would both pass a read-then-write check and
    both believe they own it; the conditional UPDATE below means exactly one
    row changes and the other caller is told who got there first.
    """
    _require(principal, "work_ticket")
    ticket = _load(ticket_id, principal, session)
    if _already_done(session, body.submission_id):
        return {"ok": True, "owner": _name(session, ticket.owner_id), "repeat": True}

    ts, source = _stamp(body)
    result = session.exec(
        update(Ticket)
        .where(Ticket.id == ticket_id, Ticket.owner_id.is_(None))
        .values(
            owner_id=principal.user_id,
            acked_by=principal.user_id,
            acked_at=ts,
            status="acknowledged",
            current_stage=max(ticket.current_stage, 1),
        )
    )
    if result.rowcount == 0:
        session.rollback()
        holder = _name(session, session.get(Ticket, ticket_id).owner_id)
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"Already acknowledged by {holder}"
        )

    _record(
        session, ticket, principal, "ACKNOWLEDGED", ts, source,
        {"_event_id": body.submission_id or uuid4()},
    )
    session.commit()
    return {"ok": True, "owner": _name(session, principal.user_id), "repeat": False}


@router.post("/{ticket_id}/hold", summary="Pause the repair clock")
def hold(ticket_id: UUID, body: HoldIn, principal: PrincipalDep, session: SessionDep) -> dict:
    """Open a pending window: waiting for a part, or still broken after a try."""
    _require(principal, "work_ticket")
    ticket = _load(ticket_id, principal, session)
    if _already_done(session, body.submission_id):
        return {"ok": True, "repeat": True}

    if body.kind not in PENDING_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown hold kind")
    if body.kind == "correction_pending" and not (body.reason or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Say what is still wrong — this records that the fix did not hold.",
        )
    if ticket.status not in ACTIVE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="This ticket is not being worked on."
        )

    open_window = session.exec(
        select(TicketPendingWindow).where(
            TicketPendingWindow.ticket_id == ticket_id,
            TicketPendingWindow.ended_at.is_(None),
        )
    ).first()
    if open_window is not None:
        # The partial unique index would reject this anyway; saying so plainly
        # beats surfacing a constraint name to a technician.
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This ticket is already on hold.")

    ts, source = _stamp(body)
    session.add(
        TicketPendingWindow(
            ticket_id=ticket_id,
            plant_id=ticket.plant_id,
            unit_id=ticket.unit_id,
            kind=body.kind,
            reason=(body.reason or None),
            started_at=ts,
            started_by=principal.user_id,
        )
    )
    ticket.status = "on_hold_material" if body.kind == "material" else "correction_pending"
    session.add(ticket)
    _record(
        session, ticket, principal, "HELD", ts, source,
        {"_event_id": body.submission_id or uuid4(), "kind": body.kind, "reason": body.reason},
    )
    session.commit()
    return {"ok": True, "status": ticket.status, "repeat": False}


@router.post("/{ticket_id}/resume", summary="Restart the repair clock")
def resume(ticket_id: UUID, body: ClaimIn, principal: PrincipalDep, session: SessionDep) -> dict:
    _require(principal, "work_ticket")
    ticket = _load(ticket_id, principal, session)
    if _already_done(session, body.submission_id):
        return {"ok": True, "repeat": True}

    window = session.exec(
        select(TicketPendingWindow).where(
            TicketPendingWindow.ticket_id == ticket_id,
            TicketPendingWindow.ended_at.is_(None),
        )
    ).first()
    if window is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This ticket is not on hold.")

    ts, source = _stamp(body)
    # Guard the check constraint with a clear message rather than a 500 from
    # the database: a queued device clock can land before the server-stamped
    # start of the window.
    if ts < window.started_at:
        ts, source = window.started_at, "server"
    window.ended_at = ts
    window.ended_by = principal.user_id
    session.add(window)

    ticket.status = "in_progress"
    session.add(ticket)
    _record(
        session, ticket, principal, "RESUMED", ts, source,
        {"_event_id": body.submission_id or uuid4(), "kind": window.kind},
    )
    session.commit()
    return {"ok": True, "status": ticket.status, "repeat": False}


@router.post("/{ticket_id}/handoff", summary="Reassign to someone else")
def handoff(
    ticket_id: UUID, body: HandoffIn, principal: PrincipalDep, session: SessionDep
) -> dict:
    """Move a ticket to another person, from any active status.

    No reason is asked for. Handoff happens at shift changeover twenty times a
    week, and a mandatory box would be filled with "shift" until it told you
    nothing.
    """
    _require(principal, "work_ticket")
    ticket = _load(ticket_id, principal, session)
    if _already_done(session, body.submission_id):
        return {"ok": True, "repeat": True}

    if ticket.status not in ACTIVE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Only a ticket somebody is working on can be handed off.",
        )
    target = session.get(User, body.to_user_id)
    if target is None or target.plant_id != ticket.plant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such person in this plant.")

    ts, source = _stamp(body)
    previous = ticket.owner_id
    ticket.owner_id = body.to_user_id
    # Only recorded when somebody moved a ticket that was not theirs — that is
    # the case worth being able to see later.
    ticket.handed_off_by = principal.user_id if previous != principal.user_id else None
    session.add(ticket)
    _record(
        session, ticket, principal, "HANDED_OFF", ts, source,
        {"_event_id": body.submission_id or uuid4(), "from": previous, "to": body.to_user_id},
    )
    session.commit()
    return {"ok": True, "owner": _name(session, body.to_user_id), "repeat": False}


@router.post("/{ticket_id}/reopen", summary="The fix did not hold")
def reopen(ticket_id: UUID, body: ReopenIn, principal: PrincipalDep, session: SessionDep) -> dict:
    """Reopen a closed or resolved ticket, with a required reason.

    Open to anyone who manages tickets. There is no approval step gating
    closure, so the only real safety net is somebody noticing the machine is
    still broken — and that net is worth keeping wide.
    """
    if not principal.can("reopen_ticket"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Your role does not have access to this."
        )
    ticket = _load(ticket_id, principal, session)
    if _already_done(session, body.submission_id):
        return {"ok": True, "repeat": True}

    if ticket.status not in {"resolved", "closed"}:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="This ticket is still open."
        )

    ts, source = _stamp(body)
    ticket.status = "correction_pending"
    ticket.reopen_count += 1
    ticket.reopened_by = principal.user_id
    ticket.reopen_reason = body.reason.strip()
    # Back into someone's hands. Whoever reopened it is not necessarily the
    # person who will fix it, so ownership is cleared for the next claim.
    ticket.owner_id = None
    session.add(ticket)
    _record(
        session, ticket, principal, "REOPENED", ts, source,
        {"_event_id": body.submission_id or uuid4(), "reason": ticket.reopen_reason},
    )
    session.commit()

    machine = session.get(Machine, ticket.machine_id)
    notify.ticket_reopened(
        session,
        machine_code=machine.code if machine else "—",
        reason=ticket.reopen_reason or "",
        by=principal.user_id,
    )
    session.commit()

    return {
        "ok": True,
        "reopened_by": _name(session, principal.user_id),
        "reopen_count": ticket.reopen_count,
        "repeat": False,
    }
