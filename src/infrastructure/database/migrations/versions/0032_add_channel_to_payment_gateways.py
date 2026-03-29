"""Add channel column to payment_gateways table.

Introduces a gateway_channel enum (BOT, WEB, ALL) and adds it as a
non-nullable column with server_default 'ALL'.  Replaces the old
unique constraint on (type) with a composite unique on (type, channel).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the enum type
    gateway_channel = postgresql.ENUM("BOT", "WEB", "ALL", name="gateway_channel", create_type=True)
    gateway_channel.create(op.get_bind(), checkfirst=True)

    # Add the column
    op.add_column(
        "payment_gateways",
        sa.Column("channel", gateway_channel, nullable=False, server_default="ALL"),
    )

    # Drop old unique constraint on type and add composite unique on (type, channel)
    op.drop_constraint("payment_gateways_type_key", "payment_gateways", type_="unique")
    op.create_unique_constraint(
        "uq_payment_gateways_type_channel", "payment_gateways", ["type", "channel"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_payment_gateways_type_channel", "payment_gateways", type_="unique")
    op.drop_column("payment_gateways", "channel")
    op.create_unique_constraint("payment_gateways_type_key", "payment_gateways", ["type"])
    sa.Enum(name="gateway_channel").drop(op.get_bind(), checkfirst=True)
