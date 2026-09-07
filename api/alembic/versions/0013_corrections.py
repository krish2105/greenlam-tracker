"""Correcting a record without erasing what it used to say.

WHY A CORRECTION IS NOT AN EDIT

Somebody types 480 when they meant 4800. That number is already on a dashboard,
already in the Excel workbook, and possibly already in somebody's head. V5 §7
says the fix has to be visible everywhere the number is, and that the original
has to survive somewhere it can be looked up.

So: the row is updated IN PLACE - one row per ticket, one per production entry,
never a second copy - and the previous value is appended to a correction log
nobody reads day to day. The app, the dashboard and the workbook always show
the current truth, carrying an "Edited" mark; the argument about what it said
before is settled by a query, not by memory.

WHY THIS IS NOT REOPEN

Reopen (§5.4) asserts the machine is still broken and sends the ticket back to
Correction Pending. Correct asserts a keystroke was wrong and changes nothing
else - the status stays Closed and `closed_at` does not move. Conflating them
would put a ticket nobody touched back into the live Pending count and could
fire the repeat-failure flag for a breakdown that never happened.

TWO TABLES, NOT ONE POLYMORPHIC ONE

Same shape, and it was tempting. But an audit trail is exactly the thing that
gets consulted years later in an argument, and a `record_id` with no foreign
key behind it is a row that can quietly point at nothing. Two tables cost a
duplicated CREATE; they buy a database that cannot hold an orphaned correction.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _correction_columns() -> list[sa.Column]:
    """The shape both logs share."""
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plant_id", sa.Integer(), nullable=False),
        # The field as the API names it, e.g. "produced_qty" or "why_1".
        sa.Column("field", sa.String(length=64), nullable=False),
        # Rendered as text, both of them, including NULL -> NULL.
        #
        # A typed column per kind would mean six nullable columns of which five
        # are always empty. This log is written rarely and read by a human, so
        # the cost of losing the type is a cast in a query nobody runs weekly,
        # and the gain is that a timestamp correction and a quantity correction
        # are the same row shape.
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("corrected_by", sa.Integer(), nullable=False),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        # True when an admin corrected a record past its self-edit window. The
        # distinction is the whole point of having a window: a fix inside it is
        # routine, a fix outside it was authorised by somebody.
        sa.Column("outside_window", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


def upgrade() -> None:
    op.create_table(
        "ticket_corrections",
        *_correction_columns(),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"]),
        sa.ForeignKeyConstraint(["corrected_by"], ["users.id"]),
    )
    op.create_index("ix_ticket_corrections_ticket", "ticket_corrections", ["ticket_id"])

    op.create_table(
        "production_corrections",
        *_correction_columns(),
        sa.Column("production_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["production_log_id"], ["production_logs.id"]),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"]),
        sa.ForeignKeyConstraint(["corrected_by"], ["users.id"]),
    )
    op.create_index(
        "ix_production_corrections_log", "production_corrections", ["production_log_id"]
    )

    # V5 §7 names these three columns for the Excel export. Using its names
    # here too means the workbook is a projection of the table rather than a
    # translation of it.
    for table in ("tickets", "production_logs"):
        op.add_column(
            table, sa.Column("last_edited_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.add_column(table, sa.Column("last_edited_by", sa.Integer(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_last_edited_by", table, "users", ["last_edited_by"], ["id"]
        )
    # "Show me everything that has been amended since it was logged" is a
    # supervisor's question, and without this it reads every ticket ever raised.
    op.create_index(
        "ix_tickets_last_edited_at",
        "tickets",
        ["last_edited_at"],
        postgresql_where=sa.text("last_edited_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_last_edited_at", table_name="tickets")
    for table in ("tickets", "production_logs"):
        op.drop_constraint(f"fk_{table}_last_edited_by", table, type_="foreignkey")
        op.drop_column(table, "last_edited_by")
        op.drop_column(table, "last_edited_at")
    op.drop_index("ix_production_corrections_log", table_name="production_corrections")
    op.drop_table("production_corrections")
    op.drop_index("ix_ticket_corrections_ticket", table_name="ticket_corrections")
    op.drop_table("ticket_corrections")
