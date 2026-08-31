"""FastAPI dependencies: session, principal, capability gates.

The access token carries identity and role only. Scope is loaded from
`user_scopes` on every request, so revoking someone's access to a plant takes
effect immediately rather than whenever their token expires.

The refresh token never appears here — it lives in an httpOnly cookie that
JavaScript cannot read, so an XSS bug can steal at most a 30-minute access
token rather than a 30-day session.
"""

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session

from .db import get_session
from .models import User
from .security import decode_token
from .tenancy import Principal

SessionDep = Annotated[Session, Depends(get_session)]

_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED,
    detail="Sign in to continue.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_principal(request: Request, session: SessionDep) -> Principal:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _UNAUTHORIZED
    try:
        payload = decode_token(token, expected_type="access")
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise _UNAUTHORIZED from exc

    # Hit the database rather than trusting the claims: deactivating someone,
    # changing their role, or revoking a plant has to bite before their token
    # expires.
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED

    # Scope is the user's own plant. The separate grants table is gone — see
    # tenancy.py for why the section axis was deleted rather than left always
    # passing.
    return Principal(
        user_id=user.id,
        role=user.role,
        home_plant_id=user.plant_id,
        home_unit_id=user.unit_id,
        plant_ids=[user.plant_id],
    )


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def get_current_user(principal: PrincipalDep, session: SessionDep) -> User:
    user = session.get(User, principal.user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require(capability: str) -> Callable[[Principal], Principal]:
    """Gate an endpoint on a capability rather than a rank.

    Rank cannot express this hierarchy: a shareholder outranks everyone on the
    org chart and may do less in this system than an operator. Naming the
    capability also makes the intent readable at the call site —
    `require("verify_close")` says what the endpoint is for.
    """

    def _check(principal: PrincipalDep) -> Principal:
        if not principal.can(capability):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="Your role does not have access to this.",
            )
        return principal

    return _check


CanRaise = Annotated[Principal, Depends(require("raise_ticket"))]
CanWork = Annotated[Principal, Depends(require("work_ticket"))]
CanVerify = Annotated[Principal, Depends(require("verify_close"))]
CanLogProduction = Annotated[Principal, Depends(require("log_production"))]
CanEditMasters = Annotated[Principal, Depends(require("edit_masters"))]
CanManageUsers = Annotated[Principal, Depends(require("manage_users"))]
CanUnlock = Annotated[Principal, Depends(require("unlock_users"))]
CanViewDashboard = Annotated[Principal, Depends(require("view_dashboard"))]

# `Operational` used to gate anything returning an individual ticket, because
# corporate tiers saw only rollups. With two levels there is no reader who may
# see a chart but not the ticket behind it, so the alias now means "signed in"
# and exists only so call sites did not all have to change in one commit.
Operational = PrincipalDep
