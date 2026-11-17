"""E2E edge cases of the Stars-only checkout: a free (0 star) order, an old «Другой способ» nudge
button, and repeated taps. Opt-in like the other e2e modules (see test_stars_only_e2e.py).
"""

from __future__ import annotations

import asyncio
import copy
import os
import time

import pytest
import pytest_asyncio

pytest.importorskip("tgmock")

from .fake_billing import STAGE  # noqa: E402
from .harness import DEV_ID, ShopE2E, redis_server_binary  # noqa: E402
from .test_stale_callback_e2e import (  # noqa: E402
    _bot_message,
    _next_update_id,
    _user,
    buttons,
    callback_update,
    send,
    show,
    tap,
    user_screens,
    wait_screen,
)
from .test_stars_only_e2e import (  # noqa: E402
    PROD_ROWS,
    RUBLE_NOTE,
    _pre_checkout,
    _text_update,
    assert_stars_only,
    open_plans,
    stars_checkout,
)

if not os.environ.get("SHOP_E2E") or not redis_server_binary():
    pytest.skip("set SHOP_E2E=1 and provide a redis-server to run the e2e", allow_module_level=True)

pytestmark = pytest.mark.asyncio(loop_scope="module")

FREE = 820000001  # 100% purchase discount: the order costs 0 stars
NUDGE = 820000002  # taps «Другой способ» on a reminder sent before the Stars-only release
TAPS = 820000003  # taps the same duration twice
BUSY = 820000004  # sends a message a moment before Telegram reports the payment
BLIP = 820000005  # pays while billing cannot answer for a moment (restart, deploy)
SLOW = 820000006  # pays while billing's Kafka consumer is slower than the bot waits
REFUSED = 820000007  # billing cancelled the payment and Telegram refuses the refund
FORGE = 820000008  # presses a plan button carrying the id of a plan not offered to them

HIDDEN_PLAN_ID = 77  # an archived plan: in billing, not offered to anyone, cheaper than Старт
OLD_PLATEGA_PAYMENT = "3d0c8f62-6a52-4a8e-9a55-6d1b2b0c1a01"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def shop():
    e2e = ShopE2E()
    e2e.billing.gateways.extend(PROD_ROWS)
    e2e.billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid in (FREE, NUDGE, TAPS, BUSY, BLIP, SLOW, REFUSED, FORGE):
        e2e.billing.add_user(uid, f"u{uid}")
    e2e.billing.discounts[FREE] = 100
    hidden = copy.deepcopy(STAGE["plans_available"][0])
    hidden.update(ID=HIDDEN_PLAN_ID, Name="Архив", IsActive=False, Availability="ALLOWED")
    for duration in hidden["Durations"]:
        duration["PlanID"] = HIDDEN_PLAN_ID
        for price in duration["Prices"]:
            price["Price"] = "1.00"
    e2e.billing.hidden_plans.append(hidden)
    e2e.billing.add_transaction(OLD_PLATEGA_PAYMENT, NUDGE, "PLATEGA")
    tx = e2e.billing.transactions[OLD_PLATEGA_PAYMENT]
    tx["Status"] = "PENDING"
    tx["Plan"] = {"id": 1, "name": "⚡️ Старт", "tag": None, "type": "BOTH", "duration": 30}
    try:
        await e2e.start()
        yield e2e
    finally:
        await e2e.stop()
        print(f"\n--- shop log: {e2e.log_path}")


async def test_free_order_needs_no_invoice_and_completes(shop: ShopE2E) -> None:
    plans = await open_plans(shop, FREE)
    durations = await tap(shop, plans, "Старт")
    show("free durations", durations)
    assert_stars_only(durations)
    invoices = len(shop.tg.invoices)
    confirm = await tap(shop, durations, "1 месяц")
    show("free confirm", confirm)
    assert_stars_only(confirm)
    assert len(shop.tg.invoices) == invoices, "a 0-star order must not get a Stars invoice"
    assert RUBLE_NOTE not in (confirm.get("text") or "")
    get = await tap(shop, confirm, "Получить бесплатно")
    show("after free", get)
    created = shop.billing.created[-1]
    assert created["gateway_type"] == "TELEGRAM_STARS"
    # Billing completes a 0-price payment by itself; the button is only a backup.
    assert await shop.wait_for(
        lambda: shop.billing.transactions[created["ID"]]["Status"] == "COMPLETED", timeout=10
    )
    assert get is not None


