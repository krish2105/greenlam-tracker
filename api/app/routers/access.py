"""Signing up, and being let in (V5 §3).

THE SHAPE OF THIS

Anyone can create an account. It arrives holding nothing — it can sign in, and
every screen behind that tells it to wait. An admin sees the queue, switches on
whichever of the six areas apply, and the person's home screen fills in.

Self-signup rather than admin-creates-everyone because the plant has hundreds
of people on their own phones and no IT desk between them and the app. Making
one person type three hundred employee IDs is how a rollout stalls in week one.
Approval rather than open registration because an account that could log
production the moment it existed would let anybody who guessed the URL write
into the plant's production record.

WHAT A PENDING ACCOUNT CAN DO

Sign in, and nothing else. That is deliberate: a login that failed outright
would be indistinguishable from a wrong PIN, and the person would try again,
and again, until the lockout in `security.py` caught them. Signing in and being
told plainly that approval is pending is the only version of this that does not
generate support calls.

REVOKED IS NOT PENDING

Both hold zero areas. `approved_at` is what separates them, and it is why that
column exists rather than being derived — otherwise every account an admin
deliberately emptied would reappear at the top of the queue the next morning.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel import select

from ..deps import CanApproveUsers, SessionDep
from ..models import AREAS, User, UserAccessArea, utcnow
from ..schemas import UserRead
from ..security import hash_pin, validate_pin_format
from ..tenancy import scope
from ..user_read import areas_of, user_read

router = APIRouter(tags=["access"])


class SignupRequest(BaseModel):
    employee_id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    pin: str = Field(min_length=6, max_length=6)
    phone: str | None = Field(default=None, max_length=20)


class PendingUser(BaseModel):
    id: int
    employee_id: str
    name: str
    phone: str | None
    signed_up_at: datetime


class AreasWrite(BaseModel):
    """The areas this person should hold after this call. Absolute, not a delta.

    Sending the full set rather than add/remove instructions means the admin
    screen cannot drift out of step with the server: whatever the checkboxes
    say is what ends up in the table, including an empty list, which is how
    access is revoked.
    """

    areas: list[str]

    @field_validator("areas")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(AREAS))
        if unknown:
            raise ValueError(f"Unknown access area(s): {', '.join(unknown)}")
        return sorted(set(v))


# ---------------------------------------------------------------------------
# Signing up
# ---------------------------------------------------------------------------


@router.post(
    "/auth/signup",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account, pending approval",
)
def signup(body: SignupRequest, session: SessionDep) -> UserRead:
    """Unauthenticated on purpose — this is how a new person gets in at all.

    It grants nothing. The account exists, holds no areas, and waits.
    """
    if not validate_pin_format(body.pin):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="PIN must be 6 digits, and not a repeat or a run like 123456.",
        )

    # Employee IDs are unique per plant, and an unauthenticated caller has no
    # plant. The pilot is one plant, so the first one is the only one; when a
    # second lands, signup needs to ask which — and that is a real question
    # about how somebody joins, not something to guess at here.
    plant_id = session.exec(select(User.plant_id).order_by(User.id)).first()
    if plant_id is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="This plant has not been set up yet.",
        )

    clash = session.exec(
        select(User).where(User.plant_id == plant_id, User.employee_id == body.employee_id)
    ).first()
    if clash is not None:
        # Deliberately the same message whether the ID is taken by somebody
        # else or is the caller's own second attempt. Confirming which would
        # turn this endpoint into a way to enumerate who works here.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="That employee ID is already registered. Sign in, or ask an admin.",
        )

    user = User(
        plant_id=plant_id,
        employee_id=body.employee_id,
        name=body.name.strip(),
        phone=body.phone,
        pin_hash=hash_pin(body.employee_id, body.pin),
        # The two facts that make this a pending account rather than a live one.
        approved_at=None,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user_read(session, user)


# ---------------------------------------------------------------------------
# Letting people in
# ---------------------------------------------------------------------------


@router.get(
    "/access/pending",
    response_model=list[PendingUser],
    summary="Accounts waiting for approval",
)
def pending(principal: CanApproveUsers, session: SessionDep) -> list[PendingUser]:
    """Never approved, still waiting. Oldest first — a queue, not a list.

    An account whose areas were revoked does NOT appear here: it has an
    `approved_at`, so it has already been looked at once.
    """
    rows = session.exec(
        scope(User, principal)
        .where(User.approved_at.is_(None), User.is_active.is_(True))
        .order_by(User.created_at)
    ).all()
    return [
        PendingUser(
            id=u.id,
            employee_id=u.employee_id,
            name=u.name,
            phone=u.phone,
            signed_up_at=u.created_at,
        )
        for u in rows
    ]


@router.post(
    "/access/users/{user_id}/approve",
    response_model=UserRead,
    summary="Approve an account and grant its areas",
)
def approve(
    user_id: int, body: AreasWrite, principal: CanApproveUsers, session: SessionDep
) -> UserRead:
    user = _load(user_id, principal, session)
    if user.approved_at is not None:
        # Already dealt with. Use the areas endpoint to change what they hold —
        # approving twice would overwrite the approval record with a later date
        # and lose who actually let them in.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"{user.name} has already been approved. Change their access instead.",
        )
    user.approved_at = utcnow()
    user.approved_by = principal.user_id
    session.add(user)
    _set_areas(session, user, body.areas, principal.user_id)
    session.commit()
    return user_read(session, user)


@router.put(
    "/access/users/{user_id}/areas",
    response_model=UserRead,
    summary="Change what someone can reach",
)
def set_areas(
    user_id: int, body: AreasWrite, principal: CanApproveUsers, session: SessionDep
) -> UserRead:
    """Add, remove, or revoke entirely by sending an empty list (V5 §3)."""
    user = _load(user_id, principal, session)

    # An admin removing their own admin area, with nobody else holding it,
    # locks the plant out of its own user management — and the only way back is
    # somebody with database access. Refused rather than warned about.
    if principal.user_id == user_id and "admin" not in body.areas:
        others = session.exec(
            select(UserAccessArea)
            .where(UserAccessArea.area == "admin", UserAccessArea.user_id != user_id)
        ).first()
        if others is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="You are the only admin. Give somebody else admin access first.",
            )

    _set_areas(session, user, body.areas, principal.user_id)
    session.commit()
    return user_read(session, user)


def _load(user_id: int, principal, session: SessionDep) -> User:
    user = session.get(User, user_id)
    if user is None or not principal.covers_plant(user.plant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return user


def _set_areas(session: SessionDep, user: User, areas: list[str], by: int) -> None:
    """Make the table say exactly `areas`, and nothing else.

    Only the difference is written. Deleting all six and re-inserting would be
    one line shorter and would reset `granted_at` on every area the person
    already had, losing when they were actually given it.
    """
    current = set(areas_of(session, user.id))
    wanted = set(areas)

    for area in current - wanted:
        row = session.exec(
            select(UserAccessArea).where(
                UserAccessArea.user_id == user.id, UserAccessArea.area == area
            )
        ).first()
        if row is not None:
            session.delete(row)

    for area in wanted - current:
        session.add(UserAccessArea(user_id=user.id, area=area, granted_by=by))
