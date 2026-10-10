"""Check-in answers: durable storage, replies, and the ✅ unlock of the 30-day offer."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message

from src.bot.routers.extra.setup_checkin import on_setup_checkin_answer, parse_checkin_answer
from src.core.enums import SetupCheckinAnswer
from src.core.metrics import SETUP_CHECKIN_ANSWERS_TOTAL
from src.infrastructure.billing.models import BillingPlan, BillingPlanDuration
from src.infrastructure.kafka.trial_reminder_consumer import TrialReminderConsumer
from src.infrastructure.taskiq.tasks import setup_followups as sf
from src.services.trial_activation import get_monthly_trial_plan, has_confirmed_connection
from tests.conftest import make_config, make_i18n, make_subscription, make_user, unwrap_inject
from tests.reminder_fakes import FakeBilling, FakeRedis

TG = 4242


def _callback(data: str) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    return callback


def _billing_with_checkin() -> FakeBilling:
    billing = FakeBilling()
    billing.claims[(TG, "SETUP_CHECKIN", "first")] = None
    return billing


def _count(answer: str) -> float:
    return SETUP_CHECKIN_ANSWERS_TOTAL.labels(answer=answer)._value.get()


def _button_texts(call) -> list[str]:
    markup = call.kwargs["reply_markup"]
    return [button.text for row in markup.inline_keyboard for button in row]


class TestAnswerCallback:
    async def test_yes_is_stored_and_shows_the_paid_offer(self):
        billing = _billing_with_checkin()
        callback = _callback("sck:CONNECTED")
        user = make_user(telegram_id=TG, subscription=make_subscription(is_trial=True))
        before = _count("CONNECTED")

        raw = unwrap_inject(on_setup_checkin_answer)
        await raw(callback, user, make_i18n(), billing, make_config())

        assert billing.claims[(TG, "SETUP_CHECKIN", "first")] == "CONNECTED"
        call = callback.message.edit_text.await_args
        assert call.kwargs["text"] == "[ntf-setup-checkin-connected]"
        assert _button_texts(call) == ["[btn-goto-subscription]"]
        assert _count("CONNECTED") == before + 1
        callback.answer.assert_awaited_once()

    async def test_no_is_stored_and_shows_troubleshooting_with_support(self):
        billing = _billing_with_checkin()
        callback = _callback("sck:NOT_CONNECTED")
        user = make_user(telegram_id=TG, subscription=make_subscription(is_trial=True))
        config = make_config()
        config.bot.support_username.get_secret_value.return_value = "support_bot"

        raw = unwrap_inject(on_setup_checkin_answer)
        await raw(callback, user, make_i18n(), billing, config)

        assert billing.claims[(TG, "SETUP_CHECKIN", "first")] == "NOT_CONNECTED"
        call = callback.message.edit_text.await_args
        assert call.kwargs["text"] == "[ntf-setup-checkin-not-connected]"
        assert _button_texts(call) == ["[btn-notification-connect]", "[btn-contact-support]"]
        urls = [b.url for row in call.kwargs["reply_markup"].inline_keyboard for b in row]
        assert urls[0] == "https://componovpn.com/connect/abc123"
        assert urls[1].startswith("https://t.me/support_bot")

    async def test_answer_without_a_sent_checkin_is_ignored(self):
        billing = FakeBilling()
        callback = _callback("sck:CONNECTED")

        raw = unwrap_inject(on_setup_checkin_answer)
        await raw(callback, make_user(telegram_id=TG), make_i18n(), billing, make_config())

        callback.message.edit_text.assert_not_awaited()
        assert billing.claims == {}

    async def test_unknown_payload_is_ignored(self):
        billing = _billing_with_checkin()
        callback = _callback("sck:MAYBE")

        raw = unwrap_inject(on_setup_checkin_answer)
        await raw(callback, make_user(telegram_id=TG), make_i18n(), billing, make_config())

        assert billing.claims[(TG, "SETUP_CHECKIN", "first")] is None
        callback.message.edit_text.assert_not_awaited()

    async def test_storage_failure_does_not_crash_the_handler(self):
        billing = AsyncMock()
        billing.answer_user_reminder.side_effect = RuntimeError("billing down")
        callback = _callback("sck:CONNECTED")

        raw = unwrap_inject(on_setup_checkin_answer)
        await raw(callback, make_user(telegram_id=TG), make_i18n(), billing, make_config())

        callback.message.edit_text.assert_not_awaited()
        callback.answer.assert_awaited_once()

    def test_parse(self):
        assert parse_checkin_answer("sck:CONNECTED") is SetupCheckinAnswer.CONNECTED
        assert parse_checkin_answer("sck:NOT_CONNECTED") is SetupCheckinAnswer.NOT_CONNECTED
        assert parse_checkin_answer("sck:x") is None


def _plan():
    return BillingPlan(
        ID=1, OrderIndex=0, IsActive=True, Type="BOTH", Availability="ALL", Name="Start",
        TrafficLimitStrategy="MONTH", Durations=[BillingPlanDuration(Days=30)],
    )


class TestUnlock:
    async def test_yes_answer_unlocks_the_monthly_offer_without_traffic(self):
        billing = FakeBilling()
        billing.claims[(TG, "SETUP_CHECKIN", "first")] = "CONNECTED"
        billing.get_available_plans = AsyncMock(return_value=[_plan()])
        remna = AsyncMock()
        remna.get_user.return_value = SimpleNamespace(user_traffic=None)
        user = make_user(telegram_id=TG, subscription=make_subscription(is_trial=True))

        plan = await get_monthly_trial_plan(user, remna, billing)

        assert plan is not None and plan.id == 1

    @pytest.mark.parametrize("answer", ["NOT_CONNECTED", None])
    async def test_no_answer_or_no_reply_stays_locked(self, answer):
        billing = FakeBilling()
        billing.claims[(TG, "SETUP_CHECKIN", "first")] = answer
        billing.get_available_plans = AsyncMock(return_value=[_plan()])
        remna = AsyncMock()
        remna.get_user.return_value = SimpleNamespace(user_traffic=None)
        user = make_user(telegram_id=TG, subscription=make_subscription(is_trial=True))

        assert await get_monthly_trial_plan(user, remna, billing) is None
        billing.get_available_plans.assert_not_awaited()

    async def test_unreadable_answer_means_unconfirmed(self):
        billing = AsyncMock()
        billing.list_user_reminders.side_effect = RuntimeError("down")
        assert await has_confirmed_connection(billing, TG) is False

    async def test_paid_and_expired_users_never_unlock(self):
        billing = FakeBilling()
        billing.claims[(TG, "SETUP_CHECKIN", "first")] = "CONNECTED"
        remna = AsyncMock()
        paid = make_user(telegram_id=TG, subscription=make_subscription(is_trial=False))
        assert await get_monthly_trial_plan(paid, remna, billing) is None
        expired = make_user(
            telegram_id=TG, subscription=make_subscription(is_trial=True, active=False)
        )
        assert await get_monthly_trial_plan(expired, remna, billing) is None


class TestTrialEventSchedulesFollowups:
    async def test_trial_created_event_queues_24h_reminder_and_fetch_watch(self):
        redis = FakeRedis()
        subscription = make_subscription(is_trial=True)
        subscription.__dict__["id"] = 31
        subscription_service = MagicMock()
        subscription_service.get_current = AsyncMock(return_value=subscription)
        config = MagicMock()
        config.website_url = "https://componovpn.com"
        services = {"SubscriptionService": subscription_service, "Redis": redis, "AppConfig": config}
        request_container = MagicMock()
        request_container.get = AsyncMock(side_effect=lambda cls: services[cls.__name__])
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=request_container)
        cm.__aexit__ = AsyncMock(return_value=None)
        kafka_config = MagicMock()
        kafka_config.kafka_brokers = "localhost:9092"
        kafka_config.kafka_group_id = "g"
        kafka_config.kafka_subscription_created_topic = "t"
        consumer = TrialReminderConsumer(config=kafka_config, container=MagicMock(return_value=cm))
        redis.zadd = AsyncMock(wraps=redis.zadd)

        await consumer._handle_message({"telegram_id": TG, "is_trial": True})

        keys = [call.args[0] for call in redis.zadd.await_args_list]
        assert sf._REMINDERS_KEY.pack() in keys
        assert sf._WATCH_KEY.pack() in keys
        assert f"{TG}:31" in redis.members(sf._WATCH_KEY.pack())

    async def test_paid_event_schedules_nothing_new(self):
        redis = FakeRedis()
        kafka_config = MagicMock()
        kafka_config.kafka_brokers = "localhost:9092"
        kafka_config.kafka_group_id = "g"
        kafka_config.kafka_subscription_created_topic = "t"
        consumer = TrialReminderConsumer(config=kafka_config, container=MagicMock())

        await consumer._handle_message({"telegram_id": TG, "is_trial": False})

        assert redis.zsets == {}
