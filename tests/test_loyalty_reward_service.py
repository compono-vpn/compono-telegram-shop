from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from src.core.enums import Locale, UserRole
from src.services.loyalty_reward import (
    LOYALTY_EXTRA_DAYS,
    LOYALTY_PERSONAL_DISCOUNT,
    LoyaltyRewardService,
)
from tests.conftest import make_config, make_subscription, make_user


def _make_service() -> tuple[
    LoyaltyRewardService,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
]:
    config = make_config()
    config.locales = [Locale.EN]
    config.default_locale = Locale.EN

    redis_client = AsyncMock()
    redis_repository = AsyncMock()
    bot = AsyncMock()
    translator_hub = MagicMock()

    user_service = AsyncMock()
    subscription_service = AsyncMock()
    remnawave_service = AsyncMock()
    notification_service = AsyncMock()

    svc = LoyaltyRewardService(
        config=config,
        bot=bot,
        redis_client=redis_client,
        redis_repository=redis_repository,
        translator_hub=translator_hub,
        user_service=user_service,
        subscription_service=subscription_service,
        remnawave_service=remnawave_service,
        notification_service=notification_service,
    )
    return (
        svc,
        redis_client,
        user_service,
        subscription_service,
        remnawave_service,
        notification_service,
    )


class TestLoyaltyRewardService:
    async def test_preview_counts_active_paid_users(self):
        (
            svc,
            redis_client,
            user_service,
            subscription_service,
            _,
            _,
        ) = _make_service()
        user = make_user(telegram_id=100)
        trial_user = make_user(telegram_id=200)
        trial_sub = make_subscription()
        trial_sub.is_trial = True

        user_service.get_by_role.side_effect = [[user], [], [trial_user]]
        redis_client.get.return_value = None
        subscription_service.get_current.side_effect = [
            make_subscription(),
            trial_sub,
        ]

        result = await svc.preview()

        assert result.scanned == 2
        assert result.eligible == 1
        assert result.skipped_trial == 1
        subscription_service.update.assert_not_awaited()

    async def test_grant_extends_subscription_and_sets_personal_discount(self):
        (
            svc,
            redis_client,
            user_service,
            subscription_service,
            remnawave_service,
            notification_service,
        ) = _make_service()
        user = make_user(telegram_id=100)
        subscription = make_subscription()
        original_expire_at = subscription.expire_at

        user_service.get_by_role.side_effect = [[user], [], []]
        redis_client.get.return_value = None
        redis_client.set.return_value = True
        subscription_service.get_current.side_effect = [subscription, subscription]

        async def update_subscription(updated_subscription):
            state_values = [
                call.args[1]
                for call in redis_client.set.await_args_list
                if call.args and call.args[1] != "1"
            ]
            assert any(value.startswith("extend_to:") for value in state_values)
            return updated_subscription

        subscription_service.update.side_effect = update_subscription
        user_service.update.return_value = user

        result = await svc.grant()

        assert result.granted == 1
        assert subscription.expire_at == original_expire_at + timedelta(days=LOYALTY_EXTRA_DAYS)
        assert user.personal_discount == LOYALTY_PERSONAL_DISCOUNT
        subscription_service.update.assert_awaited_once_with(subscription)
        user_service.update.assert_awaited_once_with(user)
        remnawave_service.updated_user.assert_awaited_once()
        notification_service.notify_user.assert_awaited_once()
        assert redis_client.set.await_args_list[-1].args[1] == "granted"

    async def test_retry_from_recorded_target_does_not_add_another_14_days(self):
        (
            svc,
            redis_client,
            user_service,
            subscription_service,
            remnawave_service,
            notification_service,
        ) = _make_service()
        user = make_user(telegram_id=100)
        subscription = make_subscription()
        original_expire_at = subscription.expire_at
        target_expire_at = original_expire_at + timedelta(days=LOYALTY_EXTRA_DAYS)

        user_service.get_by_role.side_effect = [[user], [], []]
        redis_client.get.return_value = f"extend_to:{target_expire_at.isoformat()}".encode()
        redis_client.set.return_value = True
        subscription_service.get_current.side_effect = [subscription, subscription]
        subscription_service.update.return_value = subscription
        user_service.update.return_value = user

        result = await svc.grant()

        assert result.pending_retry == 1
        assert result.granted == 1
        assert subscription.expire_at == target_expire_at
        subscription_service.update.assert_awaited_once_with(subscription)
        remnawave_service.updated_user.assert_awaited_once()
        notification_service.notify_user.assert_awaited_once()

    async def test_grant_skips_user_when_lock_is_held(self):
        (
            svc,
            redis_client,
            user_service,
            subscription_service,
            remnawave_service,
            notification_service,
        ) = _make_service()
        user = make_user(telegram_id=100)

        user_service.get_by_role.side_effect = [[user], [], []]
        redis_client.get.return_value = None
        redis_client.set.return_value = False
        subscription_service.get_current.return_value = make_subscription()

        result = await svc.grant()

        assert result.pending_retry == 1
        assert result.granted == 0
        subscription_service.update.assert_not_awaited()
        remnawave_service.updated_user.assert_not_awaited()
        notification_service.notify_user.assert_not_awaited()

    async def test_retry_after_subscription_extension_does_not_extend_again(self):
        (
            svc,
            redis_client,
            user_service,
            subscription_service,
            remnawave_service,
            notification_service,
        ) = _make_service()
        user = make_user(telegram_id=100)
        subscription = make_subscription()
        original_expire_at = subscription.expire_at

        user_service.get_by_role.side_effect = [[user], [], []]
        redis_client.get.return_value = b"subscription_extended"
        redis_client.set.return_value = True
        subscription_service.get_current.side_effect = [subscription, subscription]
        user_service.update.return_value = user

        result = await svc.grant()

        assert result.pending_retry == 1
        assert result.granted == 1
        assert subscription.expire_at == original_expire_at
        subscription_service.update.assert_not_awaited()
        user_service.update.assert_awaited_once_with(user)
        remnawave_service.updated_user.assert_awaited_once()
        notification_service.notify_user.assert_awaited_once()

    async def test_lists_candidates_from_customer_and_privileged_roles_once(self):
        svc, _, user_service, _, _, _ = _make_service()
        user = make_user(telegram_id=100)
        admin = make_user(telegram_id=200)
        admin.role = UserRole.ADMIN

        user_service.get_by_role.side_effect = [[user], [admin], [admin]]

        users = await svc._list_candidate_users()

        assert [u.telegram_id for u in users] == [100, 200]
