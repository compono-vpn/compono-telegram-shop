"""Referral days must reach the referrer whether or not they have a subscription."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.core.enums import PlanAvailability, ReferralRewardType, SubscriptionStatus
from src.core.utils.time import datetime_now
from src.infrastructure.taskiq.tasks.referrals import (
    give_referrer_reward_task,
    grant_extra_days,
)
from src.models.dto import PlanDto, ReferralRewardDto
from tests.conftest import make_subscription, make_user
from tests.test_api_client import unwrap_task


def _entry_plan() -> PlanDto:
    return PlanDto(
        id=1,
        order_index=0,
        is_active=True,
        availability=PlanAvailability.ALL,
        name="⚡️ Старт",
        traffic_limit=100,
        device_limit=2,
    )


def _plan_service(plan: PlanDto | None = _entry_plan()) -> AsyncMock:
    svc = AsyncMock()
    svc.get_entry_plan.return_value = plan
    return svc


def _api_client(url: str = "https://sub.example/abc") -> AsyncMock:
    client = AsyncMock()
    client.provision_user.return_value = SimpleNamespace(
        remnawave_user_id=str(uuid4()),
        status=SubscriptionStatus.ACTIVE.value,
        expire_at=(datetime_now() + timedelta(days=14)).isoformat(),
        subscription_url=url,
    )
    return client


def _remnawave(url: str = "https://sub.example/upgraded") -> AsyncMock:
    svc = AsyncMock()
    svc.updated_user.return_value = SimpleNamespace(
        uuid=uuid4(),
        status=SubscriptionStatus.ACTIVE,
        expire_at=datetime_now() + timedelta(days=14),
        subscription_url=url,
    )
    return svc


async def _grant(
    subscription, plan_service=None, api_client=None, remnawave=None, days=14, billing=None
):
    sub_svc = AsyncMock()
    api = api_client or _api_client()
    remna = remnawave or _remnawave()
    billing = billing or AsyncMock()
    granted, url = await grant_extra_days(
        user=make_user(telegram_id=100),
        days=days,
        subscription=subscription,
        plan_service=plan_service or _plan_service(),
        api_client=api,
        subscription_service=sub_svc,
        remnawave_service=remna,
        billing=billing,
    )
    return granted, url, sub_svc, api, remna, billing


class TestPaidSubscription:
    """Billing derives expiry from transactions, so the days must land as a
    MANUAL_GRANT transaction; writing expire_at directly is ignored by
    billing's GetCurrent and later overwritten (it cost a referrer 7 days)."""

    async def test_grants_the_days_through_billing_on_the_current_plan(self):
        subscription = make_subscription(active=True, plan_id=2)
        original = subscription.expire_at

        granted, url, sub_svc, api, remna, billing = await _grant(subscription)

        assert (granted, url) == (True, None)
        billing.grant_subscription.assert_awaited_once_with(
            telegram_id=100, plan_id=2, duration_days=14, reason="referral_reward"
        )
        assert subscription.expire_at == original
        sub_svc.update.assert_not_awaited()
        remna.updated_user.assert_not_awaited()
        sub_svc.create.assert_not_awaited()
        api.provision_user.assert_not_awaited()
        sub_svc.clear_subscription_cache.assert_awaited_once_with(subscription.id, 100)

    async def test_expired_paid_subscription_is_also_granted_through_billing(self):
        subscription = make_subscription(active=False, plan_id=3)

        granted, _, sub_svc, _, _, billing = await _grant(subscription, days=30)

        assert granted is True
        billing.grant_subscription.assert_awaited_once_with(
            telegram_id=100, plan_id=3, duration_days=30, reason="referral_reward"
        )
        sub_svc.update.assert_not_awaited()


