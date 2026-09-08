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
from ..models import (
    Attachment,
    Machine,
    Ticket,
    TicketEvent,
    TicketPendingWindow,
    User,
    UserAccessArea,
)
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


def _areas_of(session, user_id: int) -> set[str]:
    return set(
        session.exec(
            select(UserAccessArea.area).where(UserAccessArea.user_id == user_id)
        ).all()
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

    # V5 §5.4: "when the part arrives, the engineer must click Resume and upload
    # a photo of the arrived part before the ticket can continue. Simply waiting
    # isn't enough to move the ticket forward."
    #
    # Enforced only for a MATERIAL hold. A correction-pending window ends when
    # somebody goes back to the machine, and there is nothing to photograph —
    # requiring one there would teach people to photograph the floor.
    #
    # This is the one claim in the lifecycle with a number attached that nobody
    # else witnesses: ending the window restarts the repair clock, and the
    # difference lands in Solve Time and then in the criticality band.
    if window.kind == "material":
        has_photo = session.exec(
            select(Attachment).where(
                Attachment.ticket_id == ticket_id,
                Attachment.kind == "part_arrived",
                Attachment.uploaded_at >= window.started_at,
            )
        ).first()
        if has_photo is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Take a photo of the part that arrived before starting again.",
            )

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
    """Move a ticket to another person.

    TWO DIFFERENT ACTIONS THROUGH ONE DOOR

    An engineer passing their own ticket on at shift changeover, and a manager
    assigning somebody else's work. V5 §15.5 allows both, so both capabilities
    open this: `work_ticket` for the first, `reassign_ticket` for the second.
    Gating it on `work_ticket` alone — which is what this did — meant a Manager
    could not do the one thing V5 §3 names as their job.

    No reason is asked for. Handoff happens at shift changeover twenty times a
    week, and a mandatory box would be filled with "shift" until it told you
    nothing.
    """
    if not (principal.can("work_ticket") or principal.can("reassign_ticket")):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Your role does not have access to this."
        )
    ticket = _load(ticket_id, principal, session)
    if _already_done(session, body.submission_id):
        return {"ok": True, "repeat": True}

    # A raised-but-unclaimed ticket can be assigned by somebody with
    # `reassign_ticket`. "Ramesh, you take Press-4" is precisely the manager
    # action V5 §3 describes, and requiring a claim first made it impossible —
    # the manager would have had to acknowledge the ticket themselves and then
    # hand it over, which puts their name on a repair they are not doing.
    #
    # Somebody who only works tickets still cannot: passing on a ticket nobody
    # holds is assigning work, not handing over your own.
    assignable = ACTIVE_STATUSES | ({"raised"} if principal.can("reassign_ticket") else set())
    if ticket.status not in assignable:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This ticket is finished — reopen it before handing it to anybody.",
        )
    target = session.get(User, body.to_user_id)
    if target is None or target.plant_id != ticket.plant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such person in this plant.")

    # Handing a breakdown to somebody who cannot open it is a silent dead end:
    # the ticket leaves the assigner's list and never appears on anyone else's.
    if "maintenance" not in _areas_of(session, target.id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{target.name} does not have Maintenance access, so cannot work this.",
        )

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


class Assignee(BaseModel):
    user_id: int
    name: str
    employee_id: str
    # How many tickets they already hold. A manager choosing between two
    # technicians is usually asking exactly this, and without it the choice is
    # made on who they remember rather than who is free.
    open_tickets: int


@router.get(
    "/assignable-to",
    response_model=list[Assignee],
    summary="Who a ticket can be handed to",
)
def assignable_to(principal: PrincipalDep, session: SessionDep) -> list[Assignee]:
    """Everyone holding Maintenance, with their current load.

    Its own endpoint rather than reusing the admin user list, which requires
    `edit_masters` — a Manager has no business enumerating every account in the
    plant, and needs exactly this one list to do their job.
    """
    if not (principal.can("work_ticket") or principal.can("reassign_ticket")):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Your role does not have access to this."
        )

    ids = session.exec(
        select(UserAccessArea.user_id).where(UserAccessArea.area == "maintenance")
    ).all()
    if not ids:
        return []

    people = session.exec(
        select(User).where(
            User.id.in_(ids),
            User.plant_id == principal.home_plant_id,
            User.is_active.is_(True),
        )
    ).all()

    # Everything they own that is not finished — which includes a ticket a
    # manager just assigned but they have not acknowledged yet, and one sitting
    # half-closed waiting on its RCA. Both are work this person still holds,
    # and "who is free" is the question this list exists to answer.
    #
    # Counting only ACTIVE_STATUSES missed exactly the tickets a manager had
    # just handed out, so the next assignment went to the same person again.
    load: dict[int, int] = {}
    for owner_id in session.exec(
        select(Ticket.owner_id).where(
            Ticket.plant_id == principal.home_plant_id,
            Ticket.owner_id.is_not(None),
            Ticket.status != "closed",
        )
    ).all():
        load[owner_id] = load.get(owner_id, 0) + 1

    return sorted(
        (
            Assignee(
                user_id=p.id,
                name=p.name,
                employee_id=p.employee_id,
                open_tickets=load.get(p.id, 0),
            )
            for p in people
        ),
        # Least loaded first. The list is a suggestion about who is free, not
        # an alphabetical directory.
        key=lambda a: (a.open_tickets, a.name),
    )
