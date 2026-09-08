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

    # Admin AND Dashboard. V5 §3 keeps them separate grants and this is the one
    # account where combining them is right: the person setting a plant up has
    # to be able to see whether it is working, and there is nobody else yet to
    # grant it to them. They can narrow it from the Access screen afterwards.
    for area in ("admin", "dashboard"):
        session.add(UserAccessArea(user_id=user.id, area=area))
    session.commit()

    return f"Created the first admin: {employee_id} ({name}) — admin, dashboard."


def main() -> None:  # pragma: no cover - a deploy step
    with Session(engine) as session:
        print(run(session))


if __name__ == "__main__":  # pragma: no cover
    main()
