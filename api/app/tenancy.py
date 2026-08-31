"""Who is asking, and which rows they may see.

ONE AXIS NOW, NOT THREE

This file used to carry capability × scope × resolution: a user held a list of
grants (plant, unit, optionally section), `scope()` OR-ed them together, and a
separate `resolution` decided how much detail came back. That expressed a group
with five plants, a board, and managers who each owned one section.

It is the wrong shape for one plant running one pilot. Access there is a single
question — does this person need the dashboard, or just the app — and that is
answered by `roles.py`. What remains here is the part that was always going to
matter and would have been expensive to retrofit: every table carries
`plant_id`, and every query goes through `scope()`, so the day a second plant
arrives the filter is already in the right place.

The section grants are DELETED rather than left evaluating to true. A guard
that always passes is worse than no guard, because the next person writes code
believing it still guards something.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlmodel import SQLModel, select
from sqlmodel.sql.expression import SelectOfScalar

from .roles import can, sees_dashboard

if TYPE_CHECKING:  # pragma: no cover
    pass


@dataclass
class Principal:
    """Who is asking, and what they may do."""

    user_id: int
    role: str
    home_plant_id: int
    home_unit_id: int | None = None
    # Which plants this person may read. One entry today; the list shape is
    # what keeps a second plant from being a schema change.
    plant_ids: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.plant_ids:
            self.plant_ids = [self.home_plant_id]

    def can(self, capability: str) -> bool:
        return can(self.role, capability)

    @property
    def sees_dashboard(self) -> bool:
        return sees_dashboard(self.role)

    def covers_plant(self, plant_id: int) -> bool:
        return plant_id in self.plant_ids

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Principal user={self.user_id} role={self.role} plants={self.plant_ids}>"


def scope[T: SQLModel](model: type[T], principal: Principal) -> SelectOfScalar[T]:
    """Every read of tenant data starts here.

    Refuses outright on a model with no `plant_id` rather than returning an
    unfiltered query. A tenant filter that silently does nothing is the exact
    bug this layer exists to prevent, so the failure is a TypeError at import
    time rather than a data leak at runtime.
    """
    if not hasattr(model, "plant_id"):
        raise TypeError(f"{model.__name__} has no plant_id and cannot be tenant-scoped.")

    stmt = select(model)
    if not principal.plant_ids:
        # Fail closed. No plant means no rows, never all rows.
        return stmt.where(model.plant_id.is_(None))
    return stmt.where(model.plant_id.in_(principal.plant_ids))


def assert_visible(row: object | None, principal: Principal) -> None:
    """404 rather than 403 for a row outside the caller's plant.

    Telling someone a ticket exists but is not theirs leaks the fact that it
    exists. For a row they may not read, the honest answer is that there is
    nothing there.
    """
    plant_id = getattr(row, "plant_id", None)
    if row is None or plant_id is None or not principal.covers_plant(plant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found.")
