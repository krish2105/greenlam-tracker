"""Building a `UserRead`, in one place.

Areas live in their own table, so a `UserRead` cannot come straight from
`model_validate` any more. Centralised rather than joined at each call site
because the failure mode of forgetting the join is silent: the field defaults
to an empty list, and the app decides the person has no access at all.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .models import User, UserAccessArea
from .schemas import UserRead


def areas_of(session: Session, user_id: int) -> list[str]:
    return sorted(
        session.exec(
            select(UserAccessArea.area).where(UserAccessArea.user_id == user_id)
        ).all()
    )


def user_read(session: Session, user: User) -> UserRead:
    return UserRead(
        id=user.id,
        employee_id=user.employee_id,
        name=user.name,
        areas=areas_of(session, user.id),
        approved_at=user.approved_at,
        plant_id=user.plant_id,
        unit_id=user.unit_id,
        section_id=user.section_id,
        preferred_language=user.preferred_language,
        preferred_theme=user.preferred_theme,
    )
