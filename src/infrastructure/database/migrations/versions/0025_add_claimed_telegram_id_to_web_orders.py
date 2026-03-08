from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "web_orders",
        sa.Column("claimed_by_telegram_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_web_orders_claimed_by_telegram_id",
        "web_orders",
        ["claimed_by_telegram_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_web_orders_claimed_by_telegram_id", table_name="web_orders")
    op.drop_column("web_orders", "claimed_by_telegram_id")
