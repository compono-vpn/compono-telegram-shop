from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("promocodes", sa.Column("purchase_discount_max_days", sa.Integer(), nullable=True))
    op.add_column(
        "users",
        sa.Column("purchase_discount_max_days", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "purchase_discount_max_days")
    op.drop_column("promocodes", "purchase_discount_max_days")
