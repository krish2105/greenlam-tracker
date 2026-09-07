"""Resin batches.

The roadmap gives the resin kettle its own form - batch number, quantity,
operator, date, time - and then adds "for resin as well" beside the accepted
and rejected counts, so a batch is inspected like a batch of sheets is.

The batch number matters beyond this table: it is what an impregnated roll will
reference, and the link is what lets a blister found at the press be traced
back to the resin it came from. Unique per plant for that reason - two batches
sharing a number would make the trace ambiguous exactly when somebody is
relying on it.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resin_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plant_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("shift_id", sa.Integer(), nullable=True),
        sa.Column("batch_no", sa.String(length=64), nullable=False),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=True),
        sa.Column("unit_of_measure", sa.String(length=16), nullable=True),
        sa.Column("accepted_qty", sa.Numeric(10, 2), nullable=True),
        sa.Column("rejected_qty", sa.Numeric(10, 2), nullable=True),
        sa.Column("reject_reason_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("logged_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"]),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"]),
        sa.ForeignKeyConstraint(["reject_reason_id"], ["reject_reasons.id"]),
        sa.ForeignKeyConstraint(["logged_by"], ["users.id"]),
        # Rejecting more than was made is a typo, and it silently corrupts every
        # yield figure downstream.
        sa.CheckConstraint(
            "rejected_qty IS NULL OR quantity IS NULL OR rejected_qty <= quantity",
            name="ck_resin_rejected_within_quantity",
        ),
        sa.CheckConstraint("quantity IS NULL OR quantity >= 0", name="ck_resin_qty_positive"),
    )
    op.create_index("ix_resin_batches_plant", "resin_batches", ["plant_id"])
    op.create_index("ix_resin_batches_machine", "resin_batches", ["machine_id"])
    op.create_index("ix_resin_batches_date", "resin_batches", ["log_date"])
    # The trace depends on this being unambiguous.
    op.create_index(
        "uq_resin_batch_no_per_plant", "resin_batches", ["plant_id", "batch_no"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_resin_batch_no_per_plant", table_name="resin_batches")
    op.drop_index("ix_resin_batches_date", table_name="resin_batches")
    op.drop_index("ix_resin_batches_machine", table_name="resin_batches")
    op.drop_index("ix_resin_batches_plant", table_name="resin_batches")
    op.drop_table("resin_batches")
