from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("remna_user_uuid", sa.UUID(), nullable=True),
        sa.Column("remna_username", sa.String(), nullable=True),
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
            server_default=sa.text("timezone('UTC', now())"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("telegram_id"),
        sa.UniqueConstraint("remna_user_uuid"),
        sa.UniqueConstraint("remna_username"),
        sa.CheckConstraint(
            "email IS NOT NULL OR telegram_id IS NOT NULL",
            name="ck_customers_identity",
        ),
    )

    op.add_column(
        "users",
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.add_column(
        "web_orders",
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("web_orders", "customer_id")
    op.drop_column("users", "customer_id")
    op.drop_table("customers")
