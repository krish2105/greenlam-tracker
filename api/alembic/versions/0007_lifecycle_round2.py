"""Round 2 lifecycle: pending windows, ownership, handoff, reopen reason.

The decisions document rewrites the middle of the ticket lifecycle:

  * a repair can PAUSE more than once, in two different ways, and both pauses
    stop the Solve Time clock -> ticket_pending_windows
  * Acknowledge is first-tap-wins, settled atomically -> tickets.owner_id with
    a partial unique index is not enough on its own, so the claim is a
    conditional UPDATE ... WHERE owner_id IS NULL
  * Handoff works from any active status and records who reassigned
  * Reopen requires a typed reason and records who did it
  * a queued offline action keeps its device timestamp, and that provenance is
    recorded so a phone with a wrong clock is traceable

`status` is backfilled from the existing `current_stage` rather than defaulted,
so tickets already in the database land on the right status instead of all
reading "raised" on the morning after the migration.

Revision ID: 0007
Revises: 0006
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# current_stage -> status. Indexes come from STAGES in models/maintenance.py:
# 0 raised, 1 ack, 2 material, 3 repair, 4 resolved, 5 diagnosis, 6 closed.
#
# Stage 2 ("material") maps to in_progress, not on_hold_material: the old stage
# meant "materials were recorded", which is not the same claim as "work is
# paused waiting for a part". Calling those tickets held would invent a pause
# that never happened and deflate their Solve Time.
_STATUS_BACKFILL = """
    UPDATE tickets SET status = CASE
        WHEN current_stage >= 6 THEN 'closed'
        WHEN current_stage >= 4 THEN 'resolved'
        WHEN current_stage >= 2 THEN 'in_progress'
        WHEN current_stage = 1 THEN 'acknowledged'
        ELSE 'raised'
    END
"""


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("status", sa.String(length=24), nullable=False, server_default="raised"),
    )
    op.execute(_STATUS_BACKFILL)
    op.create_index("ix_tickets_status", "tickets", ["status"])

    op.add_column("tickets", sa.Column("owner_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_tickets_owner", "tickets", "users", ["owner_id"], ["id"])
    op.create_index("ix_tickets_owner_id", "tickets", ["owner_id"])
    # Whoever acknowledged it is its owner. Without this every ticket already
    # in progress looks unclaimed and is up for grabs again.
    op.execute("UPDATE tickets SET owner_id = acked_by WHERE acked_by IS NOT NULL")

    op.add_column("tickets", sa.Column("handed_off_by", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_tickets_handed_off_by", "tickets", "users", ["handed_off_by"], ["id"]
    )
    op.add_column("tickets", sa.Column("reopened_by", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_tickets_reopened_by", "tickets", "users", ["reopened_by"], ["id"])
    op.add_column("tickets", sa.Column("reopen_reason", sa.Text(), nullable=True))

    op.add_column(
        "ticket_events",
        sa.Column("ts_source", sa.String(length=8), nullable=False, server_default="server"),
    )

    op.create_table(
        "ticket_pending_windows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plant_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_by", sa.Integer(), nullable=True),
        sa.Column("ended_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.ForeignKeyConstraint(["started_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["ended_by"], ["users.id"]),
        sa.CheckConstraint(
            "kind IN ('material','correction_pending')", name="ck_pending_kind"
        ),
        # A window that ends before it starts would silently subtract time from
        # the repair and make a slow job look fast.
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at", name="ck_pending_window_order"
        ),
    )
    op.create_index(
        "ix_pending_windows_ticket", "ticket_pending_windows", ["ticket_id"]
    )
    # At most one window open per ticket. Two concurrent holds would double
    # count the wait and could push Solve Time below zero.
    op.create_index(
        "uq_pending_window_open",
        "ticket_pending_windows",
        ["ticket_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )

    op.create_check_constraint(
        "ck_tickets_status",
        "tickets",
        "status IN ('raised','acknowledged','in_progress','on_hold_material',"
        "'correction_pending','resolved','closed')",
    )
    op.create_check_constraint(
        "ck_ticket_events_ts_source", "ticket_events", "ts_source IN ('server','device')"
    )

    # The four new event types have to be allowed by the database as well as by
    # EVENT_TYPES in the model. Adding them in Python alone means the first HELD
    # event dies on a CheckViolation at runtime, which is exactly how this was
    # found.
    op.drop_constraint("ck_ticket_events_type", "ticket_events", type_="check")
    op.create_check_constraint(
        "ck_ticket_events_type",
        "ticket_events",
        "type IN ('RAISED','ACKNOWLEDGED','MATERIAL_RECORDED','REPAIR_STARTED',"
        "'RESOLVED','DIAGNOSED','CLOSED','REOPENED','HELD','RESUMED','HANDED_OFF',"
        "'CORRECTED','NOOP')",
    )


def downgrade() -> None:
    # Drop rows using the new types first: the narrower constraint cannot be
    # created while they exist, and a failed downgrade mid-way is worse than
    # losing four event kinds that only this revision could produce.
    op.execute(
        "DELETE FROM ticket_events WHERE type IN "
        "('HELD','RESUMED','HANDED_OFF','CORRECTED')"
    )
    op.drop_constraint("ck_ticket_events_type", "ticket_events", type_="check")
    op.create_check_constraint(
        "ck_ticket_events_type",
        "ticket_events",
        "type IN ('RAISED','ACKNOWLEDGED','MATERIAL_RECORDED','REPAIR_STARTED',"
        "'RESOLVED','DIAGNOSED','CLOSED','REOPENED','NOOP')",
    )

    op.drop_constraint("ck_ticket_events_ts_source", "ticket_events", type_="check")
    op.drop_constraint("ck_tickets_status", "tickets", type_="check")

    op.drop_index("uq_pending_window_open", table_name="ticket_pending_windows")
    op.drop_index("ix_pending_windows_ticket", table_name="ticket_pending_windows")
    op.drop_table("ticket_pending_windows")

    op.drop_column("ticket_events", "ts_source")

    op.drop_column("tickets", "reopen_reason")
    op.drop_constraint("fk_tickets_reopened_by", "tickets", type_="foreignkey")
    op.drop_column("tickets", "reopened_by")
    op.drop_constraint("fk_tickets_handed_off_by", "tickets", type_="foreignkey")
    op.drop_column("tickets", "handed_off_by")

    op.drop_index("ix_tickets_owner_id", table_name="tickets")
    op.drop_constraint("fk_tickets_owner", "tickets", type_="foreignkey")
    op.drop_column("tickets", "owner_id")

    op.drop_index("ix_tickets_status", table_name="tickets")
    op.drop_column("tickets", "status")
