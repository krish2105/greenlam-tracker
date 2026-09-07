"""Subscribing a device to notifications.

Three endpoints and no cleverness. The browser produces a subscription object,
posts it here, and gets pushed to until it stops working.

WHY THE PUBLIC KEY IS AN ENDPOINT

The browser needs it before it can subscribe, and baking it into the frontend
bundle would mean a rebuild every time the plant rotated keys — or worse, two
deployments briefly disagreeing about which key is current, which produces
subscriptions that can never be pushed to.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from sqlmodel import select

from .. import notify
from ..config import get_settings
from ..deps import PrincipalDep, SessionDep
from ..models import PushSubscription, utcnow

router = APIRouter(prefix="/push", tags=["push"])


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class SubscribeRequest(BaseModel):
    endpoint: str = Field(max_length=800)
    keys: SubscriptionKeys


class PushStatus(BaseModel):
    # Empty when the plant has not generated keys. The frontend then does not
    # offer to subscribe, rather than offering and failing.
    public_key: str
    enabled: bool
    devices: int


@router.get("/status", response_model=PushStatus, summary="Is push available, and am I on it")
def push_status(principal: PrincipalDep, session: SessionDep) -> PushStatus:
    count = len(
        session.exec(
            select(PushSubscription).where(
                PushSubscription.user_id == principal.user_id,
                PushSubscription.failed_at.is_(None),
            )
        ).all()
    )
    return PushStatus(
        public_key=get_settings().vapid_public_key,
        enabled=notify.configured(),
        devices=count,
    )


@router.post(
    "/subscribe",
    status_code=status.HTTP_201_CREATED,
    summary="Register this device for notifications",
)
def subscribe(
    body: SubscribeRequest, principal: PrincipalDep, session: SessionDep, request: Request
) -> dict:
    """Idempotent by endpoint.

    A browser hands back the same endpoint for the same device and origin until
    it rotates one, so re-subscribing has to update rather than insert — and it
    has to reassign, because a shared tablet's subscription belongs to whoever
    is signed in now.
    """
    existing = session.exec(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    ).first()

    if existing is not None:
        existing.user_id = principal.user_id
        existing.p256dh = body.keys.p256dh
        existing.auth = body.keys.auth
        # A rotated subscription on a previously dead endpoint is alive again.
        existing.failed_at = None
        session.add(existing)
        session.commit()
        return {"ok": True, "created": False}

    session.add(
        PushSubscription(
            plant_id=principal.home_plant_id,
            user_id=principal.user_id,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
            created_at=utcnow(),
        )
    )
    session.commit()
    return {"ok": True, "created": True}


@router.delete(
    "/subscribe",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop notifications on this device",
)
def unsubscribe(
    body: SubscribeRequest, principal: PrincipalDep, session: SessionDep
) -> Response:
    row = session.exec(
        select(PushSubscription).where(
            PushSubscription.endpoint == body.endpoint,
            PushSubscription.user_id == principal.user_id,
        )
    ).first()
    if row is not None:
        session.delete(row)
        session.commit()
    # 204 either way. "Stop notifying this device" has succeeded when the
    # device is not being notified, including when it never was.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
