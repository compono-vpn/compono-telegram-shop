"""24 h setup reminder and the first-fetch check-in: scheduling, gating and idempotency."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramNetworkError

from src.core.enums import SetupCheckinAnswer, UserNotificationType
from src.infrastructure.taskiq.tasks import setup_followups as sf
from tests.conftest import make_subscription, make_user
from tests.reminder_fakes import (
    FakeBilling,
    FakeRedis,
    NoSleep,
    make_notification_service,
    make_settings_service,
)

NOW = 1_800_000_000.0
CONNECT_URL = "https://componovpn.com/connect/abc123"
TG = 777


def _subscription(sub_id: int = 5, *, trial: bool = True, active: bool = True):
    subscription = make_subscription(is_trial=trial, active=active)
    subscription.__dict__["id"] = sub_id
    return subscription


def _user(*, bot_blocked: bool = False, blocked: bool = False):
    user = make_user(telegram_id=TG)
    user.is_bot_blocked = bot_blocked
    user.is_blocked = blocked
    return user


def _services(*, subscription=None, user=None, remote=None, devices=None, **switches):
    user_service = MagicMock()
    user_service.get = AsyncMock(return_value=user if user is not None else _user())
    subscription_service = MagicMock()
    subscription_service.get_current = AsyncMock(
        return_value=subscription if subscription is not None else _subscription()
    )
    remnawave = MagicMock()
    remnawave.get_devices_user = AsyncMock(return_value=devices or [])
    remnawave.get_user = AsyncMock(
        return_value=remote or SimpleNamespace(sub_last_opened_at=None, user_traffic=None)
    )
    config = MagicMock()
    config.bot.support_username.get_secret_value.return_value = "support_bot"
    return SimpleNamespace(
        redis=FakeRedis(),
        billing=FakeBilling(),
        user_service=user_service,
        subscription_service=subscription_service,
        remnawave=remnawave,
        notifications=make_notification_service(),
        settings=make_settings_service(**switches),
        config=config,
        sleeper=NoSleep(),
    )


async def _run_24h(s, now=NOW + sf.SETUP_REMINDER_DELAY + 1):
    return await sf.process_setup_reminders(
        redis_client=s.redis,
        billing=s.billing,
        user_service=s.user_service,
        subscription_service=s.subscription_service,
        remnawave_service=s.remnawave,
        notification_service=s.notifications,
        settings_service=s.settings,
        config=s.config,
        sleeper=s.sleeper,
        now=now,
    )


async def _watch(s, now):
    return await sf.watch_first_profile_fetch(
        redis_client=s.redis,
        user_service=s.user_service,
        subscription_service=s.subscription_service,
        remnawave_service=s.remnawave,
        settings_service=s.settings,
        now=now,
    )


async def _run_checkins(s, now):
    return await sf.process_setup_checkins(
        redis_client=s.redis,
        billing=s.billing,
        user_service=s.user_service,
        subscription_service=s.subscription_service,
        notification_service=s.notifications,
        settings_service=s.settings,
        sleeper=s.sleeper,
        now=now,
    )


async def _schedule(s, sub_id=5):
    await sf.schedule_setup_followups(s.redis, TG, sub_id, CONNECT_URL, now=NOW)


class TestScheduling:
    async def test_queues_24h_reminder_and_fetch_watch(self):
        s = _services()
        await _schedule(s)

        reminders = s.redis.members(sf._REMINDERS_KEY.pack())
        assert reminders == {f"{TG}:5:{CONNECT_URL}": NOW + 24 * 3600}
        assert s.redis.members(sf._WATCH_KEY.pack()) == {f"{TG}:5": NOW}

    async def test_scheduling_twice_keeps_the_first_timestamp(self):
        s = _services()
        await _schedule(s)
        await sf.schedule_setup_followups(s.redis, TG, 5, CONNECT_URL, now=NOW + 999)

        assert s.redis.members(sf._WATCH_KEY.pack()) == {f"{TG}:5": NOW}


class TestSetup24hReminder:
    async def test_sends_once_to_a_trial_user_who_never_opened_the_profile(self):
        s = _services()
        await _schedule(s)

        assert await _run_24h(s) == 1

        (telegram_id, payload, ntf_type, message) = s.notifications.sent[0]
        assert telegram_id == TG
        assert payload.i18n_key == "ntf-event-setup-reminder-24h"
        assert ntf_type is UserNotificationType.SETUP_REMINDER_24H
        urls = [b.url for row in payload.reply_markup.inline_keyboard for b in row]
        assert urls[0] == CONNECT_URL
        assert urls[1].startswith("https://t.me/support_bot?text=")
        assert message.message_id == 1000
        assert (TG, "SETUP_24H", "sub-5") in s.billing.claims
        assert s.sleeper.calls == [sf_interval()]

    async def test_not_due_before_24_hours(self):
        s = _services()
        await _schedule(s)

        assert await _run_24h(s, now=NOW + 3600) == 0
        assert s.notifications.sent == []
        assert s.redis.members(sf._REMINDERS_KEY.pack())

    @pytest.mark.parametrize(
        "remote",
        [
            SimpleNamespace(sub_last_opened_at="2026-10-11T10:00:00Z", user_traffic=None),
            SimpleNamespace(
                sub_last_opened_at=None,
                user_traffic=SimpleNamespace(used_traffic_bytes=1, lifetime_used_traffic_bytes=1),
            ),
        ],
    )
    async def test_skips_users_who_fetched_or_used_traffic(self, remote):
        s = _services(remote=remote)
        await _schedule(s)

        assert await _run_24h(s) == 0
        assert s.billing.claims == {}

    async def test_user_missing_from_the_panel_is_skipped_not_retried(self):
        from remnapy.exceptions import NotFoundError

        s = _services()
        s.remnawave.get_devices_user.side_effect = NotFoundError(404, MagicMock(message="User not found", code="A025"))
        await _schedule(s)

        assert await _run_24h(s) == 0
        assert s.notifications.sent == []
        assert s.billing.claims == {}
        assert s.redis.members(sf._REMINDERS_KEY.pack()) == {}

    async def test_skips_users_with_a_registered_device(self):
        s = _services(devices=[object()])
        await _schedule(s)

        assert await _run_24h(s) == 0

    @pytest.mark.parametrize(
        "case",
        ["bot_blocked", "blocked", "paid", "expired", "other_subscription", "no_subscription"],
    )
    async def test_skips_users_who_cannot_or_should_not_receive_it(self, case):
        subscription = {
            "paid": _subscription(trial=False),
            "expired": _subscription(active=False),
            "other_subscription": _subscription(sub_id=99),
        }.get(case)
        s = _services(
            user=_user(bot_blocked=case == "bot_blocked", blocked=case == "blocked"),
            subscription=subscription,
        )
        if case == "no_subscription":
            s.subscription_service.get_current.return_value = None
        await _schedule(s)

        assert await _run_24h(s) == 0
        assert s.notifications.sent == []

    async def test_switch_off_drops_due_items_without_sending(self):
        s = _services(SETUP_REMINDER_24H=False)
        await _schedule(s)

        assert await _run_24h(s) == 0
        assert s.notifications.sent == []
        assert s.redis.members(sf._REMINDERS_KEY.pack()) == {}

    async def test_same_reminder_is_never_sent_twice(self):
        s = _services()
        await _schedule(s)
        await _run_24h(s)
        await sf.schedule_setup_followups(s.redis, TG, 5, CONNECT_URL, now=NOW)

        assert await _run_24h(s) == 0
        assert len(s.notifications.sent) == 1

    async def test_transient_send_failure_releases_claim_and_retries_later(self):
        s = _services()
        s.notifications = make_notification_service(
            error=TelegramNetworkError(method=MagicMock(), message="timeout")
        )
        await _schedule(s)

        assert await _run_24h(s) == 0

        assert s.billing.claims == {}
        assert s.billing.release_calls == 1
        retry = s.redis.members(sf._REMINDERS_KEY.pack())
        assert list(retry.values()) == [NOW + sf.SETUP_REMINDER_DELAY + 1 + sf.RETRY_DELAY]

    async def test_billing_outage_requeues_instead_of_losing_the_reminder(self):
        s = _services()
        s.billing.claim_error = RuntimeError("billing down")
        await _schedule(s)

        assert await _run_24h(s) == 0
        assert s.redis.members(sf._REMINDERS_KEY.pack())
        assert s.notifications.sent == []

    async def test_blocked_by_user_keeps_the_claim_and_does_not_retry(self):
        s = _services()
        s.notifications = make_notification_service(result=None)
        await _schedule(s)

        assert await _run_24h(s) == 0
        assert (TG, "SETUP_24H", "sub-5") in s.billing.claims
        assert s.redis.members(sf._REMINDERS_KEY.pack()) == {}


def sf_interval() -> float:
    from src.services.reminder_delivery import SEND_INTERVAL_SECONDS

    return SEND_INTERVAL_SECONDS


class TestFirstFetchWatch:
    async def test_first_fetch_queues_checkin_thirty_minutes_later(self):
        from datetime import datetime, timezone

        fetched = NOW + 600
        remote = SimpleNamespace(
            sub_last_opened_at=datetime.fromtimestamp(fetched, tz=timezone.utc), user_traffic=None
        )
        s = _services(remote=remote)
        await _schedule(s)

        assert await _watch(s, now=NOW + 900) == 1

        assert s.redis.members(sf._CHECKINS_KEY.pack()) == {f"{TG}:5": fetched + 30 * 60}
        assert s.redis.members(sf._WATCH_KEY.pack()) == {}

    async def test_no_fetch_keeps_watching(self):
        s = _services()
        await _schedule(s)

        assert await _watch(s, now=NOW + 900) == 0
        assert s.redis.members(sf._WATCH_KEY.pack()) == {f"{TG}:5": NOW}
        assert s.redis.members(sf._CHECKINS_KEY.pack()) == {}

    async def test_a_fetch_older_than_the_trial_is_not_a_first_fetch(self):
        from datetime import datetime, timezone

        remote = SimpleNamespace(
            sub_last_opened_at=datetime.fromtimestamp(NOW - 5000, tz=timezone.utc),
            user_traffic=None,
        )
        s = _services(remote=remote)
        await _schedule(s)

        assert await _watch(s, now=NOW + 900) == 0
        assert s.redis.members(sf._CHECKINS_KEY.pack()) == {}

    async def test_watch_expires_after_72_hours(self):
        s = _services()
        await _schedule(s)

        await _watch(s, now=NOW + sf.WATCH_MAX_AGE + 1)

        assert s.redis.members(sf._WATCH_KEY.pack()) == {}

    async def test_switch_off_keeps_watch_but_queues_nothing(self):
        from datetime import datetime, timezone

        remote = SimpleNamespace(
            sub_last_opened_at=datetime.fromtimestamp(NOW + 60, tz=timezone.utc), user_traffic=None
        )
        s = _services(remote=remote, SETUP_CHECKIN=False)
        await _schedule(s)

        assert await _watch(s, now=NOW + 900) == 0
        assert s.redis.members(sf._CHECKINS_KEY.pack()) == {}
        s.remnawave.get_user.assert_not_awaited()

    async def test_paid_or_replaced_subscription_stops_the_watch(self):
        s = _services(subscription=_subscription(trial=False))
        await _schedule(s)

        await _watch(s, now=NOW + 900)

        assert s.redis.members(sf._WATCH_KEY.pack()) == {}


class TestCheckin:
    async def _queue(self, s, due_at):
        await s.redis.zadd(sf._CHECKINS_KEY.pack(), {f"{TG}:5": due_at})

    async def test_sends_yes_no_question_once(self):
        s = _services()
        await self._queue(s, NOW)

        assert await _run_checkins(s, now=NOW + 1) == 1

        (_, payload, ntf_type, message) = s.notifications.sent[0]
        assert payload.i18n_key == "ntf-event-setup-checkin"
        assert ntf_type is UserNotificationType.SETUP_CHECKIN
        buttons = [b.callback_data for row in payload.reply_markup.inline_keyboard for b in row]
        assert buttons == [
            f"sck:{SetupCheckinAnswer.CONNECTED.value}",
            f"sck:{SetupCheckinAnswer.NOT_CONNECTED.value}",
        ]
        assert (TG, "SETUP_CHECKIN", "first") in s.billing.claims
        assert message.message_id == 1000

    async def test_not_sent_before_thirty_minutes_are_up(self):
        s = _services()
        await self._queue(s, NOW + 1800)

        assert await _run_checkins(s, now=NOW + 60) == 0
        assert s.notifications.sent == []

    async def test_user_is_asked_only_once_even_if_queued_again(self):
        s = _services()
        await self._queue(s, NOW)
        await _run_checkins(s, now=NOW + 1)
        await self._queue(s, NOW)

        assert await _run_checkins(s, now=NOW + 2) == 0
        assert len(s.notifications.sent) == 1

    async def test_stale_checkin_is_dropped(self):
        s = _services()
        await self._queue(s, NOW)

        assert await _run_checkins(s, now=NOW + sf.MAX_LATENESS + 1) == 0
        assert s.notifications.sent == []
        assert s.redis.members(sf._CHECKINS_KEY.pack()) == {}

    async def test_switch_off_sends_nothing(self):
        s = _services(SETUP_CHECKIN=False)
        await self._queue(s, NOW)

        assert await _run_checkins(s, now=NOW + 1) == 0
        assert s.notifications.sent == []

    @pytest.mark.parametrize("case", ["bot_blocked", "paid"])
    async def test_skips_blocked_and_already_paying_users(self, case):
        s = _services(
            user=_user(bot_blocked=case == "bot_blocked"),
            subscription=_subscription(trial=False) if case == "paid" else None,
        )
        await self._queue(s, NOW)

        assert await _run_checkins(s, now=NOW + 1) == 0
        assert s.notifications.sent == []
