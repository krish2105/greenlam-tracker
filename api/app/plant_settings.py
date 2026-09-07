"""Reading the admin-editable dials.

Kept out of `lifecycle.py` on purpose: that module is pure — timestamps in,
verdict out, no session — which is what lets its rules be tested without a
database and mirrored exactly in `packages/core`. This is the thin layer that
fetches the numbers those rules are given.

A missing row falls back to the seeded default rather than raising. The
alternative is a plant where somebody deleted one setting and every ticket
resolution starts failing, which is a worse failure than a threshold quietly
reverting to the value it shipped with.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .lifecycle import (
    CRITICALITY_SETTING_KEYS,
    DEFAULT_CRITICALITY_THRESHOLDS,
)
from .models import PlantSetting


def _minutes(session: Session, plant_id: int, key: str) -> int | None:
    return session.exec(
        select(PlantSetting.minutes).where(
            PlantSetting.plant_id == plant_id, PlantSetting.key == key
        )
    ).first()


def criticality_thresholds(
    session: Session, plant_id: int, machine_class: str
) -> tuple[int, int]:
    """The (low_max, medium_max) pair in minutes for a press or for everything else."""
    default = DEFAULT_CRITICALITY_THRESHOLDS[machine_class]
    low_key, medium_key = CRITICALITY_SETTING_KEYS[machine_class]
    low = _minutes(session, plant_id, low_key)
    medium = _minutes(session, plant_id, medium_key)
    resolved = (
        low if low is not None else default[0],
        medium if medium is not None else default[1],
    )
    # A plant that set low above medium would make the Medium band empty and
    # every slow repair read Low. Fall back rather than classify against it.
    return default if resolved[0] >= resolved[1] else resolved
