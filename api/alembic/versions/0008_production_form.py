"""Which production form a machine gets.

The roadmap asks for three different production forms - a press logs sheets
against a material code, a resin kettle logs a batch and a quantity, an
impregnator logs paper, RC/VC and the resin batch it drew from.

Section is NOT the right thing to key that off. A section says where a machine
stands; the form says what it does, and the two come apart the moment a plant
puts a second impregnator in a different area or files something under "Other".
So it is declared on the machine.

Backfilled from the section name, because that is the best guess available and
leaving 33 machines NULL would mean nobody can log production until somebody
sets all of them by hand.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

FORMS = ("press", "resin", "impregnation", "general")

_BACKFILL = """
    UPDATE machines m SET production_form = CASE
        WHEN s.name ILIKE 'press%%'        THEN 'press'
        WHEN s.name ILIKE 'impregnat%%'    THEN 'impregnation'
        WHEN s.name ILIKE 'resin%%'        THEN 'resin'
        ELSE 'general'
    END
    FROM sections s
    WHERE s.id = m.section_id
"""


def upgrade() -> None:
    op.add_column(
        "machines",
        sa.Column(
            "production_form", sa.String(length=20), nullable=False, server_default="general"
        ),
    )
    op.execute(_BACKFILL)
    op.create_check_constraint(
        "ck_machines_production_form",
        "machines",
        "production_form IN ('press','resin','impregnation','general')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_machines_production_form", "machines", type_="check")
    op.drop_column("machines", "production_form")
