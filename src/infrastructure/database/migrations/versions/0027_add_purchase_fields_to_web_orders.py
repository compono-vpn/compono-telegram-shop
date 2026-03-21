from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("web_orders", sa.Column("plan_id", sa.Integer(), nullable=True))
    op.add_column("web_orders", sa.Column("plan_snapshot", sa.JSON(), nullable=True))
    op.add_column("web_orders", sa.Column("gateway_type", sa.String(), nullable=True))
    op.add_column("web_orders", sa.Column("currency", sa.String(), nullable=True))
    op.add_column(
        "web_orders",
        sa.Column("is_trial", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("web_orders", "is_trial")
    op.drop_column("web_orders", "currency")
    op.drop_column("web_orders", "gateway_type")
    op.drop_column("web_orders", "plan_snapshot")
    op.drop_column("web_orders", "plan_id")
