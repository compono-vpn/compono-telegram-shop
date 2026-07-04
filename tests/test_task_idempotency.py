"""BDT-367: idempotency guards for provisioning/renewal taskiq tasks.

A mid-task crash + taskiq retry (retry_on_error=True, count=5, see broker.py)
can re-run a purchase/trial/renew/change task for the *same* payment_id (or,
for trials, the same telegram_id). Without a guard this:
  - re-provisions a second Remnawave user (trial / new purchase), or
  - re-applies the renew/change expiry math a second time, granting free
    paid time (renew/change).

These tests run each task/handler TWICE for the same logical operation and
assert the Remnawave-mutating call happens exactly once, and (for renew)
that the resulting expiry is not extended twice. They also confirm the
guard is scoped per payment_id/telegram_id (a different one is not
blocked) and that a genuine pre-mutation failure does not permanently
block a legitimate retry.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.core.enums import (
    Currency,
    PaymentGatewayType,
    PurchaseType,
    SubscriptionStatus,
    TransactionStatus,
)
from src.core.utils.time import datetime_now
from src.infrastructure.api.client import ApiClientError
from src.infrastructure.taskiq.tasks.subscriptions import (
    _handle_change_purchase,
    _handle_new_purchase,
    _handle_renew_purchase,
    trial_subscription_task,
)
from src.models.dto import PriceDetailsDto, SubscriptionDto, TransactionDto
from tests.conftest import make_plan_snapshot, make_user
from tests.test_api_client import _make_provision_result, unwrap_task


class FakeRedis:
    """Dict-backed stand-in for redis.asyncio.Redis.

    Only implements the primitives the idempotency guard needs
    (get/set/exists/delete), enough for state to persist across repeated
    calls within a test -- unlike a plain AsyncMock, whose return values
    don't carry over between invocations.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        return int(key in self._store)

    async def get(self, key: str) -> Optional[bytes]:
        value = self._store.get(key)
        return value.encode() if value is not None else None

    async def set(self, key: str, value: str, ex: Optional[int] = None, nx: bool = False) -> Optional[bool]:
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                count += 1
        return count


def _make_transaction(purchase_type: PurchaseType, plan, payment_id=None) -> TransactionDto:
    return TransactionDto(
        payment_id=payment_id or uuid4(),
        status=TransactionStatus.COMPLETED,
        purchase_type=purchase_type,
        gateway_type=PaymentGatewayType.YOOKASSA,
        pricing=PriceDetailsDto(),
        currency=Currency.RUB,
        plan=plan,
    )


def _make_active_subscription(plan, expire_at) -> SubscriptionDto:
    return SubscriptionDto(
        user_remna_id=uuid4(),
        status=SubscriptionStatus.ACTIVE,
        is_trial=False,
        traffic_limit=plan.traffic_limit,
        device_limit=plan.device_limit,
        traffic_limit_strategy=plan.traffic_limit_strategy,
        internal_squads=[],
        external_squad=None,
        expire_at=expire_at,
        url="https://panel.example.com/sub/abc123",
        plan=plan,
    )


class TestTrialTaskIdempotency:
    """Running trial_subscription_task twice must provision exactly once."""

    async def test_run_twice_provisions_once(self):
        user = make_user()
        plan = make_plan_snapshot()

        api_client = AsyncMock()
        api_client.provision_user.return_value = _make_provision_result()

        subscription_service = AsyncMock()
        notification_service = AsyncMock()
        redis_client = FakeRedis()
        config = MagicMock()
        config.remnawave.sub_public_domain = "componovpn.com"

        raw_fn = unwrap_task(trial_subscription_task)

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.schedule_not_connected_reminder",
            new_callable=AsyncMock,
        ):
            for _ in range(2):
                await raw_fn(
                    user=user,
                    plan=plan,
                    skip_redirect=True,
                    config=config,
                    api_client=api_client,
                    subscription_service=subscription_service,
                    notification_service=notification_service,
                    redis_client=redis_client,
                )

        assert api_client.provision_user.call_count == 1
        assert subscription_service.create.call_count == 1

    async def test_different_user_is_not_blocked(self):
        plan = make_plan_snapshot()
        api_client = AsyncMock()
        api_client.provision_user.return_value = _make_provision_result()
        subscription_service = AsyncMock()
        notification_service = AsyncMock()
        redis_client = FakeRedis()
        config = MagicMock()
        config.remnawave.sub_public_domain = "componovpn.com"

        raw_fn = unwrap_task(trial_subscription_task)

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.schedule_not_connected_reminder",
            new_callable=AsyncMock,
        ):
            for telegram_id in (111, 222):
                await raw_fn(
                    user=make_user(telegram_id=telegram_id),
                    plan=plan,
                    skip_redirect=True,
                    config=config,
                    api_client=api_client,
                    subscription_service=subscription_service,
                    notification_service=notification_service,
                    redis_client=redis_client,
                )

        assert api_client.provision_user.call_count == 2

    async def test_failed_attempt_does_not_block_retry(self):
        """A crash/error *before* provisioning must not permanently block
        a legitimate retry -- only an already-succeeded mutation should be
        skipped."""
        user = make_user()
        plan = make_plan_snapshot()

        api_client = AsyncMock()
        api_client.provision_user.side_effect = [
            ApiClientError(500, "transient error"),
            _make_provision_result(),
        ]

        subscription_service = AsyncMock()
        notification_service = AsyncMock()
        redis_client = FakeRedis()
        config = MagicMock()
        config.remnawave.sub_public_domain = "componovpn.com"

        raw_fn = unwrap_task(trial_subscription_task)

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.schedule_not_connected_reminder",
            new_callable=AsyncMock,
        ), patch(
            "src.infrastructure.taskiq.tasks.subscriptions.redirect_to_failed_subscription_task",
        ) as mock_redirect:
            mock_redirect.kiq = AsyncMock()
            # First attempt fails before provisioning succeeds.
            await raw_fn(
                user=user,
                plan=plan,
                skip_redirect=True,
                config=config,
                api_client=api_client,
                subscription_service=subscription_service,
                notification_service=notification_service,
                redis_client=redis_client,
            )
            # Retry must still be allowed to provision.
            await raw_fn(
                user=user,
                plan=plan,
                skip_redirect=True,
                config=config,
                api_client=api_client,
                subscription_service=subscription_service,
                notification_service=notification_service,
                redis_client=redis_client,
            )

        assert api_client.provision_user.call_count == 2
        subscription_service.create.assert_called_once()


