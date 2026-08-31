"""PIN login, refresh-token rotation, logout, supervisor unlock.

Cookie strategy — the deployment depends on it. The PWA and the API are served
from one origin (Render static rewrites `/api/*` to the API service), so the
refresh cookie is first-party. That matters because Safari's ITP has made
cross-site cookies effectively unusable on iPhone, and half the floor is on
iPhone. The cookie is scoped to `/api/auth` so it is not attached to every
request, only to refresh and logout.
"""

from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlmodel import select

from ..config import get_settings
from ..deps import CanUnlock, CurrentUser, SessionDep
from ..models import Device, RefreshToken, User, utcnow
from ..schemas import LoginRequest, PreferencesUpdate, TokenResponse, UserRead
from ..security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_pin,
    needs_rehash,
    new_jti,
    next_lock_state,
    verify_pin,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

REFRESH_COOKIE = "gmt_refresh"
COOKIE_PATH = "/api/auth"

# Deliberately identical for "no such employee ID" and "wrong PIN". Telling
# them apart would let someone enumerate valid employee IDs, which are short,
# sequential and printed on ID cards.
_BAD_CREDENTIALS = HTTPException(
    status.HTTP_401_UNAUTHORIZED, detail="Employee ID or PIN is incorrect."
)


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True,  # unreadable from JavaScript — XSS cannot lift the session
        secure=settings.cookie_secure,
        samesite="lax",  # blocks cross-site POST, which covers CSRF here
        path=COOKIE_PATH,
        domain=settings.cookie_domain,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE, path=COOKIE_PATH, domain=settings.cookie_domain)


def _revoke_family(session: SessionDep, family_id: str, now: datetime) -> None:
    rows = session.exec(
        select(RefreshToken).where(
            RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None)
        )
    ).all()
    for row in rows:
        row.revoked_at = now
        session.add(row)


def _issue_session(
    session: SessionDep,
    response: Response,
    user: User,
    *,
    family_id: str | None = None,
    device_uid: str | None = None,
) -> tuple[TokenResponse, str]:
    """Returns the response body and the jti of the refresh token just issued."""
    access, access_expires = create_access_token(
        user_id=user.id, role=user.role, plant_id=user.plant_id, unit_id=user.unit_id
    )
    jti = new_jti()
    family = family_id or new_jti()
    refresh, refresh_expires = create_refresh_token(user_id=user.id, jti=jti, family_id=family)
    session.add(
        RefreshToken(
            plant_id=user.plant_id,
            unit_id=user.unit_id,
            user_id=user.id,
            jti=jti,
            family_id=family,
            device_uid=device_uid,
            expires_at=refresh_expires,
        )
    )
    _set_refresh_cookie(response, refresh)
    body = TokenResponse(
        access_token=access,
        expires_at=access_expires,
        user=UserRead.model_validate(user),
    )
    return body, jti


@router.post("/login", response_model=TokenResponse, summary="Sign in with employee ID and PIN")
def login(body: LoginRequest, response: Response, session: SessionDep) -> TokenResponse:
    """Exchange an employee ID and 6-digit PIN for an access token.

    The refresh token is returned as an httpOnly cookie, not in the body.

    Failed attempts back off progressively (1s, 2s, 4s...) and hard-lock at ten,
    which a supervisor clears via `POST /auth/users/{id}/unlock`.
    """
    now = utcnow()

    stmt = select(User).where(User.employee_id == body.employee_id, User.is_active.is_(True))
    if body.plant_id is not None:
        stmt = stmt.where(User.plant_id == body.plant_id)
    matches = session.exec(stmt).all()

    if len(matches) > 1:
        # Employee IDs are unique per plant, not globally. Only reachable once
        # this is multi-plant; the pilot is one plant.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="That employee ID exists at more than one plant. Include plant_id.",
        )

    user = matches[0] if matches else None

    if user is not None and user.hard_locked:
        raise HTTPException(
            status.HTTP_423_LOCKED,
            detail="This account is locked. Ask your supervisor to unlock it.",
        )

    if user is not None and user.locked_until is not None and now < user.locked_until:
        wait = max(1, int((user.locked_until - now).total_seconds()))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many attempts. Try again in {wait} seconds.",
            headers={"Retry-After": str(wait)},
        )

    # Always runs, even when the user does not exist, so response time does not
    # reveal which employee IDs are real.
    ok = verify_pin(body.employee_id, body.pin, user.pin_hash if user else None)

    if not ok or user is None:
        if user is not None:
            user.failed_pin_attempts += 1
            user.last_failed_at = now
            user.locked_until, user.hard_locked = next_lock_state(user.failed_pin_attempts, now)
            session.add(user)
            session.commit()
        raise _BAD_CREDENTIALS

    # Success — clear the lockout state.
    user.failed_pin_attempts = 0
    user.locked_until = None
    user.last_failed_at = None
    user.last_login_at = now
    if needs_rehash(user.pin_hash):
        user.pin_hash = hash_pin(body.employee_id, body.pin)
    session.add(user)

    if body.device_uid:
        existing = session.exec(
            select(Device).where(Device.user_id == user.id, Device.device_uid == body.device_uid)
        ).first()
        if existing is None:
            session.add(
                Device(
                    plant_id=user.plant_id,
                    unit_id=user.unit_id,
                    user_id=user.id,
                    device_uid=body.device_uid,
                    platform=body.platform,
                )
            )

    result, _ = _issue_session(session, response, user, device_uid=body.device_uid)
    session.commit()
    return result


