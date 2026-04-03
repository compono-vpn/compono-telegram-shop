"""Tests for ReferralService — verifies BillingClient calls and referral linking logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import make_config, make_user

from src.core.enums import (
    Locale,
    ReferralLevel,
    ReferralRewardType,
    UserNotificationType,
)
from src.infrastructure.billing.models import (
    BillingReferral,
    BillingReferralReward,
)
from src.models.dto.referral import ReferralDto
from src.models.dto.user import BaseUserDto
from src.services.referral import ReferralService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_billing_referral(**overrides) -> BillingReferral:
    defaults = dict(
        ID=1,
        ReferrerTelegramID=100,
        ReferredTelegramID=200,
        Level="1",  # BillingReferral.Level is str; converter does ReferralLevel(int(Level))
    )
    defaults.update(overrides)
    br = BillingReferral(**defaults)
    # ReferralLevel is IntEnum so the converter needs an int.
    # Override the str field with an int so ReferralLevel(br.Level) works.
    object.__setattr__(br, "Level", int(br.Level) if br.Level else 0)
    return br


def _make_billing_reward(**overrides) -> BillingReferralReward:
    defaults = dict(
        ID=1,
        ReferralID=1,
        UserTelegramID=100,
        Type="POINTS",
        Amount=10,
        IsIssued=False,
    )
    defaults.update(overrides)
    return BillingReferralReward(**defaults)


def _make_service(
    billing: AsyncMock | None = None,
) -> tuple[ReferralService, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Return (service, billing, user_service, settings_service, notification_service)."""
    billing = billing or AsyncMock()

    config = make_config()
    config.locales = [Locale.EN]
    config.default_locale = Locale.EN
    config.crypt_key.get_secret_value.return_value = "test-secret"

    redis_client = AsyncMock()
    redis_repository = AsyncMock()
    bot = AsyncMock()
    translator_hub = MagicMock()

    user_service = AsyncMock()
    settings_service = AsyncMock()
    notification_service = AsyncMock()

    svc = ReferralService(
        config=config,
        bot=bot,
        redis_client=redis_client,
        redis_repository=redis_repository,
        translator_hub=translator_hub,
        billing=billing,
        user_service=user_service,
        settings_service=settings_service,
        notification_service=notification_service,
    )
    return svc, billing, user_service, settings_service, notification_service


# ---------------------------------------------------------------------------
# create_referral()
# ---------------------------------------------------------------------------


class TestCreateReferral:
    async def test_calls_billing_create_referral(self):
        billing = AsyncMock()
        billing.create_referral.return_value = _make_billing_referral()
        svc, _, _, _, _ = _make_service(billing)

        referrer = make_user(telegram_id=100)
        referred = make_user(telegram_id=200)

        result = await svc.create_referral(referrer, referred, ReferralLevel.FIRST)

        billing.create_referral.assert_awaited_once_with(
            referrer_telegram_id=100,
            referred_telegram_id=200,
            level=1,  # ReferralLevel.FIRST.value == 1
        )
        assert isinstance(result, ReferralDto)
        assert result.level == ReferralLevel.FIRST


# ---------------------------------------------------------------------------
# get_referral_by_referred()
# ---------------------------------------------------------------------------


