"""Create sent_notifications table for idempotent one-time notifications."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sent_notifications",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("notification_key", sa.String, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("UTC", sa.func.now()),
            nullable=False,
        ),
        sa.UniqueConstraint("telegram_id", "notification_key", name="uq_sent_notification"),
    )


def downgrade() -> None:
    op.drop_table("sent_notifications")
