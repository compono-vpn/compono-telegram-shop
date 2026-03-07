from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "web_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("payment_id", sa.UUID(), unique=True, nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("plan_duration_days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("subscription_url", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("web_orders")
