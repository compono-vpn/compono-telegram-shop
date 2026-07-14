from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.core.enums import Currency, PaymentGatewayType, PurchaseType, TransactionStatus
from src.infrastructure.taskiq.tasks.subscriptions import purchase_subscription_task
from src.models.dto import PriceDetailsDto, TransactionDto
from tests.conftest import make_plan_snapshot, make_user
from tests.test_api_client import _make_provision_result, unwrap_task


def _make_transaction(plan) -> TransactionDto:
    return TransactionDto(
        payment_id=uuid4(),
        status=TransactionStatus.COMPLETED,
        purchase_type=PurchaseType.NEW,
        gateway_type=PaymentGatewayType.YOOKASSA,
        pricing=PriceDetailsDto(),
        currency=Currency.RUB,
        plan=plan,
        user=make_user(telegram_id=777),
    )


class TestPurchaseSubscriptionTaskFlushesPendingReferralRewards:
    async def test_flushes_pending_rewards_after_new_purchase(self):
        plan = make_plan_snapshot()
        transaction = _make_transaction(plan)

        api_client = AsyncMock()
        api_client.provision_user.return_value = _make_provision_result()
        remnawave_service = AsyncMock()
        subscription_service = AsyncMock()
        subscription_service.get_current.return_value = None
        transaction_service = AsyncMock()
        notification_service = AsyncMock()
        referral_service = AsyncMock()
        redis_client = AsyncMock()
        config = MagicMock()
        config.remnawave.sub_public_domain = "componovpn.com"

        raw_fn = unwrap_task(purchase_subscription_task)

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.redirect_to_successed_payment_task",
        ) as mock_redirect:
            mock_redirect.kiq = AsyncMock()
            await raw_fn(
                transaction=transaction,
                subscription=None,
                config=config,
                api_client=api_client,
                remnawave_service=remnawave_service,
                subscription_service=subscription_service,
                transaction_service=transaction_service,
                notification_service=notification_service,
                referral_service=referral_service,
                redis_client=redis_client,
            )

        referral_service.flush_pending_rewards.assert_awaited_once_with(777)
        transaction_service.update.assert_not_awaited()

    async def test_flush_failure_does_not_fail_the_purchase(self):
        plan = make_plan_snapshot()
        transaction = _make_transaction(plan)

        api_client = AsyncMock()
        api_client.provision_user.return_value = _make_provision_result()
        remnawave_service = AsyncMock()
        subscription_service = AsyncMock()
        subscription_service.get_current.return_value = None
        transaction_service = AsyncMock()
        notification_service = AsyncMock()
        referral_service = AsyncMock()
        referral_service.flush_pending_rewards.side_effect = RuntimeError("billing down")
        redis_client = AsyncMock()
        config = MagicMock()
        config.remnawave.sub_public_domain = "componovpn.com"

        raw_fn = unwrap_task(purchase_subscription_task)

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.redirect_to_successed_payment_task",
        ) as mock_redirect:
            mock_redirect.kiq = AsyncMock()
            await raw_fn(
                transaction=transaction,
                subscription=None,
                config=config,
                api_client=api_client,
                remnawave_service=remnawave_service,
                subscription_service=subscription_service,
                transaction_service=transaction_service,
                notification_service=notification_service,
                referral_service=referral_service,
                redis_client=redis_client,
            )

        transaction_service.update.assert_not_awaited()
        mock_redirect.kiq.assert_awaited_once()
