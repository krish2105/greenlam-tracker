"""Link an impregnated roll to the resin batch it drew from.

This is the missing link in the traceability chain. The chain already ran

    roll -> sheets pressed from it

and the roadmap adds the step before it, so the whole thing becomes

    resin batch -> roll -> sheets

A blister found at the press can then be walked backwards past the paper to the
resin, which is the question that actually gets asked when a whole day's output
comes back.

Nullable, and it stays nullable. Rolls already in the database were impregnated
before anyone recorded a resin batch, and a NOT NULL here would either refuse
the migration or force an invented batch onto 1,365 historical rolls.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "impregnation_logs",
        sa.Column("resin_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_impregnation_resin_batch",
        "impregnation_logs",
        "resin_batches",
        ["resin_batch_id"],
        ["id"],
    )
    # The backwards walk - "which rolls came from this batch" - is the whole
    # point, and without this index it is a sequential scan of every roll the
    # plant has ever impregnated.
    op.create_index(
        "ix_impregnation_resin_batch", "impregnation_logs", ["resin_batch_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_impregnation_resin_batch", table_name="impregnation_logs")
    op.drop_constraint("fk_impregnation_resin_batch", "impregnation_logs", type_="foreignkey")
    op.drop_column("impregnation_logs", "resin_batch_id")
