from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("web_orders", sa.Column("promocode_id", sa.Integer(), nullable=True))
    op.add_column("web_orders", sa.Column("discount_percent", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("web_orders", "discount_percent")
    op.drop_column("web_orders", "promocode_id")
