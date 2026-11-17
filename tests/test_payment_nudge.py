"""One persistent nudge about 5 minutes after a payment is created and still pending."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fluentogram import TranslatorHub
from fluentogram.storage import FileStorage

from src.bot.keyboards import get_payment_nudge_keyboard
from src.core.metrics import PAYMENT_NUDGE_SENT_TOTAL
from src.core.storage.keys import PendingPaymentNudgesKey
from src.services.payment_nudge import (
    MAX_LATENESS_SECONDS,
    NUDGE_DELAY_SECONDS,
    process_due_payment_nudges,
    schedule_payment_nudge,
)
from tests.conftest import make_user
from tests.reminder_fakes import KvRedis

TG = 4242
URL = "https://t.me/$stars-invoice"
NOW = 1_800_000_000.0


def _transaction(status: str = "PENDING", created_at: Optional[datetime] = None, **kwargs):
    return SimpleNamespace(
        Status=status,
        GatewayType=kwargs.get("gateway", "TELEGRAM_STARS"),
        CreatedAt=created_at or datetime.fromtimestamp(NOW, tz=timezone.utc),
    )


def _billing(transaction=None, history=None) -> AsyncMock:
    billing = AsyncMock()
    billing.get_transaction.return_value = (
        transaction if transaction is not None else _transaction()
    )
    billing.list_transactions.return_value = history or []
    return billing


def _services(user=None):
    user_service = AsyncMock()
    user_service.get.return_value = user if user is not None else make_user(telegram_id=TG)
    notification = AsyncMock()
    notification.notify_user.return_value = MagicMock(message_id=1)
    return user_service, notification


async def _schedule(redis, payment_id=None, telegram_id=TG, now=NOW):
    payment_id = payment_id or str(uuid4())
    await schedule_payment_nudge(
        redis,
        payment_id=payment_id,
        telegram_id=telegram_id,
        payment_url=URL,
        plan_name="⚡️ Старт",
        price_text="119 ★",
        now=now,
    )
    return payment_id


async def _run(redis, billing, user_service, notification, now):
    return await process_due_payment_nudges(
        redis_client=redis,
        billing=billing,
        user_service=user_service,
        notification_service=notification,
        now=now,
    )


class TestSchedule:
    async def test_queues_the_payment_five_minutes_out(self):
        redis = KvRedis()

        payment_id = await _schedule(redis)

        queue = redis.zsets[PendingPaymentNudgesKey().pack()]
        assert queue == {f"{payment_id}:{TG}": NOW + NUDGE_DELAY_SECONDS}
        assert NUDGE_DELAY_SECONDS == 300

    async def test_stores_what_the_message_needs(self):
        redis = KvRedis()

        payment_id = await _schedule(redis)

        stored = [json.loads(v) for k, v in redis.values.items() if payment_id in k and v != "1"]
        assert stored and stored[0]["url"] == URL
        assert stored[0]["plan"] == "⚡️ Старт"
        assert stored[0]["price"] == "119 ★"

    async def test_without_a_payment_link_nothing_is_queued(self):
        redis = KvRedis()

        await schedule_payment_nudge(
            redis,
            payment_id=str(uuid4()),
            telegram_id=TG,
            payment_url="",
            plan_name="x",
            price_text="1",
            now=NOW,
        )

        assert redis.zsets == {}


class TestSend:
    async def test_pending_payment_gets_one_persistent_message(self):
        redis = KvRedis()
        payment_id = await _schedule(redis)
        user_service, notification = _services()
        before = PAYMENT_NUDGE_SENT_TOTAL.labels(gateway="TELEGRAM_STARS")._value.get()

        sent = await _run(redis, _billing(), user_service, notification, NOW + 301)

        assert sent == 1
        notification.notify_user.assert_awaited_once()
        payload = notification.notify_user.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-payment-nudge"
        assert payload.auto_delete_after is None
        assert payload.add_close_button is False
        assert payload.i18n_kwargs == {"plan": "⚡️ Старт", "price": "119 ★"}
        buttons = [b for row in payload.reply_markup.inline_keyboard for b in row]
        assert [b.text for b in buttons] == ["btn-payment-nudge-pay"]
        assert buttons[0].url == URL
        assert PAYMENT_NUDGE_SENT_TOTAL.labels(gateway="TELEGRAM_STARS")._value.get() == before + 1

    async def test_nothing_is_sent_before_five_minutes(self):
        redis = KvRedis()
        await _schedule(redis)
        user_service, notification = _services()

        sent = await _run(redis, _billing(), user_service, notification, NOW + 299)

        assert sent == 0
        notification.notify_user.assert_not_awaited()

    async def test_running_again_never_sends_a_second_message(self):
        redis = KvRedis()
        await _schedule(redis)
        user_service, notification = _services()
        billing = _billing()

        await _run(redis, billing, user_service, notification, NOW + 301)
        await _run(redis, billing, user_service, notification, NOW + 362)

        assert notification.notify_user.await_count == 1

    async def test_the_same_payment_queued_twice_still_sends_once(self):
        redis = KvRedis()
        payment_id = await _schedule(redis)
        await _schedule(redis, payment_id=payment_id, now=NOW + 1)
        user_service, notification = _services()

        await _run(redis, _billing(), user_service, notification, NOW + 400)

        assert notification.notify_user.await_count == 1


class TestNeverSent:
    @pytest.mark.parametrize("status", ["COMPLETED", "CANCELED", "FAILED", "REFUNDED"])
    async def test_payment_that_is_no_longer_pending(self, status):
        redis = KvRedis()
        await _schedule(redis)
        user_service, notification = _services()

        sent = await _run(
            redis, _billing(_transaction(status)), user_service, notification, NOW + 301
        )

        assert sent == 0
        notification.notify_user.assert_not_awaited()

    async def test_unknown_payment(self):
        redis = KvRedis()
        await _schedule(redis)
        user_service, notification = _services()
        billing = _billing()
        billing.get_transaction.return_value = None

        assert await _run(redis, billing, user_service, notification, NOW + 301) == 0

    async def test_user_who_paid_another_payment_since(self):
        redis = KvRedis()
        await _schedule(redis)
        user_service, notification = _services()
        later = datetime.fromtimestamp(NOW + 60, tz=timezone.utc)
        billing = _billing(history=[_transaction("COMPLETED", created_at=later)])

        sent = await _run(redis, billing, user_service, notification, NOW + 301)

        assert sent == 0
        notification.notify_user.assert_not_awaited()

    async def test_an_older_completed_payment_does_not_block(self):
        redis = KvRedis()
        await _schedule(redis)
        user_service, notification = _services()
        earlier = datetime.fromtimestamp(NOW, tz=timezone.utc) - timedelta(days=30)
        billing = _billing(history=[_transaction("COMPLETED", created_at=earlier)])

        sent = await _run(redis, billing, user_service, notification, NOW + 301)

        assert sent == 1

    async def test_only_the_newest_payment_of_a_user_is_nudged(self):
        redis = KvRedis()
        first = await _schedule(redis, now=NOW)
        second = await _schedule(redis, now=NOW + 40)
        user_service, notification = _services()
        billing = _billing()

        sent = await _run(redis, billing, user_service, notification, NOW + 400)

        assert sent == 1
        url_checked = [c.args[0] for c in billing.get_transaction.await_args_list]
        assert str(second) in {str(u) for u in url_checked}
        assert str(first) not in {str(u) for u in url_checked}

    async def test_user_who_got_a_nudge_recently_gets_no_second_one(self):
        redis = KvRedis()
        await _schedule(redis, now=NOW)
        user_service, notification = _services()
        await _run(redis, _billing(), user_service, notification, NOW + 301)
        await _schedule(redis, now=NOW + 400)

        sent = await _run(redis, _billing(), user_service, notification, NOW + 701)

        assert sent == 0
        assert notification.notify_user.await_count == 1

    async def test_blocked_user(self):
        redis = KvRedis()
        await _schedule(redis)
        user = make_user(telegram_id=TG)
        object.__setattr__(user, "is_bot_blocked", True)
        user_service, notification = _services(user)

        sent = await _run(redis, _billing(), user_service, notification, NOW + 301)

        assert sent == 0
        notification.notify_user.assert_not_awaited()

    async def test_unknown_user(self):
        redis = KvRedis()
        await _schedule(redis)
        user_service, notification = _services()
        user_service.get.return_value = None

        assert await _run(redis, _billing(), user_service, notification, NOW + 301) == 0

    async def test_a_run_long_after_the_due_time_stays_silent(self):
        redis = KvRedis()
        await _schedule(redis)
        user_service, notification = _services()

        sent = await _run(
            redis,
            _billing(),
            user_service,
            notification,
            NOW + NUDGE_DELAY_SECONDS + MAX_LATENESS_SECONDS + 1,
        )

        assert sent == 0
        notification.notify_user.assert_not_awaited()


class TestFailures:
    async def test_billing_error_does_not_stop_the_other_payments(self):
        redis = KvRedis()
        await _schedule(redis, telegram_id=1, now=NOW)
        ok_payment = await _schedule(redis, telegram_id=2, now=NOW + 1)
        user_service = AsyncMock()
        user_service.get.side_effect = lambda telegram_id: make_user(telegram_id=telegram_id)
        notification = AsyncMock()
        notification.notify_user.return_value = MagicMock(message_id=1)
        billing = _billing()
        calls = {"n": 0}

        async def flaky(payment_id):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("billing down")
            return _transaction()

        billing.get_transaction.side_effect = flaky

        sent = await _run(redis, billing, user_service, notification, NOW + 400)

        assert sent == 1
        assert ok_payment

    async def test_failed_send_is_retried_on_the_next_run_without_a_double_send(self):
        redis = KvRedis()
        await _schedule(redis)
        user_service, notification = _services()
        notification.notify_user.side_effect = [RuntimeError("telegram down"), MagicMock()]
        billing = _billing()

        first = await _run(redis, billing, user_service, notification, NOW + 301)
        second = await _run(redis, billing, user_service, notification, NOW + 450)

        assert (first, second) == (0, 1)
        assert notification.notify_user.await_count == 2


class TestStarsOnly:
    @pytest.mark.parametrize("gateway", ["PLATEGA", "PLATEGA_CRYPTO", "YOOKASSA", "TON", ""])
    async def test_a_pending_non_stars_payment_is_never_nudged(self, gateway):
        # A Platega link queued before the Stars-only release must not be resent by the bot.
        redis = KvRedis()
        await _schedule(redis)
        user_service, notification = _services()

        sent = await _run(
            redis, _billing(_transaction(gateway=gateway)), user_service, notification, NOW + 301
        )

        assert sent == 0
        notification.notify_user.assert_not_awaited()


class TestKeyboardAndCopy:
    def test_keyboard_has_only_the_stars_pay_link(self):
        keyboard = get_payment_nudge_keyboard(URL)

        flat = [b for row in keyboard.inline_keyboard for b in row]
        assert [(b.text, b.url, b.callback_data) for b in flat] == [
            ("btn-payment-nudge-pay", URL, None),
        ]

    def test_callback_data_fits_telegram_limit(self):
        keyboard = get_payment_nudge_keyboard(URL)

        for row in keyboard.inline_keyboard:
            for button in row:
                assert len((button.callback_data or "").encode()) <= 64

    def test_copy_renders(self):
        hub = TranslatorHub(
            {"ru": ("ru",)},
            root_locale="ru",
            storage=FileStorage(path=Path("assets/translations") / "{locale}"),
        )
        i18n = hub.get_translator_by_locale("ru")

        text = i18n.get("ntf-payment-nudge", plan="⚡️ Старт", price="119 ★")

        assert "119 ★" in text and "Старт" in text
        assert "звёздами" in text
        for banned in ("банк", "другой способ", "₽", "карт"):
            assert banned not in text.lower()
        assert i18n.get("btn-payment-nudge-pay") == "⭐ Оплатить звёздами"


class TestChargedButNotYetCompleted:
    # Telegram took the stars, billing's Kafka consumer has not completed the payment yet (it can
    # lag or stall). The payment is still PENDING, but the user has paid: «Оплата не завершена» with
    # the same link would be wrong, and it invites a second payment.
    async def test_a_charged_payment_gets_no_nudge(self):
        redis = KvRedis()
        payment_id = await _schedule(redis)
        await redis.set(f"stars_charge:{payment_id}", "stx-1")
        user_service, notification = _services()

        sent = await _run(redis, _billing(), user_service, notification, NOW + 301)

        assert sent == 0
        notification.notify_user.assert_not_awaited()
