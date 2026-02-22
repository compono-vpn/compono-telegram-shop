"""add allowed_telegram_ids to promocodes

Revision ID: 0020
Revises: 0019
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "promocodes",
        sa.Column(
            "allowed_telegram_ids",
            sa.ARRAY(sa.BigInteger()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("promocodes", "allowed_telegram_ids")