async def test_plan_not_offered_cannot_be_bought_by_id(shop: ShopE2E) -> None:
    # The plan Select passes whatever item id the callback carries, and the handler read any plan
    # by id. A press carrying the id of a plan not in the user's list (an older message, a modified
    # client) started a checkout for it: an inactive or user-restricted plan (billing's
    # CreatePayment checks neither), the proxy plan (recorded undiscounted while the invoice used
    # the user's discount) or the trial plan (0 stars, billing completes it by itself).
    plans = await open_plans(shop, FORGE)
    start = next(b for b in buttons(plans) if "Старт" in b.get("text", ""))
    prefix, _, item = start["callback_data"].rpartition(":")
    assert item == "1", start["callback_data"]
    message = _bot_message(
        plans["message_id"], plans.get("text", ""), plans.get("reply_markup"), FORGE
    )
    created = len(shop.billing.created)
    invoices = len(shop.tg.invoices)
    since = await send(shop, callback_update(f"{prefix}:{HIDDEN_PLAN_ID}", message))
    await shop.wait_for(lambda: user_screens(shop, since, FORGE), timeout=3)
    screens = user_screens(shop, since, FORGE)
    if screens and any("1 месяц" in b.get("text", "") for b in buttons(screens[-1])):
        await tap(shop, screens[-1], "1 месяц")  # the old code opened the hidden plan's durations
    await send(shop, callback_update(f"{prefix}:4", message))  # the trial plan
    await asyncio.sleep(3)
    bought = [
        (c["plan_id"], c.get("duration_days"))
        for c in shop.billing.created[created:]
        if int(c["plan_id"]) in (HIDDEN_PLAN_ID, 4)
    ]
    print("\n[payments for plans not offered]", bought)
    assert not bought, f"a plan not offered to the user was bought by id: {bought}"
    assert len(shop.tg.invoices) == invoices


async def test_old_other_method_button_opens_the_stars_checkout(shop: ShopE2E) -> None:
    since = time.time()
    old = _bot_message(
        900001,
        "Оплата не завершена",
        {
            "inline_keyboard": [
                [{"text": "🔄 Другой способ", "callback_data": f"pn:{OLD_PLATEGA_PAYMENT}"}]
            ]
        },
        NUDGE,
    )
    await send(shop, callback_update(f"pn:{OLD_PLATEGA_PAYMENT}", old))
    screen = await wait_screen(shop, since, NUDGE)
    show("old pn: button", screen)
    assert_stars_only(screen)
    assert RUBLE_NOTE in (screen.get("text") or "")
    invoices = len(shop.tg.invoices)
    confirm = await tap(shop, screen, "Telegram Stars")
    stars_checkout(shop, confirm, invoices)


async def test_tapping_the_same_duration_twice_reuses_one_invoice(shop: ShopE2E) -> None:
    plans = await open_plans(shop, TAPS)
    durations = await tap(shop, plans, "Про")
    invoices = len(shop.tg.invoices)
    created = len(shop.billing.created)
    confirm = await tap(shop, durations, "1 месяц")
    first = stars_checkout(shop, confirm, invoices)
    back = await tap(shop, confirm, "Изменить длительность")
    confirm2 = await tap(shop, back, "1 месяц")
    show("second tap", confirm2)
    assert_stars_only(confirm2)
    assert len(shop.billing.created) == created + 1, "the same order must not be created twice"
    await asyncio.sleep(0)
    assert first["payload"] in shop.billing.transactions
    assert not [s for s in user_screens(shop, 0, TAPS) if "₽" in (s.get("text") or "")]


async def test_hidden_free_button_on_a_paid_order_completes_nothing(shop: ShopE2E) -> None:
    # aiogram-dialog runs a button's handler even when `when` hides it. «Получить бесплатно»
    # (purchase_get) pressed on the confirm screen of a paid order, from an older message or a
    # modified client, must not get that order through handle-free without paying.
    plans = await open_plans(shop, TAPS)
    durations = await tap(shop, plans, "Макс")
    invoices = len(shop.tg.invoices)
    confirm = await tap(shop, durations, "1 месяц")
    invoice = stars_checkout(shop, confirm, invoices)
    any_button = next(
        b for b in confirm["reply_markup"]["inline_keyboard"][-1] if "callback_data" in b
    )
    intent = any_button["callback_data"].split("\x1d")[0]
    message = _bot_message(
        confirm["message_id"], confirm.get("text", ""), confirm.get("reply_markup"), TAPS
    )
    await send(shop, callback_update(f"{intent}\x1dpurchase_get", message))
    await asyncio.sleep(3)
    assert invoice["payload"] not in shop.billing.completed, "a paid order was completed for free"
    assert shop.billing.transactions[invoice["payload"]]["Status"] == "PENDING"


