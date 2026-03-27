"""Backfill customers table from existing web_orders and users.

For each distinct email in completed web_orders:
  - Create a Customer with that email and the latest subscription_url
  - Set customer_id on all matching web_orders

For each user with a current subscription (and thus a Remnawave user):
  - If user's linked_emails overlap with an existing customer, merge
  - Otherwise create a new Customer with telegram_id
  - Set user.customer_id
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Create customers from web_orders (by distinct email)
    # For each email, use the latest completed order's subscription_url
    rows = conn.execute(
        sa.text("""
            SELECT DISTINCT ON (email) email, subscription_url
            FROM web_orders
            WHERE status = 'completed' AND subscription_url IS NOT NULL
            ORDER BY email, created_at DESC
        """)
    ).fetchall()

    for email, subscription_url in rows:
        # Check if customer already exists (shouldn't, but be safe)
        existing = conn.execute(
            sa.text("SELECT id FROM customers WHERE email = :email"),
            {"email": email},
        ).fetchone()

        if existing:
            customer_id = existing[0]
            # Update subscription_url if not set
            conn.execute(
                sa.text("""
                    UPDATE customers SET subscription_url = :url
                    WHERE id = :id AND subscription_url IS NULL
                """),
                {"url": subscription_url, "id": customer_id},
            )
        else:
            result = conn.execute(
                sa.text("""
                    INSERT INTO customers (email, subscription_url)
                    VALUES (:email, :url)
                    RETURNING id
                """),
                {"email": email, "url": subscription_url},
            )
            customer_id = result.fetchone()[0]

        # Link all web_orders for this email
        conn.execute(
            sa.text("""
                UPDATE web_orders SET customer_id = :cid
                WHERE email = :email AND customer_id IS NULL
            """),
            {"cid": customer_id, "email": email},
        )

    # Step 2: Link users to customers
    # For users with linked_emails, try to find matching customer by email
    users_with_emails = conn.execute(
        sa.text("""
            SELECT u.telegram_id, u.linked_emails, s.user_remna_id
            FROM users u
            LEFT JOIN subscriptions s ON s.id = u.current_subscription_id
            WHERE u.customer_id IS NULL
        """)
    ).fetchall()

    for telegram_id, linked_emails_json, user_remna_id in users_with_emails:
        customer_id = None

        # Try to find customer by linked_emails
        if linked_emails_json:
            emails = linked_emails_json if isinstance(linked_emails_json, list) else []
            for email in emails:
                row = conn.execute(
                    sa.text("SELECT id FROM customers WHERE email = :email"),
                    {"email": email},
                ).fetchone()
                if row:
                    customer_id = row[0]
                    break

        if customer_id:
            # Merge: update existing customer with telegram_id if not set
            conn.execute(
                sa.text("""
                    UPDATE customers SET telegram_id = :tg_id
                    WHERE id = :id AND telegram_id IS NULL
                """),
                {"tg_id": telegram_id, "id": customer_id},
            )
        else:
            # Create new customer with telegram_id
            result = conn.execute(
                sa.text("""
                    INSERT INTO customers (telegram_id)
                    VALUES (:tg_id)
                    ON CONFLICT (telegram_id) DO UPDATE SET telegram_id = :tg_id
                    RETURNING id
                """),
                {"tg_id": telegram_id},
            )
            customer_id = result.fetchone()[0]

        # Link user to customer
        conn.execute(
            sa.text("UPDATE users SET customer_id = :cid WHERE telegram_id = :tg_id"),
            {"cid": customer_id, "tg_id": telegram_id},
        )

        # If user has a Remnawave subscription, store UUID on customer
        if user_remna_id:
            conn.execute(
                sa.text("""
                    UPDATE customers SET remna_user_uuid = :uuid
                    WHERE id = :id AND remna_user_uuid IS NULL
                """),
                {"uuid": user_remna_id, "id": customer_id},
            )


def downgrade() -> None:
    # Data-only migration — just clear the FKs
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE users SET customer_id = NULL"))
    conn.execute(sa.text("UPDATE web_orders SET customer_id = NULL"))
    conn.execute(sa.text("DELETE FROM customers"))
