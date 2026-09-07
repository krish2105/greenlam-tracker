"""Criticality, calculated rather than chosen. And the dials that decide it.

WHAT CHANGED, AND WHY IT IS NOT A RENAME

Until now a person picked a ticket's priority when they raised it. V5 §5.8
removes that judgement call entirely: once the repair is finished, the system
measures how long the actual work took and classifies it.

    solve time = (correction complete - correction started) - pending time

Press: under 30 min Low, 30-60 Medium, over an hour High. Everything else:
under an hour, one to two, over two.

TWO COLUMNS, NOT ONE

`criticality_calculated` is an OUTCOME. It does not exist until the repair is
over, so it cannot rank a live queue - at the exact moment somebody needs to
know which of four open tickets to walk to first, every one of them is NULL.
That job stays with `machines.criticality` (A/B/C), which says how much the
machine matters and is known before anything breaks.

Collapsing the two would lose both: a live queue sorted by a column that is
always NULL, and an outcome overwritten by a guess made before the work began.
The old `priority` column is left alone here and retired separately, once the
Excel export and the register importer stop reading it.

THE THRESHOLDS ARE DATA

V5 §16 makes them admin-configurable, and the defaults above are a starting
hypothesis about this plant, not a law. Every configurable value V5 names is a
duration, so one table with a minutes column holds all of them - the
repeat-failure and no-follow-up-production windows land here too.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# Seeded per plant on upgrade. Keys are namespaced so a settings screen can
# group them without a second column saying which group they belong to.
DEFAULTS: tuple[tuple[str, int], ...] = (
    ("criticality.press.low_max", 30),
    ("criticality.press.medium_max", 60),
    ("criticality.other.low_max", 60),
    ("criticality.other.medium_max", 120),
)


def upgrade() -> None:
    op.create_table(
        "plant_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plant_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        # Every dial V5 makes configurable is a duration. NULL means "not
        # decided yet" and the caller must say what it does about that -
        # the no-follow-up-production window arrives that way, because V5 §16
        # defers it until the trial has produced a baseline.
        sa.Column("minutes", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.UniqueConstraint("plant_id", "key", name="uq_plant_setting"),
        sa.CheckConstraint("minutes IS NULL OR minutes > 0", name="ck_plant_setting_positive"),
    )

    for key, minutes in DEFAULTS:
        op.execute(
            sa.text(
                "INSERT INTO plant_settings (plant_id, key, minutes) "
                "SELECT id, :key, :minutes FROM plants"
            ).bindparams(key=key, minutes=minutes)
        )

    op.add_column("tickets", sa.Column("solve_minutes", sa.Float(), nullable=True))
    op.add_column(
        "tickets", sa.Column("criticality_calculated", sa.String(length=10), nullable=True)
    )
    op.create_check_constraint(
        "ck_tickets_criticality_calculated",
        "tickets",
        "criticality_calculated IS NULL OR criticality_calculated IN ('Low','Medium','High')",
    )
    # "Show me every High repair last month" is the question this exists to
    # answer, and it is asked against a table that grows by every breakdown.
    op.create_index(
        "ix_tickets_criticality_calculated", "tickets", ["criticality_calculated"]
    )

    # Existing resolved tickets are NOT backfilled.
    #
    # Solve time needs `repair_at` and the pending windows, and tickets raised
    # before migration 0007 have neither - the register import never carried a
    # correction-start time. A backfill would therefore classify the recent
    # tickets and silently leave a year of history NULL, which reads on a
    # dashboard as "no High repairs before August" rather than "not measured".
    # NULL everywhere is the honest version of the same fact.


def downgrade() -> None:
    op.drop_index("ix_tickets_criticality_calculated", table_name="tickets")
    op.drop_constraint("ck_tickets_criticality_calculated", "tickets", type_="check")
    op.drop_column("tickets", "criticality_calculated")
    op.drop_column("tickets", "solve_minutes")
    op.drop_table("plant_settings")
