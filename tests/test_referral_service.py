"""Tests for ReferralService — verifies BillingClient calls and referral linking logic."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.core.enums import (
    Currency,
    Locale,
    PaymentGatewayType,
    PurchaseType,
    ReferralLevel,
    ReferralRewardType,
    TransactionStatus,
    UserNotificationType,
)
from src.infrastructure.billing.models import (
    BillingReferral,
    BillingReferralReward,
)
from src.models.dto.referral import ReferralDto
from src.models.dto.settings import ReferralSettingsDto
from src.models.dto.transaction import PriceDetailsDto, TransactionDto
from src.services.referral import ReferralService
from tests.conftest import make_config, make_plan_snapshot, make_subscription, make_user

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_billing_referral(**overrides) -> BillingReferral:
    defaults = {
        "ID": 1,
        "ReferrerTelegramID": 100,
        "ReferredTelegramID": 200,
        "Level": "1",  # BillingReferral.Level is str; converter does ReferralLevel(int(Level))
    }
    defaults.update(overrides)
    br = BillingReferral(**defaults)
    # ReferralLevel is IntEnum so the converter needs an int.
    # Override the str field with an int so ReferralLevel(br.Level) works.
    object.__setattr__(br, "Level", int(br.Level) if br.Level else 0)
    return br


def _make_billing_reward(**overrides) -> BillingReferralReward:
    defaults = {
        "ID": 1,
        "ReferralID": 1,
        "UserTelegramID": 100,
        "Type": "POINTS",
        "Amount": 10,
        "IsIssued": False,
    }
    defaults.update(overrides)
    return BillingReferralReward(**defaults)


def _make_transaction(duration_days: int) -> TransactionDto:
    plan = make_plan_snapshot()
    plan.duration = duration_days
    return TransactionDto(
        payment_id=uuid4(),
        status=TransactionStatus.COMPLETED,
        purchase_type=PurchaseType.NEW,
        gateway_type=PaymentGatewayType.YOOKASSA,
        pricing=PriceDetailsDto(original_amount=100, final_amount=100),
        currency=Currency.RUB,
        plan=plan,
        user=make_user(telegram_id=200, name="NewUser"),
    )


def _make_service(
    billing: AsyncMock | None = None,
) -> tuple[ReferralService, AsyncMock, AsyncMock, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Return (service, billing, user_service, settings_service, notification_service,
    subscription_service, remnawave_service)."""
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
    settings_service.get_referral_settings.return_value = ReferralSettingsDto()
    notification_service = AsyncMock()
    subscription_service = AsyncMock()
    subscription_service.get_all_by_user.return_value = []
    subscription_service.get_current.return_value = None
    remnawave_service = AsyncMock()

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
        subscription_service=subscription_service,
        remnawave_service=remnawave_service,
    )
    return (
        svc,
        billing,
        user_service,
        settings_service,
        notification_service,
        subscription_service,
        remnawave_service,
    )


# ---------------------------------------------------------------------------
# create_referral()
# ---------------------------------------------------------------------------