@router.post("/refresh", response_model=TokenResponse, summary="Rotate the session")
def refresh(request: Request, response: Response, session: SessionDep) -> TokenResponse:
    """Exchange the refresh cookie for a new access token and a rotated cookie.

    Reuse detection: presenting an already-revoked token revokes its entire
    family. That is the signature of a stolen token being replayed, and the
    right response is to end every session in that family rather than let the
    thief ride along beside the real user.
    """
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")

    try:
        payload = decode_token(token, expected_type="refresh")
    except jwt.PyJWTError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.") from exc

    now = utcnow()
    stored = session.exec(select(RefreshToken).where(RefreshToken.jti == payload["jti"])).first()

    if stored is None:
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")

    if stored.revoked_at is not None:
        _revoke_family(session, stored.family_id, now)
        session.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="This session was ended for security. Sign in again.",
        )

    if stored.expires_at.replace(tzinfo=UTC) < now:
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")

    user = session.get(User, stored.user_id)
    if user is None or not user.is_active or user.hard_locked:
        _revoke_family(session, stored.family_id, now)
        session.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")

    new, new_jti_value = _issue_session(
        session, response, user, family_id=stored.family_id, device_uid=stored.device_uid
    )
    stored.revoked_at = now
    stored.replaced_by_jti = new_jti_value
    session.add(stored)
    session.commit()
    return new


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
def logout(request: Request, response: Response, session: SessionDep) -> Response:
    """Revoke the whole token family and clear the cookie.

    Always returns 204, including when there is no valid cookie — signing out
    should never fail.
    """
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        try:
            payload = decode_token(token, expected_type="refresh")
            _revoke_family(session, payload["fam"], utcnow())
            session.commit()
        except (jwt.PyJWTError, KeyError):
            pass
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserRead, summary="The signed-in user")
def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("/me/preferences", response_model=UserRead, summary="Save language and theme")
def update_preferences(body: PreferencesUpdate, user: CurrentUser, session: SessionDep) -> UserRead:
    """Preferences follow the person to whichever shared tablet they sign in on."""
    if body.preferred_language is not None:
        user.preferred_language = body.preferred_language
    if body.preferred_theme is not None:
        user.preferred_theme = body.preferred_theme
    session.add(user)
    session.commit()
    session.refresh(user)
    return UserRead.model_validate(user)


@router.post(
    "/users/{user_id}/unlock",
    response_model=UserRead,
    summary="Clear a PIN lockout (supervisor and above)",
)
def unlock_user(
    user_id: int,
    session: SessionDep,
    principal: CanUnlock,
) -> UserRead:
    """Unlock an account that hit the hard lock.

    In-app rather than a database chore on purpose: on a factory floor the
    supervisor is standing right there, and a lockout that needs a developer to
    clear will get worked around within a week.
    """
    target = session.get(User, user_id)
    if target is None or not principal.covers_plant(target.plant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")

    target.hard_locked = False
    target.locked_until = None
    target.failed_pin_attempts = 0
    session.add(target)
    session.commit()
    session.refresh(target)
    return UserRead.model_validate(target)