async def test_payment_right_after_another_message_still_reaches_billing(shop: ShopE2E) -> None:
    # The throttling middleware drops any message that comes within 0.5 s of the user's previous
    # message or tap. A successful_payment is a message too: dropped, the stars stay taken and
    # billing never hears of the order (no handle-free, no refund, no alert).
    plans = await open_plans(shop, BUSY)
    durations = await tap(shop, plans, "Старт")
    invoices = len(shop.tg.invoices)
    confirm = await tap(shop, durations, "1 месяц")
    invoice = stars_checkout(shop, confirm, invoices)
    assert _ok(await _pre_checkout(shop, BUSY, invoice))
    await asyncio.sleep(1)  # past the throttle window of the taps above
    await send(shop, _text_update(BUSY, "/start"))
    # Straight away, without the 1 s pause `send` keeps for the throttle.
    payment = {
        "update_id": _next_update_id(),
        "message": {
            "message_id": 1,
            "from": _user(BUSY),
            "chat": {"id": BUSY, "type": "private"},
            "date": int(time.time()),
            "successful_payment": {
                "currency": "XTR",
                "total_amount": invoice["prices"][0]["amount"],
                "invoice_payload": invoice["payload"],
                "telegram_payment_charge_id": "stxe2e-busy",
                "provider_payment_charge_id": "",
            },
        },
    }
    assert await shop.send_update(payment) == 200
    assert await shop.wait_for(lambda: invoice["payload"] in shop.billing.completed, timeout=10), (
        "the payment message was dropped: stars taken, billing never asked to complete the order"
    )
    assert await shop.wait_for(
        lambda: shop.billing.transactions[invoice["payload"]]["Status"] == "COMPLETED", timeout=10
    )


async def test_payment_while_billing_blips_still_reaches_billing(shop: ShopE2E) -> None:
    # The user middleware loads the user from billing before any handler runs. A short billing
    # outage (a restart) used to fail it: the successful_payment handler with its own retries never
    # ran, the alert named no payment, and the stars stayed taken with no order.
    plans = await open_plans(shop, BLIP)
    durations = await tap(shop, plans, "Старт")
    invoices = len(shop.tg.invoices)
    confirm = await tap(shop, durations, "1 месяц")
    invoice = stars_checkout(shop, confirm, invoices)
    assert _ok(await _pre_checkout(shop, BLIP, invoice))
    await asyncio.sleep(1)
    # Every update writes the user back (PUT /users/<id>); the read is usually cached in Redis.
    shop.billing.fail_next[f"PUT /users/{BLIP}"] = 2
    payment = {
        "update_id": _next_update_id(),
        "message": {
            "message_id": 1,
            "from": _user(BLIP),
            "chat": {"id": BLIP, "type": "private"},
            "date": int(time.time()),
            "successful_payment": {
                "currency": "XTR",
                "total_amount": invoice["prices"][0]["amount"],
                "invoice_payload": invoice["payload"],
                "telegram_payment_charge_id": "stxe2e-blip",
                "provider_payment_charge_id": "",
            },
        },
    }
    assert await shop.send_update(payment) == 200
    assert await shop.wait_for(lambda: invoice["payload"] in shop.billing.completed, timeout=15), (
        "billing blipped while loading the user: stars taken, the order never reached billing"
    )
    assert await shop.wait_for(
        lambda: shop.billing.transactions[invoice["payload"]]["Status"] == "COMPLETED", timeout=10
    )
    assert not shop.billing.fail_next[f"PUT /users/{BLIP}"], "the billing outage never happened"


