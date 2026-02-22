from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

promocode_availability_enum = sa.Enum(
    "ALL", "NEW", "EXISTING", "INVITED", "ALLOWED",
    name="promocode_availability",
)


def upgrade() -> None:
    promocode_availability_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "promocodes",
        sa.Column(
            "availability",
            promocode_availability_enum,
            nullable=False,
            server_default="ALL",
        ),
    )

    op.execute("ALTER TYPE promocode_reward_type ADD VALUE IF NOT EXISTS 'DEVICES'")


def downgrade() -> None:
    op.drop_column("promocodes", "availability")
    promocode_availability_enum.drop(op.get_bind(), checkfirst=True)
