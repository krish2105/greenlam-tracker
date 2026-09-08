"""Clear the demo and hand the plant a clean system to start a trial in.

WHAT GOES, AND WHAT STAYS

Goes: every ticket, every production entry, every roll and resin batch, every
correction, every account and every notification subscription. All of it was
generated to demonstrate a system nobody had used yet, and a trial that starts
on top of 287 invented breakdowns produces a first dashboard nobody can read.

Stays: the plant, its units, the machine master, shifts, issue categories,
reject reasons and the production vocabularies. Those are not demo data — the
machine list is V5 §4's own, and wiping it would leave a system in which no
ticket can be raised until somebody retypes forty-two machines.

WHY IT IS NOT `seed --reset`

That rebuilds the demo. This empties it. They are opposite intentions and one
flag between them is how the wrong one gets run on the day it matters.

THE FIRST ADMIN

Cannot approve themselves — there is nobody above them yet (V5 §3). So one
account is created here, holding Admin, and every account after it goes through
the queue. Its PIN comes from the environment rather than being generated,
because a PIN printed into a deploy log is a PIN in a deploy log.

    python -m app.start_trial --confirm
"""

from __future__ import annotations

import argparse
import sys

from sqlmodel import Session, delete, select

from .db import engine
from .models import (
    Attachment,
    AuditLog,
    Device,
    ImportRun,
    ImpregnationLog,
    ProductionCorrection,
    ProductionLog,
    PushSubscription,
    QrScan,
    RefreshToken,
    ResinBatch,
    Ticket,
    TicketCorrection,
    TicketEvent,
    TicketMaterial,
    TicketPendingWindow,
    User,
    UserAccessArea,
    utcnow,
)
from .security import hash_pin, validate_pin_format

# Children before parents, or the foreign keys refuse. Same discipline as
# `seed.SEEDED_TABLES`, and deliberately a separate list: this one must never
# grow a master table by accident.
TRANSACTIONAL = (
    ProductionCorrection,
    TicketCorrection,
    ProductionLog,
    Attachment,
    TicketPendingWindow,
    TicketMaterial,
    TicketEvent,
    Ticket,
    ImpregnationLog,
    ResinBatch,
    QrScan,
    ImportRun,
    AuditLog,
    RefreshToken,
    Device,
    PushSubscription,
    UserAccessArea,
    User,
)


def wipe(session: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model in TRANSACTIONAL:
        name = model.__tablename__
        before = len(session.exec(select(model)).all())
        if before:
            session.exec(delete(model))
            counts[name] = before
    session.commit()
    return counts


def create_admin(session: Session, *, employee_id: str, name: str, pin: str) -> User:
    """The one account that exists before anybody can be approved.

    Given Dashboard alongside Admin. V5 §3 keeps them separate grants and this
    is the one account where combining them is right: the person setting a
    plant up has to be able to see whether it is working, and there is nobody
    else yet to grant it to them.
    """
    plant_id = session.exec(select(User.plant_id)).first()
    if plant_id is None:
        from .models import Plant

        plant = session.exec(select(Plant)).first()
        if plant is None:
            sys.exit("No plant exists. Run the migrations and the seed first.")
        plant_id = plant.id

    if not validate_pin_format(pin):
        sys.exit("The admin PIN must be 6 digits, and not a repeat or a run like 123456.")

    user = User(
        plant_id=plant_id,
        employee_id=employee_id,
        name=name,
        pin_hash=hash_pin(employee_id, pin),
        approved_at=utcnow(),
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    for area in ("admin", "dashboard"):
        session.add(UserAccessArea(user_id=user.id, area=area))
    session.commit()
    return user


def main() -> None:  # pragma: no cover - an operator command
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required. Without it this prints what it would delete and stops.",
    )
    parser.add_argument("--admin-id", default="ADMIN")
    parser.add_argument("--admin-name", default="Plant Admin")
    parser.add_argument(
        "--admin-pin",
        default=None,
        help="Six digits. Omit to skip creating an admin.",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        if not args.confirm:
            print("Would delete every row from:")
            for model in TRANSACTIONAL:
                n = len(session.exec(select(model)).all())
                if n:
                    print(f"  {model.__tablename__:26} {n}")
            print("\nMasters (plant, machines, shifts, lists) would be kept.")
            print("Re-run with --confirm to do it.")
            return

        counts = wipe(session)
        for table, n in counts.items():
            print(f"  cleared {table:26} {n}")
        print(f"\nCleared {sum(counts.values())} rows across {len(counts)} tables.")

        if args.admin_pin:
            user = create_admin(
                session,
                employee_id=args.admin_id,
                name=args.admin_name,
                pin=args.admin_pin,
            )
            print(f"\nFirst admin: {user.employee_id} ({user.name}) — admin, dashboard")
            print("Everybody else signs up in the app and is approved by them.")


if __name__ == "__main__":  # pragma: no cover
    main()