class TestGetReferralByReferred:
    async def test_returns_referral_when_found(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = _make_billing_referral(
            ReferredTelegramID=200
        )
        svc, _, _, _, _ = _make_service(billing)

        result = await svc.get_referral_by_referred(200)

        billing.get_referral_by_referred.assert_awaited_once_with(200)
        assert result is not None
        assert result.referred.telegram_id == 200

    async def test_returns_none_when_not_found(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = None
        svc, _, _, _, _ = _make_service(billing)

        result = await svc.get_referral_by_referred(999)
        assert result is None


# ---------------------------------------------------------------------------
# get_referrals_by_referrer()
# ---------------------------------------------------------------------------


class TestGetReferralsByReferrer:
    async def test_returns_list(self):
        billing = AsyncMock()
        billing.get_referrals_by_referrer.return_value = [
            _make_billing_referral(ReferredTelegramID=201),
            _make_billing_referral(ReferredTelegramID=202),
        ]
        svc, _, _, _, _ = _make_service(billing)

        result = await svc.get_referrals_by_referrer(100)

        billing.get_referrals_by_referrer.assert_awaited_once_with(100)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# create_reward()
# ---------------------------------------------------------------------------


class TestCreateReward:
    async def test_calls_billing_create_referral_reward(self):
        billing = AsyncMock()
        billing.create_referral_reward.return_value = _make_billing_reward(
            Amount=25, Type="POINTS"
        )
        svc, _, _, _, _ = _make_service(billing)

        result = await svc.create_reward(
            referral_id=1,
            user_telegram_id=100,
            type=ReferralRewardType.POINTS,
            amount=25,
        )

        billing.create_referral_reward.assert_awaited_once_with(
            referral_id=1,
            user_telegram_id=100,
            type="POINTS",
            amount=25,
        )
        assert result.amount == 25
        assert result.type == ReferralRewardType.POINTS


# ---------------------------------------------------------------------------
# mark_reward_as_issued()
# ---------------------------------------------------------------------------


class TestMarkRewardAsIssued:
    async def test_calls_billing_update_referral_reward(self):
        billing = AsyncMock()
        billing.update_referral_reward.return_value = _make_billing_reward(IsIssued=True)
        svc, _, _, _, _ = _make_service(billing)

        await svc.mark_reward_as_issued(42)

        billing.update_referral_reward.assert_awaited_once_with(42, is_issued=True)


# ---------------------------------------------------------------------------
# get_referral_count() / get_reward_count()
# ---------------------------------------------------------------------------


class TestReferralStats:
    async def test_get_referral_count(self):
        billing = AsyncMock()
        billing.get_referral_stats.return_value = {
            "referral_count": 5,
            "reward_count": 3,
            "total_rewards_amount": 100,
        }
        svc, _, _, _, _ = _make_service(billing)

        count = await svc.get_referral_count(100)

        billing.get_referral_stats.assert_awaited_once_with(100)
        assert count == 5

    async def test_get_reward_count(self):
        billing = AsyncMock()
        billing.get_referral_stats.return_value = {
            "referral_count": 5,
            "reward_count": 3,
        }
        svc, _, _, _, _ = _make_service(billing)

        count = await svc.get_reward_count(100)

        billing.get_referral_stats.assert_awaited_once_with(100)
        assert count == 3

    async def test_get_total_rewards_amount(self):
        billing = AsyncMock()
        billing.get_referral_stats.return_value = {
            "total_rewards_amount": 250,
        }
        svc, _, _, _, _ = _make_service(billing)

        amount = await svc.get_total_rewards_amount(100, ReferralRewardType.POINTS)

        billing.get_referral_stats.assert_awaited_once_with(100)
        assert amount == 250

    async def test_returns_zero_when_key_missing(self):
        billing = AsyncMock()
        billing.get_referral_stats.return_value = {}
        svc, _, _, _, _ = _make_service(billing)

        assert await svc.get_referral_count(100) == 0
        assert await svc.get_reward_count(100) == 0
        assert await svc.get_total_rewards_amount(100, ReferralRewardType.POINTS) == 0


# ---------------------------------------------------------------------------
# get_rewards_by_referral()
# ---------------------------------------------------------------------------


class TestGetRewardsByReferral:
    async def test_returns_list(self):
        billing = AsyncMock()
        billing.get_rewards_by_referral.return_value = [
            _make_billing_reward(ID=1),
            _make_billing_reward(ID=2),
        ]
        svc, _, _, _, _ = _make_service(billing)

        result = await svc.get_rewards_by_referral(1)

        billing.get_rewards_by_referral.assert_awaited_once_with(1)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# handle_referral()
# ---------------------------------------------------------------------------


class TestHandleReferral:
    async def test_no_code_does_nothing(self):
        svc, billing, _, _, _ = _make_service()
        user = make_user(telegram_id=200)

        await svc.handle_referral(user, code=None)

        billing.create_referral.assert_not_awaited()

    async def test_strips_ref_prefix(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = None  # no existing referral
        billing.create_referral.return_value = _make_billing_referral()
        svc, _, user_svc, settings_svc, ntf_svc = _make_service(billing)

        referrer = make_user(telegram_id=100)
        user_svc.get_by_referral_code.return_value = referrer
        settings_svc.is_referral_enable.return_value = False

        user = make_user(telegram_id=200)
        await svc.handle_referral(user, code="ref_MYCODE")

        user_svc.get_by_referral_code.assert_awaited_once_with("MYCODE")

    async def test_self_referral_ignored(self):
        svc, billing, user_svc, _, _ = _make_service()

        # Referrer is the same user
        user = make_user(telegram_id=100)
        user_svc.get_by_referral_code.return_value = user

        await svc.handle_referral(user, code="ref_MYCODE")

        billing.create_referral.assert_not_awaited()

    async def test_already_referred_skipped(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = _make_billing_referral()
        svc, _, user_svc, _, _ = _make_service(billing)

        referrer = make_user(telegram_id=100)
        user_svc.get_by_referral_code.return_value = referrer

        user = make_user(telegram_id=200)
        await svc.handle_referral(user, code="ref_CODE")

        billing.create_referral.assert_not_awaited()

    async def test_successful_referral_creates_and_notifies(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = None
        billing.create_referral.return_value = _make_billing_referral()
        svc, _, user_svc, settings_svc, ntf_svc = _make_service(billing)

        referrer = make_user(telegram_id=100, name="Referrer")
        user_svc.get_by_referral_code.return_value = referrer
        settings_svc.is_referral_enable.return_value = True

        user = make_user(telegram_id=200, name="NewUser")
        await svc.handle_referral(user, code="ref_CODE")

        billing.create_referral.assert_awaited_once()
        ntf_svc.notify_user.assert_awaited_once()
        ntf_call = ntf_svc.notify_user.call_args
        assert ntf_call.kwargs["user"] == referrer
        assert ntf_call.kwargs["ntf_type"] == UserNotificationType.REFERRAL_ATTACHED

    async def test_no_notification_when_referral_disabled(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = None
        billing.create_referral.return_value = _make_billing_referral()
        svc, _, user_svc, settings_svc, ntf_svc = _make_service(billing)

        referrer = make_user(telegram_id=100)
        user_svc.get_by_referral_code.return_value = referrer
        settings_svc.is_referral_enable.return_value = False

        user = make_user(telegram_id=200)
        await svc.handle_referral(user, code="ref_CODE")

        billing.create_referral.assert_awaited_once()
        ntf_svc.notify_user.assert_not_awaited()


# ---------------------------------------------------------------------------
# _define_referral_level()
# ---------------------------------------------------------------------------


class TestDefineReferralLevel:
    def test_first_level_when_no_parent(self):
        svc, _, _, _, _ = _make_service()
        assert svc._define_referral_level(None) == ReferralLevel.FIRST

    def test_second_level_when_parent_is_first(self):
        svc, _, _, _, _ = _make_service()
        assert svc._define_referral_level(ReferralLevel.FIRST) == ReferralLevel.SECOND

    def test_capped_at_max_level(self):
        svc, _, _, _, _ = _make_service()
        # SECOND is the max level (value=2), so it should stay at SECOND
        assert svc._define_referral_level(ReferralLevel.SECOND) == ReferralLevel.SECOND
