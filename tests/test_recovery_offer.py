"""One targeted 30% first-month offer for users we would otherwise lose."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiogram.types import Message
from fluentogram import TranslatorHub
from fluentogram.storage import FileStorage

from src.bot.routers.extra.recovery_offer import on_recovery_offer_accept
from src.bot.states import Subscription
from src.core.constants import RECOVERY_OFFER_PREFIX
from src.core.metrics import RECOVERY_OFFER_SENT_TOTAL
from src.core.storage.keys import PendingRecoveryOffersKey
from src.infrastructure.billing.client import BillingClientError
from src.infrastructure.billing.models import BillingPlan, BillingPlanDuration
from src.services.payment_nudge import (
    OFFER_DELAY_SECONDS,
    process_due_payment_offers,
    schedule_payment_nudge,
)
from src.services.recovery_offer import (
    DEDUP_KEY,
    KIND,
    PROMO_CODE,
    OfferActivation,
    activate_offer,
    claim_offer,
    get_recovery_offer_keyboard,
    has_paid,
    release_offer,
)
from tests.conftest import make_dialog_manager, make_i18n, make_user, unwrap_inject
from tests.reminder_fakes import FakeBilling, KvRedis

TG = 4242
NOW = 1_800_000_000.0
REF = (TG, KIND, DEDUP_KEY)


def _tx(status="COMPLETED", amount="119", created_at=None):
    return SimpleNamespace(
        Status=status,
        GatewayType="PLATEGA",
        CreatedAt=created_at or datetime.fromtimestamp(NOW, tz=timezone.utc),
        Pricing=SimpleNamespace(final_amount=amount),
        PurchaseType="NEW",
        UserTelegramID=TG,
        Plan=SimpleNamespace(id=1, duration=30),
    )


def _user(telegram_id=TG):
    return make_user(telegram_id=telegram_id)


class TestHasPaid:
    async def test_new_user_has_not_paid(self):
        assert await has_paid(FakeBilling(), TG) is False

    async def test_a_completed_payment_counts(self):
        billing = FakeBilling()
        billing.transactions[TG] = [_tx("COMPLETED", "119")]

        assert await has_paid(billing, TG) is True

    async def test_cancelled_pending_and_free_grants_do_not_count(self):
        billing = FakeBilling()
        billing.transactions[TG] = [_tx("CANCELED"), _tx("PENDING"), _tx("COMPLETED", "0")]

        assert await has_paid(billing, TG) is False

    async def test_an_active_paid_subscription_counts(self):
        billing = FakeBilling()
        billing.current_subscriptions[TG] = SimpleNamespace(Status="ACTIVE", IsTrial=False)

        assert await has_paid(billing, TG) is True

    async def test_an_active_trial_does_not_count(self):
        billing = FakeBilling()
        billing.current_subscriptions[TG] = SimpleNamespace(Status="ACTIVE", IsTrial=True)

        assert await has_paid(billing, TG) is False


class TestClaim:
    async def test_first_claim_wins_and_the_second_is_refused(self):
        billing = FakeBilling()

        assert await claim_offer(billing, _user()) is True
        assert await claim_offer(billing, _user()) is False
        assert REF in billing.claims

    async def test_a_user_who_paid_is_never_claimed(self):
        billing = FakeBilling()
        billing.transactions[TG] = [_tx()]

        assert await claim_offer(billing, _user()) is False
        assert billing.claims == {}

    async def test_billing_errors_mean_no_offer(self):
        billing = FakeBilling()
        billing.claim_error = RuntimeError("down")

        assert await claim_offer(billing, _user()) is False

    async def test_release_frees_the_claim(self):
        billing = FakeBilling()
        await claim_offer(billing, _user())

        await release_offer(billing, TG)

        assert REF not in billing.claims


class TestActivate:
    async def test_activates_the_one_code(self):
        billing = FakeBilling()

        assert await activate_offer(billing, TG) is OfferActivation.ACTIVATED
        assert billing.activated == [(PROMO_CODE, TG)]

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (409, OfferActivation.ACTIVATED),
            (403, OfferActivation.UNAVAILABLE),
            (404, OfferActivation.UNAVAILABLE),
        ],
    )
    async def test_billing_answers(self, status, expected):
        billing = FakeBilling()
        billing.activate_error = BillingClientError(status, "x")

        assert await activate_offer(billing, TG) is expected

    async def test_other_errors_are_reported_as_failed(self):
        billing = FakeBilling()
        billing.activate_error = BillingClientError(500, "boom")

        assert await activate_offer(billing, TG) is OfferActivation.FAILED


class TestKeyboard:
    def test_one_button_carries_the_payment(self):
        keyboard = get_recovery_offer_keyboard("pid")

        flat = [b for row in keyboard.inline_keyboard for b in row]
        assert [(b.text, b.callback_data) for b in flat] == [
            ("btn-recovery-offer-accept", f"{RECOVERY_OFFER_PREFIX}pid")
        ]

    def test_without_a_payment_the_marker_is_a_dash(self):
        keyboard = get_recovery_offer_keyboard(None)

        assert keyboard.inline_keyboard[0][0].callback_data == f"{RECOVERY_OFFER_PREFIX}-"


def _services(user=None):
    user_service = AsyncMock()
    user_service.get.return_value = user if user is not None else _user()
    notification = AsyncMock()
    notification.notify_user.return_value = MagicMock(message_id=1)
    return user_service, notification


async def _schedule(redis, payment_id=None, telegram_id=TG, now=NOW):
    payment_id = payment_id or str(uuid4())
    await schedule_payment_nudge(
        redis,
        payment_id=payment_id,
        telegram_id=telegram_id,
        payment_url="https://pay.example/1",
        plan_name="⚡️ Старт",
        price_text="119 ₽",
        now=now,
    )
    return payment_id


class _Billing(FakeBilling):
    def __init__(self, status="PENDING"):
        super().__init__()
        self.status = status

    async def get_transaction(self, payment_id):
        return _tx(self.status, "119")


async def _offers(redis, billing, user_service, notification, now):
    return await process_due_payment_offers(
        redis_client=redis,
        billing=billing,
        user_service=user_service,
        notification_service=notification,
        now=now,
    )


class TestAbandonedPaymentOffer:
    async def test_scheduling_queues_the_offer_fifteen_minutes_out(self):
        redis = KvRedis()

        payment_id = await _schedule(redis)

        assert OFFER_DELAY_SECONDS == 900
        assert redis.zsets[PendingRecoveryOffersKey().pack()] == {f"{payment_id}:{TG}": NOW + 900}

    @pytest.mark.parametrize("status", ["PENDING", "CANCELED"])
    async def test_abandoned_payment_gets_the_offer_once(self, status):
        redis = KvRedis()
        payment_id = await _schedule(redis)
        billing = _Billing(status)
        user_service, notification = _services()
        before = RECOVERY_OFFER_SENT_TOTAL.labels(source="payment")._value.get()

        first = await _offers(redis, billing, user_service, notification, NOW + 901)
        second = await _offers(redis, billing, user_service, notification, NOW + 960)

        assert (first, second) == (1, 0)
        payload = notification.notify_user.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-recovery-offer"
        assert payload.auto_delete_after is None
        assert payload.add_close_button is False
        button = payload.reply_markup.inline_keyboard[0][0]
        assert button.callback_data == f"{RECOVERY_OFFER_PREFIX}{payment_id}"
        assert REF in billing.claims
        assert RECOVERY_OFFER_SENT_TOTAL.labels(source="payment")._value.get() == before + 1

    async def test_not_before_fifteen_minutes(self):
        redis = KvRedis()
        await _schedule(redis)
        user_service, notification = _services()

        sent = await _offers(redis, _Billing(), user_service, notification, NOW + 899)

        assert sent == 0

    async def test_never_after_the_payment_completed(self):
        redis = KvRedis()
        await _schedule(redis)
        user_service, notification = _services()

        sent = await _offers(redis, _Billing("COMPLETED"), user_service, notification, NOW + 901)

        assert sent == 0
        notification.notify_user.assert_not_awaited()

    async def test_never_to_a_user_who_already_paid(self):
        redis = KvRedis()
        await _schedule(redis)
        billing = _Billing()
        billing.transactions[TG] = [_tx("COMPLETED", "119")]
        user_service, notification = _services()

        sent = await _offers(redis, billing, user_service, notification, NOW + 901)

        assert sent == 0
        assert billing.claims == {}

    async def test_never_twice_even_for_a_second_abandoned_payment(self):
        redis = KvRedis()
        billing = _Billing()
        user_service, notification = _services()
        await _schedule(redis, now=NOW)
        await _offers(redis, billing, user_service, notification, NOW + 901)
        await _schedule(redis, now=NOW + 5000)

        sent = await _offers(redis, billing, user_service, notification, NOW + 5901)

        assert sent == 0
        assert notification.notify_user.await_count == 1

    async def test_only_the_newest_payment_triggers_the_offer(self):
        redis = KvRedis()
        await _schedule(redis, now=NOW)
        newest = await _schedule(redis, now=NOW + 100)
        user_service, notification = _services()

        sent = await _offers(redis, _Billing(), user_service, notification, NOW + 1100)

        assert sent == 1
        button = notification.notify_user.await_args.kwargs["payload"].reply_markup
        assert button.inline_keyboard[0][0].callback_data.endswith(newest)

    async def test_failed_send_releases_the_claim_and_retries(self):
        redis = KvRedis()
        await _schedule(redis)
        billing = _Billing()
        user_service, notification = _services()
        notification.notify_user.side_effect = [RuntimeError("telegram down"), MagicMock()]

        first = await _offers(redis, billing, user_service, notification, NOW + 901)
        assert first == 0
        assert REF not in billing.claims
        second = await _offers(redis, billing, user_service, notification, NOW + 1000)

        assert second == 1

    async def test_blocked_user_is_skipped(self):
        redis = KvRedis()
        await _schedule(redis)
        user = _user()
        object.__setattr__(user, "is_bot_blocked", True)
        user_service, notification = _services(user)

        sent = await _offers(redis, _Billing(), user_service, notification, NOW + 901)

        assert sent == 0
        notification.notify_user.assert_not_awaited()


def _callback(data: str) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=Message)
    callback.message.edit_reply_markup = AsyncMock()
    return callback


def _dm() -> MagicMock:
    dm = make_dialog_manager()
    dm.start = AsyncMock()
    dm.update = AsyncMock()
    return dm


def _router_billing(activation_error=None, plan=True):
    billing = AsyncMock()
    billing.activate_promocode.side_effect = activation_error
    billing.get_transaction.return_value = _tx("PENDING")
    billing.get_plan.return_value = (
        BillingPlan(ID=1, Name="Старт", Type="BOTH", Durations=[BillingPlanDuration(ID=1, Days=30)])
        if plan
        else None
    )
    return billing


class TestAcceptButton:
    async def test_from_an_abandoned_payment_opens_that_plans_durations(self):
        dm, billing = _dm(), _router_billing()
        callback = _callback(f"{RECOVERY_OFFER_PREFIX}{uuid4()}")

        raw = unwrap_inject(on_recovery_offer_accept)
        await raw(callback, _user(), dm, billing, make_i18n())

        billing.activate_promocode.assert_awaited_once_with(code=PROMO_CODE, telegram_id=TG)
        assert dm.start.await_args.args[0] == Subscription.DURATION
        seeded = dm.update.await_args.args[0]
        assert seeded["plandto"]["id"] == 1
        assert seeded["only_single_plan"] is False

    async def test_from_the_expired_notice_opens_the_plan_list(self):
        dm, billing = _dm(), _router_billing()
        callback = _callback(f"{RECOVERY_OFFER_PREFIX}-")

        raw = unwrap_inject(on_recovery_offer_accept)
        await raw(callback, _user(), dm, billing, make_i18n())

        assert dm.start.await_args.args[0] == Subscription.PLANS
        assert "plandto" not in dm.update.await_args.args[0]
        billing.get_transaction.assert_not_awaited()

    async def test_a_second_tap_still_opens_checkout(self):
        dm = _dm()
        billing = _router_billing(BillingClientError(409, "already"))

        raw = unwrap_inject(on_recovery_offer_accept)
        await raw(_callback(f"{RECOVERY_OFFER_PREFIX}-"), _user(), dm, billing, make_i18n())

        dm.start.assert_awaited_once()

    async def test_a_user_who_paid_meanwhile_is_told_the_offer_is_gone(self):
        dm = _dm()
        billing = _router_billing(BillingClientError(403, "not eligible"))
        callback = _callback(f"{RECOVERY_OFFER_PREFIX}-")

        raw = unwrap_inject(on_recovery_offer_accept)
        await raw(callback, _user(), dm, billing, make_i18n())

        dm.start.assert_not_awaited()
        callback.answer.assert_awaited_once_with(
            text="[msg-recovery-offer-unavailable]", show_alert=True
        )
        callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)

    async def test_billing_failure_keeps_the_button_and_says_try_again(self):
        dm = _dm()
        billing = _router_billing(BillingClientError(500, "boom"))
        callback = _callback(f"{RECOVERY_OFFER_PREFIX}-")

        raw = unwrap_inject(on_recovery_offer_accept)
        await raw(callback, _user(), dm, billing, make_i18n())

        dm.start.assert_not_awaited()
        callback.answer.assert_awaited_once_with(
            text="[msg-recovery-offer-failed]", show_alert=True
        )
        callback.message.edit_reply_markup.assert_not_awaited()


@pytest.fixture(scope="module")
def i18n():
    hub = TranslatorHub(
        {"ru": ("ru",)},
        root_locale="ru",
        storage=FileStorage(path=Path("assets/translations") / "{locale}"),
    )
    return hub.get_translator_by_locale("ru")


class TestCopy:
    def test_offer_texts_say_30_percent_first_month_once(self, i18n):
        for key in ("ntf-recovery-offer", "ntf-event-user-expired-offer"):
            text = i18n.get(key)
            assert "30%" in text and "первый месяц" in text
            assert "один раз" in text or "одноразов" in text

    def test_buttons_and_replies(self, i18n):
        assert "30%" in i18n.get("btn-recovery-offer-accept")
        for key in ("msg-recovery-offer-unavailable", "msg-recovery-offer-failed"):
            assert i18n.get(key) != key

    def test_no_message_asks_users_to_type_the_blanket_code(self):
        root = Path("assets/translations/ru")
        text = "".join(p.read_text(encoding="utf-8") for p in root.glob("*.ftl"))
        assert "COMPONO30" not in text


class TestChargedButNotYetCompletedOffer:
    # The user paid, billing has not completed the payment yet: offering 30% off a new payment
    # 15 minutes later makes them pay twice.
    async def test_a_charged_payment_gets_no_offer(self):
        redis = KvRedis()
        payment_id = await _schedule(redis)
        await redis.set(f"stars_charge:{payment_id}", "stx-1")
        billing = _Billing("PENDING")
        user_service, notification = _services()

        sent = await _offers(redis, billing, user_service, notification, NOW + 901)

        assert sent == 0
        notification.notify_user.assert_not_awaited()
        assert REF not in billing.claims