class TestNewPurchaseIdempotency:
    """Running _handle_new_purchase twice for the same payment must provision once."""

    async def test_run_twice_provisions_once(self):
        user = make_user()
        plan = make_plan_snapshot()
        payment_id = uuid4()

        api_client = AsyncMock()
        api_client.provision_user.return_value = _make_provision_result()
        subscription_service = AsyncMock()
        redis_client = FakeRedis()

        for _ in range(2):
            await _handle_new_purchase(
                user,
                plan,
                api_client,
                subscription_service,
                redis_client,
                payment_id,
            )

        assert api_client.provision_user.call_count == 1
        assert subscription_service.create.call_count == 1

    async def test_different_payment_id_is_not_blocked(self):
        user = make_user()
        plan = make_plan_snapshot()

        api_client = AsyncMock()
        api_client.provision_user.return_value = _make_provision_result()
        subscription_service = AsyncMock()
        redis_client = FakeRedis()

        for _ in range(2):
            await _handle_new_purchase(
                user,
                plan,
                api_client,
                subscription_service,
                redis_client,
                uuid4(),
            )

        assert api_client.provision_user.call_count == 2

    async def test_failed_attempt_does_not_block_retry(self):
        user = make_user()
        plan = make_plan_snapshot()
        payment_id = uuid4()

        api_client = AsyncMock()
        api_client.provision_user.side_effect = [
            ApiClientError(500, "transient error"),
            _make_provision_result(),
        ]
        subscription_service = AsyncMock()
        redis_client = FakeRedis()

        with pytest.raises(ApiClientError):
            await _handle_new_purchase(
                user, plan, api_client, subscription_service, redis_client, payment_id,
            )

        await _handle_new_purchase(
            user, plan, api_client, subscription_service, redis_client, payment_id,
        )

        assert api_client.provision_user.call_count == 2
        subscription_service.create.assert_called_once()


class TestRenewPurchaseIdempotency:
    """Running _handle_renew_purchase twice must not extend expiry twice."""

    async def test_run_twice_applies_once_no_double_extension(self):
        plan = make_plan_snapshot()
        user = make_user()
        original_expire = datetime_now() + timedelta(days=10)
        subscription = _make_active_subscription(plan, original_expire)
        transaction = _make_transaction(PurchaseType.RENEW, plan)
        redis_client = FakeRedis()

        applied_expire = original_expire + timedelta(days=plan.duration)
        remnawave_service = AsyncMock()
        remnawave_service.updated_user.return_value = SimpleNamespace(
            expire_at=applied_expire,
            subscription_url="https://panel.example.com/sub/renewed",
        )
        subscription_service = AsyncMock()

        for _ in range(2):
            await _handle_renew_purchase(
                user,
                plan,
                subscription,
                transaction,
                remnawave_service,
                subscription_service,
                redis_client,
            )

        assert remnawave_service.updated_user.call_count == 1
        assert subscription_service.update.call_count == 1
        # Must be extended by exactly one duration, not two.
        assert subscription.expire_at == applied_expire

    async def test_different_payment_id_is_not_blocked(self):
        plan = make_plan_snapshot()
        user = make_user()
        original_expire = datetime_now() + timedelta(days=10)
        redis_client = FakeRedis()

        remnawave_service = AsyncMock()
        remnawave_service.updated_user.return_value = SimpleNamespace(
            expire_at=original_expire + timedelta(days=plan.duration),
            subscription_url="https://panel.example.com/sub/renewed",
        )
        subscription_service = AsyncMock()

        for _ in range(2):
            subscription = _make_active_subscription(plan, original_expire)
            transaction = _make_transaction(PurchaseType.RENEW, plan)
            await _handle_renew_purchase(
                user,
                plan,
                subscription,
                transaction,
                remnawave_service,
                subscription_service,
                redis_client,
            )

        assert remnawave_service.updated_user.call_count == 2


class TestChangePurchaseIdempotency:
    """Running _handle_change_purchase twice must mutate Remnawave exactly once."""

    async def test_run_twice_provisions_once(self):
        plan = make_plan_snapshot()
        user = make_user()
        subscription = _make_active_subscription(
            plan, datetime_now() + timedelta(days=5)
        )
        redis_client = FakeRedis()
        payment_id = uuid4()

        remnawave_service = AsyncMock()
        remnawave_service.updated_user.return_value = SimpleNamespace(
            uuid=subscription.user_remna_id,
            status=SubscriptionStatus.ACTIVE,
            expire_at=datetime_now() + timedelta(days=plan.duration + 5),
            subscription_url="https://panel.example.com/sub/changed",
        )
        subscription_service = AsyncMock()

        for _ in range(2):
            await _handle_change_purchase(
                user,
                plan,
                subscription,
                remnawave_service,
                subscription_service,
                redis_client,
                payment_id,
            )

        assert remnawave_service.updated_user.call_count == 1
        assert subscription_service.create.call_count == 1
