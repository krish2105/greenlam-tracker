"""Scheduled operating hours per machine.

THE LAST INPUT AVAILABILITY WAS MISSING.

`availability_percent` has been computed on CALENDAR hours since it existed —
machines × days × 24 — and labelled `availability_basis: "calendar"` everywhere
it appears, because a press that runs two shifts is not unavailable for the
third. Calendar availability flatters every plant that does not run 24/7, which
is most of them, and 99.22% on the seeded data is exactly that flattery.

With scheduled hours the same arithmetic becomes real OEE availability, and the
label changes to say so. Nullable, so a plant that has not answered keeps the
honest calendar figure rather than getting a silently wrong "real" one.

`hourly_downtime_cost` and `criticality` already existed on this table and are
untouched here — what they lacked was a screen and, in the cost's case, any
code that read it. Both land in this change set alongside the migration.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "machines",
        # Hours per day this machine is SUPPOSED to run. Two shifts is 16, three
        # is 24, a machine used one day a week is ~3.4. Per machine rather than
        # per plant because a boiler and a press rarely share a schedule.
        sa.Column("scheduled_hours_per_day", sa.Numeric(4, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_machines_scheduled_hours",
        "machines",
        "scheduled_hours_per_day IS NULL OR "
        "(scheduled_hours_per_day > 0 AND scheduled_hours_per_day <= 24)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_machines_scheduled_hours", "machines", type_="check")
    op.drop_column("machines", "scheduled_hours_per_day")