async def test_payment_billing_completes_late_tells_the_user_not_to_pay_again(
    shop: ShopE2E,
) -> None:
    # Billing's consumer takes longer than the bot's ~20 s wait. The stars stay (billing will
    # complete it), the admins get #EventError, and the user must hear that the money arrived:
    # otherwise they see only the main menu and may buy the same plan a second time.
    shop.billing.completion_delay = 28
    try:
        plans = await open_plans(shop, SLOW)
        durations = await tap(shop, plans, "Старт")
        invoices = len(shop.tg.invoices)
        confirm = await tap(shop, durations, "1 месяц")
        invoice = stars_checkout(shop, confirm, invoices)
        assert _ok(await _pre_checkout(shop, SLOW, invoice))
        await asyncio.sleep(1)
        since = time.time()
        payment = {
            "update_id": _next_update_id(),
            "message": {
                "message_id": 1,
                "from": _user(SLOW),
                "chat": {"id": SLOW, "type": "private"},
                "date": int(time.time()),
                "successful_payment": {
                    "currency": "XTR",
                    "total_amount": invoice["prices"][0]["amount"],
                    "invoice_payload": invoice["payload"],
                    "telegram_payment_charge_id": "stxe2e-slow",
                    "provider_payment_charge_id": "",
                },
            },
        }
        assert await shop.send_update(payment) == 200

        def told() -> list[str]:
            return [
                str(c["data"].get("text", ""))
                for c in shop.tg.calls_of("sendMessage", since)
                if str(c["data"].get("chat_id")) == str(SLOW)
            ]

        assert await shop.wait_for(lambda: any("не нужно" in t for t in told()), timeout=30), (
            f"the user paid and was told nothing while billing was slow: {told()}"
        )
        assert shop.billing.transactions[invoice["payload"]]["Status"] == "PENDING"
        assert not shop.tg.calls_of("refundStarPayment", since)
        assert await shop.wait_for(
            lambda: shop.billing.transactions[invoice["payload"]]["Status"] == "COMPLETED", 15
        )
        assert not shop.tg.calls_of("refundStarPayment", since)
        print("\n[told the user]", [t for t in told() if "не нужно" in t])
    finally:
        shop.billing.completion_delay = 0.7


async def test_refund_telegram_refuses_alerts_admins_with_the_charge(shop: ShopE2E) -> None:
    # Billing cancelled the payment (30-minute timeout) just before Telegram took the stars, and
    # Telegram then refuses the refund. Only a person can send the stars back, so the admin alert
    # must name the Telegram charge id; before, it carried only Telegram's error text.
    plans = await open_plans(shop, REFUSED)
    durations = await tap(shop, plans, "Старт")
    invoices = len(shop.tg.invoices)
    confirm = await tap(shop, durations, "1 месяц")
    invoice = stars_checkout(shop, confirm, invoices)
    assert _ok(await _pre_checkout(shop, REFUSED, invoice))
    shop.billing.transactions[invoice["payload"]]["Status"] = "CANCELED"
    shop.tg.failures["refundStarPayment"] = (400, "Bad Request: CHARGE_NOT_FOUND")
    await asyncio.sleep(1)
    since = time.time()
    try:
        payment = {
            "update_id": _next_update_id(),
            "message": {
                "message_id": 1,
                "from": _user(REFUSED),
                "chat": {"id": REFUSED, "type": "private"},
                "date": int(time.time()),
                "successful_payment": {
                    "currency": "XTR",
                    "total_amount": invoice["prices"][0]["amount"],
                    "invoice_payload": invoice["payload"],
                    "telegram_payment_charge_id": "stxe2e-refused",
                    "provider_payment_charge_id": "",
                },
            },
        }
        assert await shop.send_update(payment) == 200

        def alerts() -> list[str]:
            # #EventError goes to the dev chat as a message or, with the traceback, a document.
            return [
                str(c["data"])
                for c in shop.tg.calls
                if c["at"] >= since
                and c["method"] != "refundStarPayment"
                and str(c["data"].get("chat_id")) == str(DEV_ID)
            ]

        assert await shop.wait_for(lambda: shop.tg.calls_of("refundStarPayment", since), 15)
        assert await shop.wait_for(
            lambda: any("stxe2e-refused" in a for a in alerts()), timeout=15
        ), f"the failed refund alert names no charge: {alerts()}"
        print("\n[admin alert]", [a for a in alerts() if "stxe2e-refused" in a][0][:400])
    finally:
        shop.tg.failures.pop("refundStarPayment", None)


def _ok(answer: dict) -> bool:
    return str(answer.get("ok")).lower() in ("true", "1")
