"""The two closure-integrity checks that cannot be answered at write time.

V5 §5.7 asks for two flags, and they are different shapes:

  Repeat failure       — a new ticket on the same machine soon after the last
                         one was fixed. Knowable the instant the ticket is
                         raised, so it is decided there and stored as a link.

  No follow-up         — a machine that has run nothing since it was repaired.
  production             Cannot be known at any single moment: it becomes true
                         by nothing happening, which is exactly what a
                         scheduled pass is for.

WHERE THIS RUNS

Not on Render. The free tier has no cron and sleeps after fifteen minutes idle,
so a long-lived worker there is a moving part that stops without telling
anybody — and a stalled integrity check leaves the board looking calm. It runs
on the GitHub Actions schedule the nightly export already uses.

WHY THE SECOND CHECK IS ADVISORY

Production depends on the planning schedule, not only on machine health. If the
next load simply does not call for that machine, there will be no entries
however genuine the repair was. V5 §5.7 is explicit that this is a soft,
informational flag — and it is why the window is admin-configurable and, for
now, deliberately unset.
"""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import Session, select

from . import notify
from .models import Machine, PlantSetting, ProductionLog, Ticket, utcnow

# Confirmed default (V5 §16). Read from plant_settings so a plant can change it
# without a deploy; this is the value migration 0015 seeds.
DEFAULT_REPEAT_WINDOW_MINUTES = 48 * 60


def _window(session: Session, plant_id: int, key: str) -> int | None:
    return session.exec(
        select(PlantSetting.minutes).where(
            PlantSetting.plant_id == plant_id, PlantSetting.key == key
        )
    ).first()


def find_repeat(session: Session, ticket: Ticket) -> object | None:
    """The most recent ticket on this machine fixed inside the repeat window.

    Keyed off `resolved_at` — the moment the machine actually went back into
    service — and not `closed_at`, which can trail by days while an engineer
    catches up on RCAs (V5 §5.7).
    """
    minutes = _window(session, ticket.plant_id, "repeat_failure.window")
    if minutes is None:
        minutes = DEFAULT_REPEAT_WINDOW_MINUTES

    since = ticket.raised_at - timedelta(minutes=minutes)
    previous = session.exec(
        select(Ticket)
        .where(
            Ticket.machine_id == ticket.machine_id,
            Ticket.id != ticket.id,
            Ticket.resolved_at.is_not(None),
            Ticket.resolved_at >= since,
            Ticket.resolved_at <= ticket.raised_at,
        )
        .order_by(Ticket.resolved_at.desc())
        .limit(1)
    ).first()
    return previous.id if previous else None


def check_no_follow_up(session: Session, plant_id: int) -> dict:
    """Flag repairs that no production has followed.

    Returns a summary rather than printing, so the caller decides what to say.

    Skipped entirely while the window is unset. V5 §16 defers that number until
    the trial has produced a baseline, and a threshold invented here would
    start flagging real repairs against something nobody agreed to.
    """
    minutes = _window(session, plant_id, "no_follow_up.window")
    if minutes is None:
        return {"checked": 0, "flagged": 0, "skipped": "no window configured"}

    now = utcnow()
    cutoff = now - timedelta(minutes=minutes)

    # Repaired long enough ago for the window to have elapsed, and not already
    # flagged. The `flagged_at` column is what stops a half-hourly worker
    # sending the same alert forty-eight times a day.
    candidates = session.exec(
        select(Ticket).where(
            Ticket.plant_id == plant_id,
            Ticket.resolved_at.is_not(None),
            Ticket.resolved_at <= cutoff,
            Ticket.no_follow_up_flagged_at.is_(None),
        )
    ).all()

    flagged = 0
    for ticket in candidates:
        ran = session.exec(
            select(ProductionLog)
            .where(
                ProductionLog.machine_id == ticket.machine_id,
                ProductionLog.log_date >= ticket.resolved_at.date(),
            )
            .limit(1)
        ).first()
        if ran is not None:
            # It ran. Mark it so this ticket is never reconsidered — the answer
            # cannot change, and leaving it unmarked means re-running this
            # query against it every half hour forever.
            ticket.no_follow_up_flagged_at = now
            session.add(ticket)
            continue

        ticket.no_follow_up_flagged_at = now
        session.add(ticket)
        flagged += 1

        machine = session.get(Machine, ticket.machine_id)
        notify.ticket_flagged(
            session,
            machine_code=machine.code if machine else "—",
            reason="Marked fixed, but nothing has been produced on it since.",
            by=None,
        )

    session.commit()
    return {"checked": len(candidates), "flagged": flagged}


def run(session: Session) -> dict:
    """One pass over every plant. Safe to run as often as you like."""
    from .models import Plant

    summary = {"plants": 0, "checked": 0, "flagged": 0, "skipped": None}
    for plant in session.exec(select(Plant)).all():
        result = check_no_follow_up(session, plant.id)
        summary["plants"] += 1
        summary["checked"] += result["checked"]
        summary["flagged"] += result["flagged"]
        if result.get("skipped"):
            summary["skipped"] = result["skipped"]
    return summary


def main() -> None:  # pragma: no cover - the entry point the scheduler calls
    from .db import engine

    with Session(engine) as session:
        result = run(session)
    if result["skipped"]:
        print(f"No-follow-up check skipped: {result['skipped']}")
    print(
        f"Checked {result['checked']} repaired ticket(s) across "
        f"{result['plants']} plant(s); flagged {result['flagged']}."
    )


if __name__ == "__main__":  # pragma: no cover
    main()
