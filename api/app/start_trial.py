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
import os
import sys

from sqlmodel import Session, delete, select

from .db import engine
from .models import (
    Attachment,
    AuditLog,
    Device,
    ImportRun,
    ImpregnationLog,
    Plant,
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


# Written to `plant_settings` the first time the demo is cleared, and checked
# before it is ever cleared again.
#
# THE MARKER IS IN THE DATABASE, NOT THE ENVIRONMENT
#
# This runs on container start when START_TRIAL is set, and an environment
# variable somebody forgets to clear would empty the plant's real trial data on
# the next redeploy. A row that survives in the database cannot be forgotten:
# once the trial has started, this is a no-op forever, whatever the environment
# says.
STARTED_KEY = "trial.started"


def _key_for(run_id: str) -> str:
    """The marker key for one particular clear.

    The run id lives IN the key rather than in a column of its own, which keeps
    this to zero schema changes and makes the history readable: every clear the
    plant has ever done is a row, and `SELECT key FROM plant_settings WHERE key
    LIKE 'trial.started:%'` is the whole audit.
    """
    return f"{STARTED_KEY}:{run_id}"[:64]


def already_started(session: Session, run_id: str) -> bool:
    """Whether this exact clear has already happened.

    Keyed on the VALUE of START_TRIAL, not merely on its presence. Redeploying
    with the same value — which is what happens on every restart, every env
    change and every push — is a no-op forever. Clearing a second time takes
    deliberately typing a different value, which nobody does by accident.

    That distinction is the whole safety property: the plant's real trial data
    must survive a redeploy, and it must still be possible to start over on the
    day before the trial begins.
    """
    from .models import PlantSetting

    return (
        session.exec(
            select(PlantSetting).where(PlantSetting.key == _key_for(run_id))
        ).first()
        is not None
    )


def mark_started(session: Session, run_id: str) -> None:
    from .models import PlantSetting

    plant_id = session.exec(select(Plant.id)).first()
    if plant_id is None:
        return
    session.add(
        PlantSetting(
            plant_id=plant_id, key=_key_for(run_id), minutes=None, updated_at=utcnow()
        )
    )
    session.commit()


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
    parser.add_argument(
        "--on-boot",
        action="store_true",
        help=(
            "For the container start chain. Acts only when START_TRIAL is set "
            "AND the trial has never been started before, then records that it "
            "has so a redeploy can never wipe real data."
        ),
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
        if args.on_boot:
            run_id = os.environ.get("START_TRIAL", "").strip()
            if not run_id or run_id.lower() in ("0", "false", "no"):
                return
            if already_started(session, run_id):
                print(f"Trial '{run_id}' already started — leaving the data alone.")
                return
            counts = wipe(session)
            mark_started(session, run_id)
            print(
                f"Cleared the demo: {sum(counts.values())} rows across "
                f"{len(counts)} tables. Masters kept."
            )
            return

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
