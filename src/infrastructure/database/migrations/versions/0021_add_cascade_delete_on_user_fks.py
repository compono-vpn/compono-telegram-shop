from typing import Sequence, Union

from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All FK constraints referencing users.telegram_id that lack ON DELETE CASCADE.
FK_UPDATES = [
    ("promocode_activations", "promocode_activations_user_telegram_id_fkey", "user_telegram_id"),
    ("transactions", "transactions_user_telegram_id_fkey", "user_telegram_id"),
    ("referrals", "referrals_referrer_telegram_id_fkey", "referrer_telegram_id"),
    ("referrals", "referrals_referred_telegram_id_fkey", "referred_telegram_id"),
    ("referral_rewards", "referral_rewards_user_telegram_id_fkey", "user_telegram_id"),
]


def upgrade() -> None:
    for table, constraint, column in FK_UPDATES:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint, table, "users", [column], ["telegram_id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    for table, constraint, column in FK_UPDATES:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint, table, "users", [column], ["telegram_id"]
        )
