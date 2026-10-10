"""Expiring and expired notices: windows, gating, idempotency, pacing and real Russian copy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fluentogram import TranslatorHub
from fluentogram.storage import FileStorage

from src.core.enums import Locale, UserNotificationType
from src.core.i18n.translator import get_translated_kwargs
from src.core.utils.formatters import i18n_postprocess_text
from src.infrastructure.kafka.subscription_expired_consumer import SubscriptionExpiredConsumer
from src.infrastructure.taskiq.tasks import expiry_notifications as en
from tests.conftest import make_subscription, make_user
from tests.reminder_fakes import (
    FakeBilling,
    NoSleep,
    make_notification_service,
    make_settings_service,
)

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
TG = 555


def _billing_sub(*, sub_id=7, trial=True, expires_in=timedelta(hours=23), status="ACTIVE"):
    return SimpleNamespace(
        ID=sub_id,
        UserTelegramID=TG,
        Status=status,
        IsTrial=trial,
        ExpireAt=NOW + expires_in,
    )


def _current(sub_id=7, *, active=True, expires_in=timedelta(hours=23)):
    subscription = make_subscription(is_trial=True, active=active)
    subscription.__dict__["id"] = sub_id
    subscription.expire_at = NOW + expires_in
    return subscription


def _services(*, current=None, bot_blocked=False, **switches):
    user = make_user(telegram_id=TG)
    user.is_bot_blocked = bot_blocked
    user_service = MagicMock()
    user_service.get = AsyncMock(return_value=user)
    subscription_service = MagicMock()
    subscription_service.get_current = AsyncMock(return_value=current)
    return SimpleNamespace(
        billing=FakeBilling(),
        user_service=user_service,
        subscription_service=subscription_service,
        notifications=make_notification_service(),
        settings=make_settings_service(**switches),
        sleeper=NoSleep(),
    )


async def _scan(s, now=NOW):
    return await en.send_expiring_notifications(
        billing=s.billing,
        user_service=s.user_service,
        subscription_service=s.subscription_service,
        notification_service=s.notifications,
        settings_service=s.settings,
        sleeper=s.sleeper,
        now=now,
    )


async def _expired(s, payload, now=NOW):
    return await en.notify_subscription_expired(
        payload=payload,
        billing=s.billing,
        user_service=s.user_service,
        subscription_service=s.subscription_service,
        notification_service=s.notifications,
        settings_service=s.settings,
        sleeper=s.sleeper,
        now=now,
    )


def _payload(*, sub_id=7, expired_ago=timedelta(minutes=2)):
    return {
        "telegram_id": TG,
        "subscription_id": sub_id,
        "plan_name": "trial",
        "expire_at": (NOW - expired_ago).isoformat().replace("+00:00", "Z"),
    }


class TestExpiringWindows:
    @pytest.mark.parametrize(
        ("trial", "hours_left", "expected"),
        [
            (True, 23, [1]),
            (True, 24, [1]),
            (True, 25, []),
            (True, 21, []),
            (True, 71, []),
            (False, 71.5, [3]),
            (False, 23, [1]),
            (False, 48, []),
            (False, 100, []),
        ],
    )
    def test_marks(self, trial, hours_left, expected):
        marks = en.due_expiring_marks(
            is_trial=trial, expire_at=NOW + timedelta(hours=hours_left), now=NOW
        )
        assert [days for days, _ in marks] == expected

    def test_a_subscription_whose_mark_passed_before_deploy_is_not_caught(self):
        # 3-day mark of a subscription that expires in 48 h passed a day ago: no backfill.
        assert en.due_expiring_marks(
            is_trial=False, expire_at=NOW + timedelta(hours=48), now=NOW
        ) == []


class TestExpiringScan:
    async def test_sends_trial_notice_once_and_records_the_claim(self):
        s = _services(current=_current())
        s.billing.subscriptions = [_billing_sub()]

        assert await _scan(s) == 1
        assert await _scan(s) == 0

        (telegram_id, payload, ntf_type, _) = s.notifications.sent[0]
        assert telegram_id == TG
        assert payload.i18n_key == "ntf-event-user-expiring"
        assert payload.i18n_kwargs == {"is_trial": True, "value": 1}
        assert ntf_type is UserNotificationType.EXPIRES_IN_1_DAYS
        assert (TG, "SUB_EXPIRING_1D", "sub-7:20261012") in s.billing.claims
        assert len(s.notifications.sent) == 1

    async def test_paid_subscription_gets_renew_button(self):
        s = _services(current=_current())
        s.billing.subscriptions = [_billing_sub(trial=False, expires_in=timedelta(hours=71.5))]

        await _scan(s)

        payload = s.notifications.sent[0][1]
        assert payload.i18n_kwargs == {"is_trial": False, "value": 3}
        assert payload.reply_markup.inline_keyboard[0][0].text == "btn-goto-subscription-renew"

    async def test_ignores_inactive_subscriptions(self):
        s = _services(current=_current())
        s.billing.subscriptions = [_billing_sub(status="EXPIRED"), _billing_sub(status="DISABLED")]

        assert await _scan(s) == 0

    async def test_switch_off_sends_nothing(self):
        s = _services(current=_current(), EXPIRES_IN_1_DAYS=False)
        s.billing.subscriptions = [_billing_sub()]

        assert await _scan(s) == 0
        assert s.billing.claims == {}

    async def test_bot_blocked_users_are_excluded(self):
        s = _services(current=_current(), bot_blocked=True)
        s.billing.subscriptions = [_billing_sub()]

        assert await _scan(s) == 0
        assert s.billing.claims == {}

    async def test_only_the_users_current_subscription_is_notified(self):
        s = _services(current=_current(sub_id=99))
        s.billing.subscriptions = [_billing_sub(sub_id=7)]

        assert await _scan(s) == 0

    async def test_many_users_are_paced_under_twenty_per_second(self):
        s = _services(current=_current())
        s.billing.subscriptions = [_billing_sub(sub_id=7)]
        await _scan(s)
        assert s.sleeper.calls
        assert all(delay >= 0.05 for delay in s.sleeper.calls)
        assert 1 / s.sleeper.calls[0] <= 20

    async def test_one_failing_user_does_not_stop_the_scan(self):
        s = _services(current=_current())
        first, second = _billing_sub(sub_id=7), _billing_sub(sub_id=8)
        second.UserTelegramID = 556
        s.billing.subscriptions = [first, second]
        calls = {"n": 0}

        async def flaky(telegram_id):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            user = make_user(telegram_id=telegram_id)
            return user

        s.user_service.get = AsyncMock(side_effect=flaky)
        s.subscription_service.get_current = AsyncMock(return_value=_current(sub_id=8))

        assert await _scan(s) == 1


class TestExpiredEvent:
    async def test_trial_expiry_sends_buy_notice_once(self):
        s = _services(current=_current(active=False, expires_in=-timedelta(minutes=2)))
        s.billing.by_id[7] = _billing_sub(status="EXPIRED")

        assert await _expired(s, _payload()) is True
        assert await _expired(s, _payload()) is False

        (_, payload, ntf_type, _) = s.notifications.sent[0]
        assert payload.i18n_key == "ntf-event-user-expired"
        assert payload.i18n_kwargs == {"is_trial": True}
        assert payload.reply_markup.inline_keyboard[0][0].text == "btn-goto-subscription"
        assert ntf_type is UserNotificationType.EXPIRED
        assert (TG, "SUB_EXPIRED", "sub-7:20261011") in s.billing.claims
        assert len(s.notifications.sent) == 1

    async def test_paid_expiry_offers_renewal(self):
        s = _services(current=_current(active=False, expires_in=-timedelta(minutes=2)))
        s.billing.by_id[7] = _billing_sub(trial=False, status="EXPIRED")

        await _expired(s, _payload())

        payload = s.notifications.sent[0][1]
        assert payload.i18n_kwargs == {"is_trial": False}
        assert payload.reply_markup.inline_keyboard[0][0].text == "btn-goto-subscription-renew"

    async def test_old_events_are_not_notified(self):
        s = _services(current=_current(active=False))
        s.billing.by_id[7] = _billing_sub()

        assert await _expired(s, _payload(expired_ago=timedelta(hours=49))) is False
        assert s.notifications.sent == []

    async def test_already_renewed_subscription_is_not_told_it_expired(self):
        s = _services(current=_current(active=True, expires_in=timedelta(days=30)))
        s.billing.by_id[7] = _billing_sub(trial=False)

        assert await _expired(s, _payload()) is False

    async def test_older_subscription_that_is_not_current_is_not_notified(self):
        s = _services(current=_current(sub_id=99, active=False, expires_in=-timedelta(minutes=2)))
        s.billing.by_id[7] = _billing_sub()

        assert await _expired(s, _payload(sub_id=7)) is False
        assert s.billing.claims == {}

    async def test_user_without_a_current_subscription_is_not_notified(self):
        s = _services(current=None)
        s.billing.by_id[7] = _billing_sub()

        assert await _expired(s, _payload()) is False

    async def test_switch_off_and_bot_blocked_send_nothing(self):
        off = _services(current=_current(active=False), EXPIRED=False)
        off.billing.by_id[7] = _billing_sub()
        assert await _expired(off, _payload()) is False

        blocked = _services(current=_current(active=False), bot_blocked=True)
        blocked.billing.by_id[7] = _billing_sub()
        assert await _expired(blocked, _payload()) is False
        assert blocked.billing.claims == {}

    @pytest.mark.parametrize(
        "payload",
        [{}, {"telegram_id": TG}, {"telegram_id": TG, "subscription_id": 7}],
    )
    async def test_malformed_events_are_skipped(self, payload):
        s = _services(current=_current(active=False))

        assert await _expired(s, payload) is False

    async def test_consumer_hands_the_event_to_the_notifier(self):
        s = _services(current=_current(active=False, expires_in=-timedelta(minutes=2)))
        s.billing.by_id[7] = _billing_sub()
        services = {
            "BillingClient": s.billing,
            "UserService": s.user_service,
            "SubscriptionService": s.subscription_service,
            "NotificationService": s.notifications,
            "SettingsService": s.settings,
        }
        request_container = MagicMock()
        request_container.get = AsyncMock(side_effect=lambda cls: services[cls.__name__])
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=request_container)
        cm.__aexit__ = AsyncMock(return_value=None)
        config = MagicMock()
        config.kafka_brokers = "localhost:9092"
        config.kafka_group_id = "g"
        config.kafka_subscription_expired_topic = "prod.compono-billing.subscription.expired.v1"
        consumer = SubscriptionExpiredConsumer(config=config, container=MagicMock(return_value=cm))

        payload = {
            "telegram_id": TG,
            "subscription_id": 7,
            "expire_at": datetime.now(timezone.utc).isoformat(),
        }
        await consumer._handle_message(payload)

        assert consumer.topic == "prod.compono-billing.subscription.expired.v1"
        assert consumer.group_id == "g-expiry-notice"
        assert len(s.notifications.sent) == 1


@pytest.fixture(scope="module")
def translator():
    storage = FileStorage(path=Path("assets/translations") / "{locale}")
    hub = TranslatorHub({"ru": ("ru",)}, root_locale="ru", storage=storage)
    return hub.get_translator_by_locale(locale=Locale.RU)


def _render(translator, key, **kwargs):
    rendered = translator.get(key, **get_translated_kwargs(translator, kwargs))
    return i18n_postprocess_text(rendered)


class TestRussianCopy:
    def test_trial_expiring_mentions_first30_and_plain_wording(self, translator):
        text = _render(translator, "ntf-event-user-expiring", is_trial=True, value=1)
        assert "через 1 день" in text
        assert "пробный период" in text
        assert "FIRST30" in text
        assert "пробник" not in text

    def test_paid_expiring_does_not_offer_first_month_discount(self, translator):
        text = _render(translator, "ntf-event-user-expiring", is_trial=False, value=3)
        assert "через 3 дня" in text
        assert "FIRST30" not in text
        assert "Продлите" in text

    def test_trial_expired_mentions_first30(self, translator):
        text = _render(translator, "ntf-event-user-expired", is_trial=True)
        assert "пробный период закончился" in text
        assert "FIRST30" in text

    def test_paid_expired_asks_to_renew(self, translator):
        text = _render(translator, "ntf-event-user-expired", is_trial=False)
        assert "подписка истекла" in text
        assert "FIRST30" not in text

    def test_setup_messages_render_without_placeholders(self, translator):
        for key in (
            "ntf-event-setup-reminder-24h",
            "ntf-event-setup-checkin",
            "ntf-setup-checkin-connected",
            "ntf-setup-checkin-not-connected",
        ):
            text = _render(translator, key)
            assert text and "{" not in text and "$" not in text, key

    def test_checkin_answers_carry_the_promised_content(self, translator):
        yes = _render(translator, "ntf-setup-checkin-connected")
        no = _render(translator, "ntf-setup-checkin-not-connected")
        assert "FIRST30" in yes and "30 дней" in yes
        assert "Белый список" in no and "Direct" in no
        assert "Обновите подписку" in no and "другое приложение" in no
        assert "поддержку" in no

    def test_buttons_exist(self, translator):
        for key in ("btn-setup-checkin-yes", "btn-setup-checkin-no"):
            assert translator.get(key) != key
