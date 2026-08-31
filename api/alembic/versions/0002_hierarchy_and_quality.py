"""Org hierarchy, explicit scopes, guided why-why, and shift handover.

Three things land together because they are one change in intent: making the
system serve Greenlam's actual chain of command rather than a flat plant.

1. ROLES go from five to ten, matching Shareholders → Board → MD & CEO →
   CXO/SVP → Business heads → Plant/regional heads → Managers → Employees,
   plus admin. `supervisor` becomes `manager` to match how the business names
   the level.

2. SCOPE moves off the user row into `user_scopes`. A single `plant_id` could
   not express a business head who spans four plants or a manager who owns one
   section. Same argument as putting plant_id on every table in 0001: cheap
   now, an audit of every query later.

3. ROOT CAUSE becomes three prompted why-levels plus a stored quality score.
   Addendum §4.2: one free-text box degrades to "belt issue" within a
   fortnight, and once that happens the analytics describe nothing.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)

ROLES = (
    "shareholder",
    "board",
    "md_ceo",
    "cxo",
    "business_head",
    "plant_head",
    "manager",
    "technician",
    "operator",
    "admin",
)
ROLE_LIST = ",".join(f"'{r}'" for r in ROLES)


def upgrade() -> None:
    # ---------------------------------------------------------------- roles
    op.drop_constraint("ck_users_role", "users", type_="check")
    # The pilot's supervisors are the business's managers. Rename before the
    # new constraint lands or existing rows fail it.
    op.execute("UPDATE users SET role = 'manager' WHERE role = 'supervisor'")
    op.create_check_constraint("ck_users_role", "users", f"role IN ({ROLE_LIST})")

    # --------------------------------------------------------------- scopes
    op.create_table(
        "user_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        # A grant narrows left to right. plant only = the whole plant;
        # plant + unit = that unit; plant + unit + section = that section.
        sa.Column("plant_id", sa.Integer(), sa.ForeignKey("plants.id"), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("units.id")),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("sections.id")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "user_id", "plant_id", "unit_id", "section_id", name="uq_user_scopes_grant"
        ),
    )
    op.create_index("ix_user_scopes_user_id", "user_scopes", ["user_id"])
    op.create_index("ix_user_scopes_plant_id", "user_scopes", ["plant_id"])

    # Everyone who exists today works at their home plant. Backfilling here
    # means no user loses access the moment scope enforcement switches on.
    op.execute(
        """
        INSERT INTO user_scopes (user_id, plant_id, unit_id, section_id)
        SELECT id, plant_id, unit_id, section_id FROM users
        """
    )

    # ------------------------------------------------------- guided why-why
    op.add_column("tickets", sa.Column("why_1", sa.Text()))
    op.add_column("tickets", sa.Column("why_2", sa.Text()))
    op.add_column("tickets", sa.Column("why_3", sa.Text()))
    # Scored at write time so the trend is queryable without replaying every
    # ticket. Reported at TEAM level only — addendum §4.1.
    op.add_column("tickets", sa.Column("root_cause_score", sa.Integer()))
    op.add_column(
        "tickets",
        sa.Column("root_cause_usable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "ck_tickets_rc_score_range",
        "tickets",
        "root_cause_score IS NULL OR root_cause_score BETWEEN 0 AND 100",
    )
    # Partial index: the quality trend only ever reads closed tickets.
    op.create_index(
        "ix_tickets_rc_quality",
        "tickets",
        ["plant_id", "closed_at"],
        postgresql_where=sa.text("root_cause_score IS NOT NULL"),
    )

    # Set once when an escalation alert is actually delivered, so a retried
    # notifier job cannot page the same person twice. The escalation STATE
    # itself is derived from timestamps and never stored — Render free has no
    # cron, and a stalled escalator that leaves the board looking calm while a
    # press sits dead is worse than no escalator at all.
    op.add_column("tickets", sa.Column("escalation_notified_at", TS))
    op.add_column("tickets", sa.Column("escalation_level", sa.String(20)))

    # ------------------------------------------------------ shift handover
    op.create_table(
        "shift_handovers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("plant_id", sa.Integer(), sa.ForeignKey("plants.id"), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("units.id")),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("shifts.id"), nullable=False),
        sa.Column("handover_date", sa.Date(), nullable=False),
        # Snapshot of what the outgoing shift left behind, as published. Same
        # reasoning as review_runs.metrics: when someone asks in November why
        # the digest said four open tickets, the answer has to be recoverable.
        sa.Column("summary", postgresql.JSONB()),
        sa.Column("prepared_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("acknowledged_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("acknowledged_at", TS),
        sa.UniqueConstraint(
            "plant_id", "shift_id", "handover_date", name="uq_shift_handover_period"
        ),
    )
    op.create_index("ix_shift_handovers_plant_id", "shift_handovers", ["plant_id"])
    op.create_index("ix_shift_handovers_date", "shift_handovers", ["handover_date"])


def downgrade() -> None:
    op.drop_table("shift_handovers")

    op.drop_column("tickets", "escalation_level")
    op.drop_column("tickets", "escalation_notified_at")
    op.drop_index("ix_tickets_rc_quality", table_name="tickets")
    op.drop_constraint("ck_tickets_rc_score_range", "tickets", type_="check")
    op.drop_column("tickets", "root_cause_usable")
    op.drop_column("tickets", "root_cause_score")
    op.drop_column("tickets", "why_3")
    op.drop_column("tickets", "why_2")
    op.drop_column("tickets", "why_1")

    op.drop_table("user_scopes")

    op.drop_constraint("ck_users_role", "users", type_="check")
    op.execute(
        "UPDATE users SET role = 'manager' WHERE role IN "
        "('shareholder','board','md_ceo','cxo','business_head')"
    )
    op.execute("UPDATE users SET role = 'supervisor' WHERE role = 'manager'")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('operator','technician','supervisor','plant_head','admin')",
    )
