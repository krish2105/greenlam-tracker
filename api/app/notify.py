"""Sending a push, and deciding who gets it (V5 §9).

WHAT THIS IS CAREFUL ABOUT

A notification that fails must never take a ticket down with it. Somebody
reporting a stopped press is doing the single most important thing this system
supports, and a push service having a bad afternoon is not a reason to refuse
their report. So every send is wrapped, every failure is swallowed, and the
worst case is a quiet phone rather than a lost breakdown.

The other half of that: a dead subscription is retired rather than retried. A
push service answers 404 or 410 for an endpoint that no longer exists — a wiped
phone, an uninstalled app, a rotated subscription — and hammering it forever
would eventually get the sender rate-limited for everybody.

WHO GETS WHAT (V5 §9)

  raised     -> everyone holding Maintenance
  flagged    -> Supervisors and Managers, for awareness. No action is asked of
                them, so the wording says what happened and not what to do.
  reopened   -> Maintenance, Supervisors and Managers, worded so it plainly
                reads as reopened rather than newly raised. Somebody who skims
                it as a new breakdown will walk to the machine expecting a
                different problem.

Nobody is ever notified about their own action. Being told you did the thing
you just did is how people learn to ignore an app's notifications entirely.
"""

from __future__ import annotations

import json
import logging

from sqlmodel import Session, select

from .config import get_settings
from .models import PushSubscription, UserAccessArea, utcnow

log = logging.getLogger(__name__)


def configured() -> bool:
    """Whether push is switched on at all.

    Absent keys are a working configuration, not an error: a plant that has not
    generated a pair yet should still be able to raise and work tickets.
    """
    s = get_settings()
    return bool(s.vapid_public_key and s.vapid_private_key)


def recipients(session: Session, areas: tuple[str, ...], *, exclude: int | None) -> list[int]:
    """User ids holding any of these areas, minus whoever caused the event."""
    rows = session.exec(
        select(UserAccessArea.user_id).where(UserAccessArea.area.in_(areas))
    ).all()
    return sorted({uid for uid in rows if uid != exclude})


def send_to(
    session: Session,
    user_ids: list[int],
    *,
    title: str,
    body: str,
    url: str = "/floor/maintenance",
    tag: str | None = None,
) -> int:
    """Push to every live device of these people. Returns how many were sent.

    Never raises. The caller is always in the middle of something that matters
    more than the notification.
    """
    if not user_ids or not configured():
        return 0

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:  # pragma: no cover - the dependency is declared
        log.warning("pywebpush is not installed; notifications are off")
        return 0

    settings = get_settings()
    subs = session.exec(
        select(PushSubscription).where(
            PushSubscription.user_id.in_(user_ids),
            PushSubscription.failed_at.is_(None),
        )
    ).all()

    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    sent = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},
                timeout=5,
            )
            sub.last_sent_at = utcnow()
            session.add(sub)
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                # The endpoint is gone for good. Retiring it stops the sender
                # being rate-limited on behalf of a phone that no longer exists.
                sub.failed_at = utcnow()
                session.add(sub)
            else:
                log.warning("push failed (%s) for subscription %s", status, sub.id)
        except Exception:  # noqa: BLE001 - a quiet phone beats a lost ticket
            log.exception("push failed unexpectedly for subscription %s", sub.id)

    return sent


# ---------------------------------------------------------------------------
# The three events V5 §9 names
# ---------------------------------------------------------------------------


def ticket_raised(session: Session, *, machine_code: str, description: str, by: int) -> None:
    send_to(
        session,
        recipients(session, ("maintenance",), exclude=by),
        title=f"{machine_code} is down",
        # Truncated rather than wrapped: a push notification is read on a lock
        # screen, and the machine code is the part that decides who walks.
        body=description[:120],
        tag=f"raised:{machine_code}",
    )


def ticket_flagged(session: Session, *, machine_code: str, reason: str, by: int | None) -> None:
    """Awareness only. V5 §9 asks for no action, so the wording asks for none."""
    send_to(
        session,
        recipients(session, ("supervisor", "manager"), exclude=by),
        title=f"{machine_code} — worth a look",
        body=reason,
        tag=f"flag:{machine_code}",
    )


def ticket_reopened(
    session: Session, *, machine_code: str, reason: str, by: int
) -> None:
    send_to(
        session,
        recipients(session, ("maintenance", "supervisor", "manager"), exclude=by),
        # "Reopened" first, before anything else in the string. Somebody
        # skimming a lock screen and reading this as a new breakdown will walk
        # to the machine expecting a different problem.
        title=f"Reopened: {machine_code}",
        body=f"The last fix did not hold. {reason}"[:140],
        tag=f"reopen:{machine_code}",
    )
