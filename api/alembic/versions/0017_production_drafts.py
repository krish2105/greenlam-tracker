"""Draft and Submitted for a production entry (V5 §6.3).

WHAT A DRAFT IS FOR

A press operator fills the form between cycles, not in one sitting. Today the
only way to save half an entry is to save a whole one — which means a row with
a sheet count of zero landing on the dashboard, in the daily log and in the
Excel, and then being corrected later and tagged "Edited" for the crime of
being written in two goes.

V5 §6.3 draws the line where the ticket lifecycle already draws it: a ticket is
freely editable while it is open and only tracked once it closes. For a
production entry, "submitted" is the equivalent of "closed". A draft is private
to whoever started it, changes as often as they like, and is never tagged
Edited. Pressing Done is what makes it real.

WHY A TIMESTAMP AND NOT A BOOLEAN

The correction window in §7 is ten hours from submission. With a flag there is
no submission time to count from, and `created_at` is wrong the moment drafts
exist — an entry started on Monday and finished on Wednesday would arrive with
its correction window already expired. So the column is the anchor as well as
the state.

THE REJECT-REASON CHECK HAS TO LEARN ABOUT DRAFTS

Migration 0001 wrote `rejected_qty = 0 OR reject_reason_id IS NOT NULL`
unconditionally, and it is right: a rejection without a reason is a Pareto with
a hole in it. But it fires on INSERT, so an operator who has typed the scrap
count and not yet chosen the reason cannot save what they have — which is the
exact state drafts exist to hold. The rule now applies to submitted rows only.
It has not been weakened: `_assert_final` in the router enforces the same thing
at the Done press, and the constraint still guards every row that counts.

EXISTING ROWS ARE SUBMITTED

Backfilled from `created_at`. Every row written before this migration was final
the moment it was saved, because that was the only state there was; leaving
them NULL would make the entire production history vanish from the dashboard
in one deploy.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "production_logs",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE production_logs SET submitted_at = created_at")

    op.drop_constraint("ck_production_reject_needs_reason", "production_logs", type_="check")
    op.create_check_constraint(
        "ck_production_reject_needs_reason",
        "production_logs",
        "submitted_at IS NULL OR rejected_qty = 0 OR reject_reason_id IS NOT NULL",
    )

    # Every read path filters on this, and a draft is the rare row. A partial
    # index on the drafts is the small half; the reads want the other half, so
    # the index covers the column plainly and lets the planner choose.
    op.create_index("ix_production_logs_submitted", "production_logs", ["submitted_at"])

    # A draft belongs to one person and nobody else can see it. Fetching
    # "my drafts" is the only query that starts from the owner.
    op.create_index(
        "ix_production_logs_drafts",
        "production_logs",
        ["logged_by"],
        postgresql_where=sa.text("submitted_at IS NULL"),
    )


def downgrade() -> None:
    # Anything still a draft would violate the original constraint, and there
    # is no version of it that both restores the old rule and keeps those rows.
    # Discarding them is the honest downgrade: they were never part of the
    # plant's record, and nothing downstream has seen them.
    op.execute("DELETE FROM production_logs WHERE submitted_at IS NULL")
    op.drop_constraint("ck_production_reject_needs_reason", "production_logs", type_="check")
    op.create_check_constraint(
        "ck_production_reject_needs_reason",
        "production_logs",
        "rejected_qty = 0 OR reject_reason_id IS NOT NULL",
    )

    op.drop_index("ix_production_logs_drafts", table_name="production_logs")
    op.drop_index("ix_production_logs_submitted", table_name="production_logs")
    op.drop_column("production_logs", "submitted_at")
