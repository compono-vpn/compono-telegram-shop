"""Tests for the success payment getter.

Regression: after a RENEW, msg-subscription-renew-success must report the
duration the user JUST purchased (from the latest completed transaction),
not the stale/accumulated duration on the current subscription snapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.bot.routers.subscription.getters import success_payment_getter as _success_payment_getter
from src.core.enums import PurchaseType
from src.infrastructure.billing.models import (
    BillingPlanSnapshot,
    BillingSubscription,
    BillingTransaction,
)
from tests.conftest import (
    make_config,
    make_dialog_manager,
    make_user,
    unwrap_inject,
)

success_payment_getter = unwrap_inject(_success_payment_getter)


def _make_billing_subscription(duration: int) -> BillingSubscription:
    return BillingSubscription(
        ID=1,
        Status="ACTIVE",
        URL="https://panel.example.com/sub/abc123",
        ExpireAt=datetime(2030, 1, 1, tzinfo=timezone.utc),
        Plan=BillingPlanSnapshot(
            id=2,
            name="🚀 Про",
            type="BOTH",
            duration=duration,
            traffic_limit=300,
            device_limit=6,
            traffic_limit_strategy="MONTH",
        ),
    )


def _make_billing_transaction(
    status: str,
    duration: int,
    created_at: datetime,
) -> BillingTransaction:
    return BillingTransaction(
        ID=1,
        PaymentID="",
        Status=status,
        PurchaseType="RENEW",
        GatewayType="TELEGRAM_STARS",
        Currency="XTR",
        CreatedAt=created_at,
        Plan=BillingPlanSnapshot(
            id=2,
            name="🚀 Про",
            type="BOTH",
            duration=duration,
            traffic_limit=300,
            device_limit=6,
            traffic_limit_strategy="MONTH",
        ),
    )


async def _call_success_payment_getter(billing, dialog_data=None):
    dm = make_dialog_manager()
    dm.start_data = dialog_data or {"purchase_type": PurchaseType.RENEW}
    return await success_payment_getter(
        dialog_manager=dm,
        config=make_config(),
        user=make_user(),
        billing=billing,
    )


class TestSuccessPaymentGetterAddedDuration:
    @pytest.mark.asyncio
    async def test_added_duration_reflects_just_purchased_transaction_not_stale_subscription(self):
        billing = AsyncMock()
        billing.get_current_subscription.return_value = _make_billing_subscription(duration=90)
        billing.list_transactions.return_value = [
            _make_billing_transaction(
                status="COMPLETED",
                duration=90,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            _make_billing_transaction(
                status="COMPLETED",
                duration=30,
                created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            ),
        ]

        result = await _call_success_payment_getter(billing)

        assert result["added_duration"] == (
            "unit-month",
            {"value": 1},
        )

    @pytest.mark.asyncio
    async def test_added_duration_ignores_pending_transactions(self):
        billing = AsyncMock()
        billing.get_current_subscription.return_value = _make_billing_subscription(duration=90)
        billing.list_transactions.return_value = [
            _make_billing_transaction(
                status="COMPLETED",
                duration=30,
                created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            ),
            _make_billing_transaction(
                status="PENDING",
                duration=365,
                created_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
            ),
        ]

        result = await _call_success_payment_getter(billing)

        assert result["added_duration"] == (
            "unit-month",
            {"value": 1},
        )

    @pytest.mark.asyncio
    async def test_added_duration_falls_back_to_subscription_when_no_completed_transaction(self):
        billing = AsyncMock()
        billing.get_current_subscription.return_value = _make_billing_subscription(duration=90)
        billing.list_transactions.return_value = [
            _make_billing_transaction(
                status="PENDING",
                duration=30,
                created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            ),
        ]

        result = await _call_success_payment_getter(billing)

        assert result["added_duration"] == (
            "unit-month",
            {"value": 3},
        )