class TestCreateReferral:
    async def test_calls_billing_create_referral(self):
        billing = AsyncMock()
        billing.create_referral.return_value = _make_billing_referral()
        svc, _, _, _, _, _, _ = _make_service(billing)

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
        svc, _, _, _, _, _, _ = _make_service(billing)

        result = await svc.get_referral_by_referred(200)

        billing.get_referral_by_referred.assert_awaited_once_with(200)
        assert result is not None
        assert result.referred.telegram_id == 200

    async def test_returns_none_when_not_found(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = None
        svc, _, _, _, _, _, _ = _make_service(billing)

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
        svc, _, _, _, _, _, _ = _make_service(billing)

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
        svc, _, _, _, _, _, _ = _make_service(billing)

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
        svc, _, _, _, _, _, _ = _make_service(billing)

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
        svc, _, _, _, _, _, _ = _make_service(billing)

        count = await svc.get_referral_count(100)

        billing.get_referral_stats.assert_awaited_once_with(100)
        assert count == 5

    async def test_get_reward_count(self):
        billing = AsyncMock()
        billing.get_referral_stats.return_value = {
            "referral_count": 5,
            "reward_count": 3,
        }
        svc, _, _, _, _, _, _ = _make_service(billing)

        count = await svc.get_reward_count(100)

        billing.get_referral_stats.assert_awaited_once_with(100)
        assert count == 3

    async def test_get_total_rewards_amount(self):
        billing = AsyncMock()
        billing.get_referral_stats.return_value = {
            "total_rewards_amount": 250,
        }
        svc, _, _, _, _, _, _ = _make_service(billing)

        amount = await svc.get_total_rewards_amount(100, ReferralRewardType.POINTS)

        billing.get_referral_stats.assert_awaited_once_with(100)
        assert amount == 250

    async def test_returns_zero_when_key_missing(self):
        billing = AsyncMock()
        billing.get_referral_stats.return_value = {}
        svc, _, _, _, _, _, _ = _make_service(billing)

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
        svc, _, _, _, _, _, _ = _make_service(billing)

        result = await svc.get_rewards_by_referral(1)

        billing.get_rewards_by_referral.assert_awaited_once_with(1)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# handle_referral()
# ---------------------------------------------------------------------------


class TestHandleReferral:
    async def test_no_code_does_nothing(self):
        svc, billing, _, _, _, _, _ = _make_service()
        user = make_user(telegram_id=200)

        await svc.handle_referral(user, code=None)

        billing.create_referral.assert_not_awaited()

    async def test_strips_ref_prefix(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = None  # no existing referral
        billing.create_referral.return_value = _make_billing_referral()
        svc, _, user_svc, settings_svc, ntf_svc, _, _ = _make_service(billing)

        referrer = make_user(telegram_id=100)
        user_svc.get_by_referral_code.return_value = referrer
        settings_svc.is_referral_enable.return_value = False

        user = make_user(telegram_id=200)
        await svc.handle_referral(user, code="ref_MYCODE")

        user_svc.get_by_referral_code.assert_awaited_once_with("MYCODE")

    async def test_self_referral_ignored(self):
        svc, billing, user_svc, _, _, _, _ = _make_service()

        # Referrer is the same user
        user = make_user(telegram_id=100)
        user_svc.get_by_referral_code.return_value = user

        await svc.handle_referral(user, code="ref_MYCODE")

        billing.create_referral.assert_not_awaited()

    async def test_already_referred_skipped(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = _make_billing_referral()
        svc, _, user_svc, _, _, _, _ = _make_service(billing)

        referrer = make_user(telegram_id=100)
        user_svc.get_by_referral_code.return_value = referrer

        user = make_user(telegram_id=200)
        await svc.handle_referral(user, code="ref_CODE")

        billing.create_referral.assert_not_awaited()

    async def test_successful_referral_creates_and_notifies(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = None
        billing.create_referral.return_value = _make_billing_referral()
        svc, _, user_svc, settings_svc, ntf_svc, _, _ = _make_service(billing)

        referrer = make_user(telegram_id=100, name="Referrer")
        user_svc.get_by_referral_code.return_value = referrer

        user = make_user(telegram_id=200, name="NewUser")
        await svc.handle_referral(user, code="ref_CODE")

        billing.create_referral.assert_awaited_once()
        assert ntf_svc.notify_user.await_count == 2
        first_call = ntf_svc.notify_user.await_args_list[0]
        second_call = ntf_svc.notify_user.await_args_list[1]
        assert first_call.kwargs["user"] == referrer
        assert first_call.kwargs["ntf_type"] == UserNotificationType.REFERRAL_ATTACHED
        assert second_call.kwargs["user"] == user
        assert "ntf_type" not in second_call.kwargs

    async def test_successful_referral_applies_invitee_purchase_discount(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = None
        billing.create_referral.return_value = _make_billing_referral()
        svc, _, user_svc, _, _, _, _ = _make_service(billing)

        referrer = make_user(telegram_id=100)
        user_svc.get_by_referral_code.return_value = referrer

        user = make_user(telegram_id=200)
        await svc.handle_referral(user, code="ref_CODE")

        assert user.purchase_discount == 10
        assert user.purchase_discount_max_days == 365
        user_svc.update.assert_awaited_once_with(user)

    async def test_invitee_discount_keeps_larger_existing_discount(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = None
        billing.create_referral.return_value = _make_billing_referral()
        svc, _, user_svc, _, _, _, _ = _make_service(billing)

        referrer = make_user(telegram_id=100)
        user_svc.get_by_referral_code.return_value = referrer

        user = make_user(telegram_id=200)
        user.purchase_discount = 20
        user.purchase_discount_max_days = 100
        await svc.handle_referral(user, code="ref_CODE")

        assert user.purchase_discount == 20
        assert user.purchase_discount_max_days == 365
        user_svc.update.assert_awaited_once_with(user)

    async def test_no_invitee_discount_when_already_paid_before(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = None
        billing.create_referral.return_value = _make_billing_referral()
        svc, _, user_svc, _, _, subscription_svc, _ = _make_service(billing)
        subscription_svc.get_all_by_user.return_value = [
            make_subscription(active=False),
        ]

        referrer = make_user(telegram_id=100)
        user_svc.get_by_referral_code.return_value = referrer

        user = make_user(telegram_id=200)
        await svc.handle_referral(user, code="ref_CODE")

        assert user.purchase_discount == 0
        assert user.purchase_discount_max_days == 0
        user_svc.update.assert_not_awaited()

    async def test_no_notification_when_referral_disabled(self):
        billing = AsyncMock()
        billing.get_referral_by_referred.return_value = None
        billing.create_referral.return_value = _make_billing_referral()
        svc, _, user_svc, settings_svc, ntf_svc, _, _ = _make_service(billing)

        referrer = make_user(telegram_id=100)
        user_svc.get_by_referral_code.return_value = referrer
        settings_svc.get_referral_settings.return_value = ReferralSettingsDto(enable=False)

        user = make_user(telegram_id=200)
        await svc.handle_referral(user, code="ref_CODE")

        billing.create_referral.assert_awaited_once()
        ntf_svc.notify_user.assert_not_awaited()


class TestReferralCampaignReward:
    def test_regular_first_payment_reward_is_14_days(self):
        settings = ReferralSettingsDto()
        amount = ReferralService._compute_reward_amount(
            settings.reward,
            ReferralRewardType.EXTRA_DAYS,
            ReferralLevel.FIRST,
            _make_transaction(duration_days=30),
        )

        assert amount == 14

    def test_long_first_payment_reward_is_30_days(self):
        settings = ReferralSettingsDto()
        amount = ReferralService._compute_reward_amount(
            settings.reward,
            ReferralRewardType.EXTRA_DAYS,
            ReferralLevel.FIRST,
            _make_transaction(duration_days=90),
        )

        assert amount == 30


# ---------------------------------------------------------------------------
# _define_referral_level()
# ---------------------------------------------------------------------------


class TestDefineReferralLevel:
    def test_first_level_when_no_parent(self):
        svc, _, _, _, _, _, _ = _make_service()
        assert svc._define_referral_level(None) == ReferralLevel.FIRST

    def test_second_level_when_parent_is_first(self):
        svc, _, _, _, _, _, _ = _make_service()
        assert svc._define_referral_level(ReferralLevel.FIRST) == ReferralLevel.SECOND

    def test_capped_at_max_level(self):
        svc, _, _, _, _, _, _ = _make_service()
        # SECOND is the max level (value=2), so it should stay at SECOND
        assert svc._define_referral_level(ReferralLevel.SECOND) == ReferralLevel.SECOND


# ---------------------------------------------------------------------------
# flush_pending_rewards()
# ---------------------------------------------------------------------------


class TestFlushPendingRewards:
    async def test_applies_pending_extra_days_reward_to_current_subscription(self):
        billing = AsyncMock()
        svc, _, user_svc, _, ntf_svc, sub_svc, remna_svc = _make_service(billing)

        user = make_user(telegram_id=100)
        user_svc.get.return_value = user

        subscription = make_subscription(active=True)
        original_expire_at = subscription.expire_at
        sub_svc.get_current.return_value = subscription

        pending_reward = _make_billing_reward(ID=1, Type="EXTRA_DAYS", Amount=14, IsIssued=False)
        billing.list_referral_rewards.return_value = [pending_reward]

        await svc.flush_pending_rewards(100)

        sub_svc.update.assert_awaited_once()
        updated_subscription = sub_svc.update.await_args.args[0]
        assert updated_subscription.expire_at == original_expire_at + timedelta(days=14)

        remna_svc.updated_user.assert_awaited_once()
        remna_call = remna_svc.updated_user.await_args
        assert remna_call.kwargs["user"] == user
        assert remna_call.kwargs["uuid"] == subscription.user_remna_id
        assert remna_call.kwargs["subscription"] == updated_subscription

        billing.update_referral_reward.assert_awaited_once_with(1, is_issued=True)
        ntf_svc.notify_user.assert_awaited_once()

    async def test_applies_multiple_pending_rewards_chained(self):
        billing = AsyncMock()
        svc, _, user_svc, _, _, sub_svc, _ = _make_service(billing)

        user = make_user(telegram_id=100)
        user_svc.get.return_value = user

        subscription = make_subscription(active=True)
        original_expire_at = subscription.expire_at
        sub_svc.get_current.return_value = subscription

        billing.list_referral_rewards.return_value = [
            _make_billing_reward(ID=1, Type="EXTRA_DAYS", Amount=14, IsIssued=False),
            _make_billing_reward(ID=2, Type="EXTRA_DAYS", Amount=30, IsIssued=False),
        ]

        await svc.flush_pending_rewards(100)

        assert sub_svc.update.await_count == 2
        final_subscription = sub_svc.update.await_args.args[0]
        assert final_subscription.expire_at == original_expire_at + timedelta(days=44)
        assert billing.update_referral_reward.await_count == 2

    async def test_skips_already_issued_rewards(self):
        billing = AsyncMock()
        svc, _, user_svc, _, _, sub_svc, _ = _make_service(billing)

        user_svc.get.return_value = make_user(telegram_id=100)
        sub_svc.get_current.return_value = make_subscription(active=True)

        billing.list_referral_rewards.return_value = [
            _make_billing_reward(ID=1, Type="EXTRA_DAYS", Amount=14, IsIssued=True),
        ]

        await svc.flush_pending_rewards(100)

        sub_svc.update.assert_not_awaited()
        billing.update_referral_reward.assert_not_awaited()

    async def test_skips_points_type_rewards(self):
        billing = AsyncMock()
        svc, _, user_svc, _, _, sub_svc, _ = _make_service(billing)

        user_svc.get.return_value = make_user(telegram_id=100)
        sub_svc.get_current.return_value = make_subscription(active=True)

        billing.list_referral_rewards.return_value = [
            _make_billing_reward(ID=1, Type="POINTS", Amount=10, IsIssued=False),
        ]

        await svc.flush_pending_rewards(100)

        sub_svc.update.assert_not_awaited()
        billing.update_referral_reward.assert_not_awaited()

    async def test_noop_when_no_active_subscription(self):
        billing = AsyncMock()
        svc, _, _, _, _, sub_svc, _ = _make_service(billing)

        sub_svc.get_current.return_value = None

        await svc.flush_pending_rewards(100)

        billing.list_referral_rewards.assert_not_awaited()

    async def test_noop_when_subscription_is_trial(self):
        billing = AsyncMock()
        svc, _, _, _, _, sub_svc, _ = _make_service(billing)

        trial_subscription = make_subscription(active=True)
        trial_subscription.is_trial = True
        sub_svc.get_current.return_value = trial_subscription

        await svc.flush_pending_rewards(100)

        billing.list_referral_rewards.assert_not_awaited()

    async def test_noop_when_no_pending_rewards(self):
        billing = AsyncMock()
        svc, _, user_svc, _, _, sub_svc, _ = _make_service(billing)

        user_svc.get.return_value = make_user(telegram_id=100)
        sub_svc.get_current.return_value = make_subscription(active=True)
        billing.list_referral_rewards.return_value = []

        await svc.flush_pending_rewards(100)

        sub_svc.update.assert_not_awaited()
        billing.update_referral_reward.assert_not_awaited()
