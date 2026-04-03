"""Tests for SettingsService -- verifies correct BillingClient calls and Redis cache logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.billing.models import BillingSettings
from src.models.dto.settings import ReferralSettingsDto, SettingsDto
from src.services.settings import SettingsService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_billing_settings(**overrides) -> BillingSettings:
    defaults = {
        "ID": 1,
        "RulesRequired": False,
        "ChannelRequired": False,
        "RulesLink": "https://example.com/rules",
        "ChannelID": -100123,
        "ChannelLink": "@testchannel",
        "AccessMode": "PUBLIC",
        "PurchasesAllowed": True,
        "RegistrationAllowed": True,
        "DefaultCurrency": "XTR",
        "UserNotifications": {"expires_in_3_days": True, "expired": False},
        "SystemNotifications": {"user_registered": True},
        "Referral": {
            "Enable": True,
            "Level": 1,
            "AccrualStrategy": "ON_FIRST_PAYMENT",
            "Reward": {
                "Type": "EXTRA_DAYS",
                "Strategy": "AMOUNT",
                "Config": {1: 5},
            },
        },
    }
    defaults.update(overrides)
    return BillingSettings(**defaults)


def _make_service(
    billing: AsyncMock | None = None,
    redis_client: AsyncMock | None = None,
) -> SettingsService:
    config = MagicMock()
    redis_client = redis_client or AsyncMock()
    redis_repository = MagicMock()
    billing = billing or AsyncMock()
    return SettingsService(
        config=config,
        redis_client=redis_client,
        redis_repository=redis_repository,
        billing=billing,
    )


# ---------------------------------------------------------------------------
# Tests: get()
# ---------------------------------------------------------------------------


class TestSettingsGet:
    """SettingsService.get() delegates to billing.get_settings() with Redis caching."""

    async def test_get_calls_billing_on_cache_miss(self):
        """First call fetches from billing API when Redis cache is empty."""
        billing = AsyncMock()
        billing.get_settings.return_value = _make_billing_settings()
        redis_client = AsyncMock()
        redis_client.get.return_value = None  # cache miss

        svc = _make_service(billing=billing, redis_client=redis_client)
        result = await svc.get()

        billing.get_settings.assert_awaited_once()
        assert isinstance(result, SettingsDto)
        assert result.rules_link.get_secret_value() == "https://example.com/rules"

    async def test_get_uses_in_memory_memo_on_second_call(self):
        """Second call returns memoized result without hitting billing again."""
        billing = AsyncMock()
        billing.get_settings.return_value = _make_billing_settings()
        redis_client = AsyncMock()
        redis_client.get.return_value = None

        svc = _make_service(billing=billing, redis_client=redis_client)
        first = await svc.get()
        second = await svc.get()

        # billing.get_settings should only be called once due to in-memory memo
        billing.get_settings.assert_awaited_once()
        assert first is second


# ---------------------------------------------------------------------------
# Tests: update()
# ---------------------------------------------------------------------------


class TestSettingsUpdate:
    """SettingsService.update() calls billing.update_settings() and clears cache."""

    async def test_update_sends_changed_data_to_billing(self):
        """Changed fields are sent to the billing API."""
        billing = AsyncMock()
        billing.get_settings.return_value = _make_billing_settings()
        billing.update_settings.return_value = _make_billing_settings(
            PurchasesAllowed=False,
        )
        redis_client = AsyncMock()
        redis_client.get.return_value = None

        svc = _make_service(billing=billing, redis_client=redis_client)
        settings = await svc.get()
        settings.purchases_allowed = False
        result = await svc.update(settings)

        billing.update_settings.assert_awaited_once()
        call_args = billing.update_settings.call_args[0][0]
        assert "purchases_allowed" in call_args
        assert call_args["purchases_allowed"] is False
        assert isinstance(result, SettingsDto)

    async def test_update_clears_redis_cache(self):
        """After update, the Redis cache key is deleted."""
        billing = AsyncMock()
        billing.get_settings.return_value = _make_billing_settings()
        billing.update_settings.return_value = _make_billing_settings()
        redis_client = AsyncMock()
        redis_client.get.return_value = None

        svc = _make_service(billing=billing, redis_client=redis_client)
        settings = await svc.get()
        settings.purchases_allowed = False
        await svc.update(settings)

        redis_client.delete.assert_awaited()
        deleted_key = redis_client.delete.call_args[0][0]
        assert "get_settings" in deleted_key

    async def test_update_clears_in_memory_memo(self):
        """After update, the in-memory memo is cleared so next get() re-fetches."""
        billing = AsyncMock()
        billing.get_settings.return_value = _make_billing_settings()
        billing.update_settings.return_value = _make_billing_settings()
        redis_client = AsyncMock()
        redis_client.get.return_value = None

        svc = _make_service(billing=billing, redis_client=redis_client)
        settings = await svc.get()
        settings.purchases_allowed = False
        await svc.update(settings)

        assert svc._settings_memo is None

    async def test_update_no_changes_skips_billing_call(self):
        """If no fields changed, billing API is not called."""
        billing = AsyncMock()
        redis_client = AsyncMock()

        svc = _make_service(billing=billing, redis_client=redis_client)
        # Fresh SettingsDto with no changed_data
        settings = SettingsDto()
        result = await svc.update(settings)

        billing.update_settings.assert_not_awaited()
        assert result is settings


# ---------------------------------------------------------------------------
# Tests: get_referral_settings() / is_referral_enable()
# ---------------------------------------------------------------------------


class TestSettingsReferral:
    """Referral helper methods read from settings."""

    async def test_get_referral_settings_returns_referral_dto(self):
        billing = AsyncMock()
        billing.get_settings.return_value = _make_billing_settings()
        redis_client = AsyncMock()
        redis_client.get.return_value = None

        svc = _make_service(billing=billing, redis_client=redis_client)
        result = await svc.get_referral_settings()

        assert isinstance(result, ReferralSettingsDto)
        assert result.enable is True

    async def test_is_referral_enable_returns_bool(self):
        billing = AsyncMock()
        billing.get_settings.return_value = _make_billing_settings()
        redis_client = AsyncMock()
        redis_client.get.return_value = None

        svc = _make_service(billing=billing, redis_client=redis_client)
        result = await svc.is_referral_enable()

        assert result is True

    async def test_is_referral_enable_false_when_disabled(self):
        billing = AsyncMock()
        billing.get_settings.return_value = _make_billing_settings(
            Referral={"Enable": False, "Level": 1, "AccrualStrategy": "ON_FIRST_PAYMENT"},
        )
        redis_client = AsyncMock()
        redis_client.get.return_value = None

        svc = _make_service(billing=billing, redis_client=redis_client)
        result = await svc.is_referral_enable()

        assert result is False
