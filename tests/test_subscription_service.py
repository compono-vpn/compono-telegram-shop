"""Tests for SubscriptionService — verifies BillingClient calls and DTO mapping."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.core.enums import SubscriptionStatus
from src.infrastructure.billing.models import (
    BillingPlanSnapshot,
    BillingSubscription,
)
from src.models.dto import SubscriptionDto
from src.services.subscription import SubscriptionService

from tests.conftest import make_plan_snapshot, make_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_billing_subscription(
    sub_id: int = 1,
    telegram_id: int = 100,
    status: str = "ACTIVE",
    url: str = "https://panel.example.com/sub/abc123",
) -> BillingSubscription:
    return BillingSubscription(
        ID=sub_id,
        UserRemnaID=str(uuid4()),
        UserTelegramID=telegram_id,
        Status=status,
        IsTrial=False,
        TrafficLimit=300,
        DeviceLimit=6,
        TrafficLimitStrategy="MONTH",
        Tag=None,
        InternalSquads=[],
        ExternalSquad=None,
        ExpireAt=datetime.now(tz=timezone.utc) + timedelta(days=30),
        URL=url,
        Plan=BillingPlanSnapshot(
            id=2, name="Pro", type="BOTH", traffic_limit=300, device_limit=6,
            duration=30, traffic_limit_strategy="MONTH",
        ),
        CreatedAt=datetime.now(tz=timezone.utc),
        UpdatedAt=datetime.now(tz=timezone.utc),
    )


def _make_service(
    billing: AsyncMock | None = None,
    user_service: AsyncMock | None = None,
    sub_public_domain: str = "",
) -> SubscriptionService:
    billing = billing or AsyncMock()
    user_service = user_service or AsyncMock()
    config = MagicMock()
    config.remnawave.sub_public_domain = sub_public_domain
    bot = MagicMock()
    redis_client = AsyncMock()
    redis_repository = MagicMock()
    translator_hub = MagicMock()

    return SubscriptionService(
        config=config,
        bot=bot,
        redis_client=redis_client,
        redis_repository=redis_repository,
        translator_hub=translator_hub,
        billing=billing,
        user_service=user_service,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.asyncio
    async def test_sends_pascal_case_keys_with_internal_squads(self):
        """Bug: create() sent snake_case keys but Go's Subscription struct
        expects PascalCase (no json tags). InternalSquads arrived as null,
        violating the DB NOT NULL constraint."""
        billing = AsyncMock()
        user_service = AsyncMock()
        billing_sub = _make_billing_subscription(sub_id=10, telegram_id=100)
        billing.create_subscription.return_value = billing_sub

        svc = _make_service(billing=billing, user_service=user_service)
        user = make_user(telegram_id=100)

        squad_id = uuid4()
        sub_input = SubscriptionDto(
            user_remna_id=uuid4(),
            status=SubscriptionStatus.ACTIVE,
            traffic_limit=300,
            device_limit=6,
            traffic_limit_strategy="MONTH",
            internal_squads=[squad_id],
            external_squad=None,
            expire_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
            url="https://panel.example.com/sub/new",
            plan=make_plan_snapshot(),
        )

        await svc.create(user, sub_input)

        data = billing.create_subscription.call_args[0][0]
        # Must use PascalCase keys for Go's encoding/json
        assert "InternalSquads" in data, f"Expected PascalCase key 'InternalSquads', got keys: {list(data.keys())}"
        assert data["InternalSquads"] == [str(squad_id)]
        assert "UserTelegramID" in data
        assert "TrafficLimit" in data
        # snake_case keys must NOT be present at top level
        assert "internal_squads" not in data
        assert "user_telegram_id" not in data

    @pytest.mark.asyncio
    async def test_calls_billing_and_sets_current_subscription(self):
        billing = AsyncMock()
        user_service = AsyncMock()
        billing_sub = _make_billing_subscription(sub_id=10, telegram_id=100)
        billing.create_subscription.return_value = billing_sub

        svc = _make_service(billing=billing, user_service=user_service)
        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()

        sub_input = SubscriptionDto(
            user_remna_id=uuid4(),
            status=SubscriptionStatus.ACTIVE,
            traffic_limit=300,
            device_limit=6,
            traffic_limit_strategy="MONTH",
            internal_squads=[],
            external_squad=None,
            expire_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
            url="https://panel.example.com/sub/new",
            plan=plan,
        )

        result = await svc.create(user, sub_input)

        billing.create_subscription.assert_awaited_once()
        user_service.set_current_subscription.assert_awaited_once_with(
            telegram_id=100, subscription_id=10,
        )
        assert isinstance(result, SubscriptionDto)
        assert result.id == 10

    @pytest.mark.asyncio
    async def test_clears_cache_after_create(self):
        billing = AsyncMock()
        user_service = AsyncMock()
        billing_sub = _make_billing_subscription(sub_id=5, telegram_id=200)
        billing.create_subscription.return_value = billing_sub

        redis_client = AsyncMock()
        svc = _make_service(billing=billing, user_service=user_service)
        svc.redis_client = redis_client

        user = make_user(telegram_id=200)
        sub_input = SubscriptionDto(
            user_remna_id=uuid4(),
            status=SubscriptionStatus.ACTIVE,
            traffic_limit=300,
            device_limit=6,
            traffic_limit_strategy="MONTH",
            internal_squads=[],
            external_squad=None,
            expire_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
            url="https://panel.example.com/sub/new",
            plan=make_plan_snapshot(),
        )

        await svc.create(user, sub_input)

        redis_client.delete.assert_awaited_once()


class TestGet:
    @pytest.mark.asyncio
    async def test_returns_dto_when_found(self):
        billing = AsyncMock()
        billing_sub = _make_billing_subscription(sub_id=7)
        billing.get_subscription.return_value = billing_sub

        svc = _make_service(billing=billing)
        # Call the underlying method directly to bypass redis_cache decorator
        result = await svc.get.__wrapped__(svc, 7)

        billing.get_subscription.assert_awaited_once_with(7)
        assert isinstance(result, SubscriptionDto)
        assert result.id == 7

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        billing = AsyncMock()
        billing.get_subscription.return_value = None

        svc = _make_service(billing=billing)
        result = await svc.get.__wrapped__(svc, 999)

        assert result is None

    @pytest.mark.asyncio
    async def test_rewrites_sub_url_when_domain_configured(self):
        billing = AsyncMock()
        billing_sub = _make_billing_subscription(url="https://panel.example.com/sub/abc123")
        billing.get_subscription.return_value = billing_sub

        svc = _make_service(billing=billing, sub_public_domain="componovpn.com")
        result = await svc.get.__wrapped__(svc, 1)

        assert "componovpn.com" in result.url
        assert "panel.example.com" not in result.url


class TestUpdate:
    @pytest.mark.asyncio
    async def test_calls_billing_update(self):
        billing = AsyncMock()
        user_service = AsyncMock()
        billing_sub = _make_billing_subscription(sub_id=3, telegram_id=100)
        billing.update_subscription.return_value = billing_sub

        svc = _make_service(billing=billing, user_service=user_service)
        svc.redis_client = AsyncMock()

        sub = SubscriptionDto(
            id=3,
            user_remna_id=uuid4(),
            status=SubscriptionStatus.ACTIVE,
            traffic_limit=300,
            device_limit=6,
            traffic_limit_strategy="MONTH",
            internal_squads=[],
            external_squad=None,
            expire_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
            url="https://panel.example.com/sub/abc",
            plan=make_plan_snapshot(),
        )
        # Trigger a change
        sub.status = SubscriptionStatus.EXPIRED

        result = await svc.update(sub)

        billing.update_subscription.assert_awaited_once()
        call_args = billing.update_subscription.call_args
        assert call_args[0][0] == 3  # subscription_id
        assert isinstance(result, SubscriptionDto)

    @pytest.mark.asyncio
    async def test_clears_caches_after_update(self):
        billing = AsyncMock()
        user_service = AsyncMock()
        billing_sub = _make_billing_subscription(sub_id=3, telegram_id=100)
        billing.update_subscription.return_value = billing_sub

        redis_client = AsyncMock()
        svc = _make_service(billing=billing, user_service=user_service)
        svc.redis_client = redis_client

        sub = SubscriptionDto(
            id=3,
            user_remna_id=uuid4(),
            status=SubscriptionStatus.ACTIVE,
            traffic_limit=300,
            device_limit=6,
            traffic_limit_strategy="MONTH",
            internal_squads=[],
            external_squad=None,
            expire_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
            url="https://panel.example.com/sub/abc",
            plan=make_plan_snapshot(),
        )

        await svc.update(sub)

        redis_client.delete.assert_awaited_once()
        user_service.clear_user_cache.assert_awaited_once_with(100)


class TestGetAll:
    @pytest.mark.asyncio
    async def test_returns_list_of_dtos(self):
        billing = AsyncMock()
        billing.list_all_subscriptions.return_value = [
            _make_billing_subscription(sub_id=1),
            _make_billing_subscription(sub_id=2),
        ]

        svc = _make_service(billing=billing)
        result = await svc.get_all()

        billing.list_all_subscriptions.assert_awaited_once()
        assert len(result) == 2
        assert all(isinstance(r, SubscriptionDto) for r in result)

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        billing = AsyncMock()
        billing.list_all_subscriptions.return_value = []

        svc = _make_service(billing=billing)
        result = await svc.get_all()

        assert result == []


class TestGetCurrent:
    @pytest.mark.asyncio
    async def test_returns_dto_when_found(self):
        billing = AsyncMock()
        billing_sub = _make_billing_subscription(telegram_id=42)
        billing.get_current_subscription.return_value = billing_sub

        svc = _make_service(billing=billing)
        result = await svc.get_current.__wrapped__(svc, 42)

        billing.get_current_subscription.assert_awaited_once_with(42)
        assert isinstance(result, SubscriptionDto)

    @pytest.mark.asyncio
    async def test_returns_none_when_no_active(self):
        billing = AsyncMock()
        billing.get_current_subscription.return_value = None

        svc = _make_service(billing=billing)
        result = await svc.get_current.__wrapped__(svc, 42)

        assert result is None

    @pytest.mark.asyncio
    async def test_rewrites_url_when_domain_set(self):
        billing = AsyncMock()
        billing_sub = _make_billing_subscription(url="https://panel.example.com/sub/token")
        billing.get_current_subscription.return_value = billing_sub

        svc = _make_service(billing=billing, sub_public_domain="public.vpn.com")
        result = await svc.get_current.__wrapped__(svc, 42)

        assert "public.vpn.com" in result.url


class TestHasUsedTrial:
    @pytest.mark.asyncio
    async def test_delegates_to_billing(self):
        billing = AsyncMock()
        billing.has_used_trial.return_value = True

        svc = _make_service(billing=billing)
        result = await svc.has_used_trial.__wrapped__(svc, 42)

        billing.has_used_trial.assert_awaited_once_with(42)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_used(self):
        billing = AsyncMock()
        billing.has_used_trial.return_value = False

        svc = _make_service(billing=billing)
        result = await svc.has_used_trial.__wrapped__(svc, 42)

        assert result is False


class TestGetAllByUser:
    @pytest.mark.asyncio
    async def test_calls_list_subscriptions_by_user(self):
        billing = AsyncMock()
        billing.list_subscriptions_by_user.return_value = [
            _make_billing_subscription(telegram_id=55),
        ]

        svc = _make_service(billing=billing)
        result = await svc.get_all_by_user(55)

        billing.list_subscriptions_by_user.assert_awaited_once_with(55)
        assert len(result) == 1


class TestRewriteSubUrl:
    def test_rewrites_netloc(self):
        svc = _make_service(sub_public_domain="my-domain.com")
        sub = SubscriptionDto(
            user_remna_id=uuid4(),
            status=SubscriptionStatus.ACTIVE,
            traffic_limit=300,
            device_limit=6,
            traffic_limit_strategy="MONTH",
            internal_squads=[],
            external_squad=None,
            expire_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
            url="https://panel.internal.com/sub/token123",
            plan=make_plan_snapshot(),
        )

        result = svc._rewrite_sub_url(sub)

        assert result.url == "https://my-domain.com/sub/token123"

    def test_returns_none_for_none(self):
        svc = _make_service(sub_public_domain="my-domain.com")
        assert svc._rewrite_sub_url(None) is None

    def test_noop_when_no_domain_configured(self):
        svc = _make_service(sub_public_domain="")
        sub = SubscriptionDto(
            user_remna_id=uuid4(),
            status=SubscriptionStatus.ACTIVE,
            traffic_limit=300,
            device_limit=6,
            traffic_limit_strategy="MONTH",
            internal_squads=[],
            external_squad=None,
            expire_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
            url="https://panel.internal.com/sub/token123",
            plan=make_plan_snapshot(),
        )

        result = svc._rewrite_sub_url(sub)

        assert result.url == "https://panel.internal.com/sub/token123"
