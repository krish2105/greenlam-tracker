"""Create the first admin, if and only if there is nobody at all.

WHY THIS RUNS ON EVERY BOOT

The first Admin cannot be self-approved — there is nobody above them yet
(V5 §3) — so somebody has to be provisioned outside the app. Doing it here,
where the app's own PIN hashing and pepper live, is the only way to create a
working account without either printing a PIN into a deploy log or moving the
pepper somewhere it can be read.

WHY IT IS SAFE TO RUN EVERY TIME

Two conditions, both required, and the first can only be true once in the life
of a plant:

  * the users table is completely empty, and
  * BOOTSTRAP_ADMIN_PIN is set in the environment

After the first person exists this is a no-op forever. It cannot be used to
add a second admin, and it cannot be used to reset one — if somebody is locked
out, that is an unlock, not a bootstrap.

Set BOOTSTRAP_ADMIN_PIN once, deploy, then clear it. Leaving it set is not
dangerous while anybody exists, but a secret with no remaining purpose is a
secret somebody has to keep explaining.

    python -m app.bootstrap
"""

from __future__ import annotations

import os

from sqlmodel import Session, select

from .db import engine
from .models import Plant, User, UserAccessArea, utcnow
from .roles import AREAS
from .security import hash_pin, validate_pin_format


def run(session: Session) -> str:
    if session.exec(select(User)).first() is not None:
        return "Somebody already has an account — nothing to bootstrap."

    pin = os.environ.get("BOOTSTRAP_ADMIN_PIN", "").strip()
    if not pin:
        return "No users, and BOOTSTRAP_ADMIN_PIN is not set — nobody can sign in yet."
    if not validate_pin_format(pin):
        return "BOOTSTRAP_ADMIN_PIN must be 6 digits, and not a repeat or a run."

    plant = session.exec(select(Plant)).first()
    if plant is None:
        return "No plant yet — migrations and the seed run before this."

    employee_id = os.environ.get("BOOTSTRAP_ADMIN_ID", "ADMIN").strip() or "ADMIN"
    name = os.environ.get("BOOTSTRAP_ADMIN_NAME", "Plant Admin").strip() or "Plant Admin"

    user = User(
        plant_id=plant.id,
        employee_id=employee_id,
        name=name,
        pin_hash=hash_pin(employee_id, pin),
        approved_at=utcnow(),
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    # EVERY area, not just admin and dashboard.
    #
    # The first version granted those two, reasoning that whoever sets a plant
    # up needs to see whether it is working. That gave them the board and
    # withheld the floor — the half they would actually want to test — because
    # Admin does not grant `log_production` and V5 §3 is right to keep those
    # separate. The result: the only account on a freshly cleared system opened
    # the app, found no Production section, and reasonably concluded something
    # had been deleted. Nothing had.
    #
    # All six is the right default for the one account that has to prove the
    # whole system before anybody else exists. V5 §3 explicitly allows one
    # person to hold all of them, and the Access screen is where it gets
    # narrowed the moment there is somebody to narrow it in favour of.
    for area in AREAS:
        session.add(UserAccessArea(user_id=user.id, area=area))
    session.commit()

    return f"Created the first admin: {employee_id} ({name}) — admin, dashboard."


def main() -> None:  # pragma: no cover - a deploy step
    with Session(engine) as session:
        print(run(session))


if __name__ == "__main__":  # pragma: no cover
    main()
