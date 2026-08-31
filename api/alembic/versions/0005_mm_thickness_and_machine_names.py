"""Thickness in millimetres, and Hindi names for machines.

TWO CORRECTIONS, BOTH FROM THE PLANT ANSWERING A QUESTION.

1. THICKNESS IS MILLIMETRES, NOT MICRONS.

   The impregnation columns were built with the unit unconfirmed and labelled
   microns as a guess. Greenlam has since said millimetres, which is a bigger
   change than relabelling: décor paper runs roughly 0.08–0.25 mm, so two
   decimal places would round 0.125 mm to 0.13 and quietly destroy the
   resolution the measurement exists for.

   Numeric(8,2) becomes Numeric(8,3). Existing rows are converted by dividing
   by 1000 — everything already stored was entered as microns, and leaving
   them would put 120 mm sheets in a table where 0.12 is normal, which is the
   kind of silent factor-of-1000 that survives right up until somebody builds a
   supplier comparison on it.

2. MACHINES GET A LATIN-SCRIPT HINDI NAME.

   Sections, categories and reject reasons already carry all three. Machines
   had `name_hi` but no `name_hi_latn`, so the Hinglish interface fell back to
   English for the one vocabulary an operator reads most.

   Machine CODES are untouched and always will be. "Press-4" is painted on the
   machine; rendering it as "प्रेस-4" would mean the screen and the asset
   disagree, and a technician sent to a machine that is not labelled that way
   is a real failure rather than a cosmetic one.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# Micron readings already in the table, expressed in millimetres.
_TO_MM = "{col} = ROUND({col} / 1000.0, 3)"


def upgrade() -> None:
    for column in ("thickness_before", "thickness_after"):
        # Convert BEFORE widening the scale: at Numeric(8,2) the division
        # rounds to 0.12, so the precision has to exist first.
        op.alter_column(
            "impregnation_logs",
            column,
            type_=sa.Numeric(8, 3),
            existing_type=sa.Numeric(8, 2),
            existing_nullable=True,
        )
        op.execute(
            f"UPDATE impregnation_logs SET {_TO_MM.format(col=column)} "
            f"WHERE {column} IS NOT NULL"
        )

    op.add_column(
        "machines", sa.Column("name_hi_latn", sa.String(length=160), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("machines", "name_hi_latn")
    for column in ("thickness_before", "thickness_after"):
        op.execute(
            f"UPDATE impregnation_logs SET {column} = ROUND({column} * 1000.0, 2) "
            f"WHERE {column} IS NOT NULL"
        )
        op.alter_column(
            "impregnation_logs",
            column,
            type_=sa.Numeric(8, 2),
            existing_type=sa.Numeric(8, 3),
            existing_nullable=True,
        )