class TestNoSubscription:
    async def test_provisions_entry_plan_for_the_reward_days(self):
        granted, url, sub_svc, api, _, _ = await _grant(None)

        assert granted is True
        assert url == "https://sub.example/abc"
        api.provision_user.assert_awaited_once()
        plan = api.provision_user.await_args.kwargs["plan"]
        assert plan.name == "⚡️ Старт"
        assert plan.duration == 14
        sub_svc.create.assert_awaited_once()
        assert sub_svc.create.await_args.args[1].is_trial is False

    async def test_reports_failure_without_provisioning_when_no_plan_exists(self):
        granted, url, sub_svc, api, _, _ = await _grant(None, plan_service=_plan_service(None))

        assert (granted, url) == (False, None)
        api.provision_user.assert_not_awaited()
        sub_svc.create.assert_not_awaited()


class TestTrialSubscription:
    async def test_upgrades_trial_to_the_entry_plan(self):
        trial = make_subscription(active=True, is_trial=True)

        granted, url, sub_svc, api, remna, billing = await _grant(trial)

        assert granted is True
        assert url == "https://sub.example/upgraded"
        assert trial.status == SubscriptionStatus.DISABLED
        remna.updated_user.assert_awaited_once()
        assert remna.updated_user.await_args.kwargs["reset_traffic"] is True
        sub_svc.create.assert_awaited_once()
        assert sub_svc.create.await_args.args[1].plan.name == "⚡️ Старт"
        api.provision_user.assert_not_awaited()
        billing.grant_subscription.assert_not_awaited()

    async def test_carries_the_remaining_trial_days_into_the_reward_subscription(self):
        trial = make_subscription(active=True, is_trial=True)
        remaining = (trial.expire_at - datetime_now()).total_seconds() / 86400

        _, _, _, _, remna, _ = await _grant(trial)

        proposed = remna.updated_user.await_args.kwargs["subscription"]
        expected = datetime_now() + timedelta(days=14 + remaining)
        assert abs((proposed.expire_at - expected).total_seconds()) < 5


class TestGiveReferrerRewardTask:
    async def _run(self, subscription, reward_amount=14):
        user_service = AsyncMock()
        user_service.get.return_value = make_user(telegram_id=100)
        subscription_service = AsyncMock()
        subscription_service.get_current.return_value = subscription
        notification_service = AsyncMock()
        referral_service = AsyncMock()
        config = MagicMock()
        config.remnawave.sub_public_domain = "getfastlink.online"
        config.website_url = "https://componovpn.com"

        await unwrap_task(give_referrer_reward_task)(
            user_telegram_id=100,
            reward=ReferralRewardDto(
                id=7,
                referral_id=1,
                user_telegram_id=100,
                type=ReferralRewardType.EXTRA_DAYS,
                amount=reward_amount,
                is_issued=False,
            ),
            referred_name="Friend",
            config=config,
            user_service=user_service,
            plan_service=_plan_service(),
            api_client=_api_client(),
            subscription_service=subscription_service,
            remnawave_service=_remnawave(),
            notification_service=notification_service,
            referral_service=referral_service,
            billing=AsyncMock(),
        )
        return notification_service, referral_service

    async def test_offers_a_connect_link_when_access_was_newly_provisioned(self):
        ntf, referral_service = await self._run(subscription=None)

        payload = ntf.notify_user.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-event-user-referral-reward-subscription"
        assert payload.reply_markup is not None
        referral_service.mark_reward_as_issued.assert_awaited_once_with(7)

    async def test_keeps_the_plain_receipt_when_an_existing_subscription_was_extended(self):
        ntf, referral_service = await self._run(subscription=make_subscription(active=True))

        payload = ntf.notify_user.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-event-user-referral-reward"
        assert payload.reply_markup is None
        referral_service.mark_reward_as_issued.assert_awaited_once_with(7)

    async def test_hands_off_to_the_next_pending_reward_after_issuing(self):
        _, referral_service = await self._run(subscription=make_subscription(active=True))

        referral_service.issue_pending_rewards.assert_awaited_once_with(100)
