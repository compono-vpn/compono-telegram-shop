"""E2E: the bot sells only for Telegram Stars (Telegram bot terms 6.2).

Real app against tgmock + the in-memory billing. Billing is given the prod gateway rows on top of
the stage ones (PLATEGA BOT RUB active, PLATEGA_CRYPTO BOT), so these flows prove the bot ignores
every non-Stars row even when billing says it is active. Opt-in, like the other e2e module:

    uv pip install -e ../tgmock
    SHOP_E2E=1 SHOP_E2E_REDIS_SERVER=/opt/homebrew/bin/redis-server uv run pytest tests/e2e -v -s
"""

from __future__ import annotations

import asyncio
import copy
import os
import time
from typing import Any

import pytest
import pytest_asyncio

pytest.importorskip("tgmock")

from .fake_billing import STAGE  # noqa: E402
from .harness import DEV_ID, ShopE2E, redis_server_binary  # noqa: E402
from .test_stale_callback_e2e import (  # noqa: E402
    _bot_message,
    _next_update_id,
    _user,
    admin_alerts,
    buttons,
    callback_update,
    send,
    show,
    tap,
    user_screens,
    wait_screen,
)

if not os.environ.get("SHOP_E2E") or not redis_server_binary():
    pytest.skip("set SHOP_E2E=1 and provide a redis-server to run the e2e", allow_module_level=True)

pytestmark = pytest.mark.asyncio(loop_scope="module")

BUYER = 810000001  # no subscription: plans -> Stars checkout -> successful_payment
PROMO = 810000002  # activates a 30% promo code, then buys
RENEW = 810000003  # paid Старт ending tomorrow, renews from the expiry notice button
PROXY = 810000004  # buys the Pro proxy
ULTRA_BUYER = 810000005  # buys Ultra
ULTRA_OWNER = 810000006  # has Ultra, opens «Выделенный IP»

SUPPORT_URL = "https://t.me/compono_support"
RUBLE_NOTE = "Оплата в рублях сейчас недоступна"
# Nothing a user sees in the bot may name a ruble, card, SBP or crypto payment, or the website.
BANNED = ("₽", "СБП", "Карт", "карт", "крипт", "Platega", "componovpn.com", "/pricing", "/purchase")

PROD_ROWS = [
    {"ID": 107, "OrderIndex": 1, "Type": "PLATEGA", "Channel": "BOT", "Currency": "RUB",
     "IsActive": True, "Settings": None},
    {"ID": 108, "OrderIndex": 1, "Type": "PLATEGA", "Channel": "WEB", "Currency": "RUB",
     "IsActive": True, "Settings": None},
    {"ID": 109, "OrderIndex": 3, "Type": "PLATEGA_CRYPTO", "Channel": "BOT", "Currency": "USDT",
     "IsActive": True, "Settings": None},
]  # fmt: skip


def _ultra_plan() -> dict[str, Any]:
    plan = copy.deepcopy(next(p for p in STAGE["plans_available"] if p["ID"] == 3))
    plan.update(ID=38, Name="👑 Ультра", Tag="ULTRA", OrderIndex=4)
    stars = {30: "799.00", 90: "2199.00", 180: "4199.00", 365: "7699.00"}
    for duration in plan["Durations"]:
        duration["PlanID"] = 38
        for price in duration["Prices"]:
            if price["Currency"] in ("XTR", "RUB"):
                price["Price"] = stars[duration["Days"]]
    return plan


def _proxy_plan() -> dict[str, Any]:
    return {
        "ID": 5,
        "OrderIndex": 9,
        "IsActive": True,
        "Type": "PROXY",
        "Availability": "ALL",
        "Name": "Прокси",
        "TrafficLimit": 0,
        "DeviceLimit": 0,
        "Durations": [
            {
                "ID": 51,
                "PlanID": 5,
                "Days": 30,
                "Prices": [
                    {"ID": 1, "Currency": "RUB", "Price": "49.00"},
                    {"ID": 2, "Currency": "XTR", "Price": "49.00"},
                ],
            }
        ],
    }


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def shop():
    e2e = ShopE2E()
    billing = e2e.billing
    billing.gateways.extend(PROD_ROWS)
    billing.extra_plans.append(_ultra_plan())
    billing.hidden_plans.append(_proxy_plan())
    billing.promocodes["RETURN30"] = 30
    billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid in (BUYER, PROMO, RENEW, PROXY, ULTRA_BUYER, ULTRA_OWNER):
        billing.add_user(uid, f"u{uid}")
    billing.add_active_subscription(RENEW, days_left=1)
    billing.add_active_subscription(ULTRA_OWNER, plan_id=38, plan_name="👑 Ультра", tag="ULTRA")
    billing.personal_proxies[PROXY] = {
        "entitled": False,
        "proxy_plan_id": 5,
        "price_rub": 49,
        "proxies": [
            {"id": 7, "server": "russia.compono.online", "port": 443, "secret": "x",
             "kind": "WEB", "link": "https://t.me/webproxy?server=r&secret=aa", "is_public": True}
        ],
    }  # fmt: skip
    try:
        await e2e.start()
        yield e2e
    finally:
        await e2e.stop()
        print(f"\n--- shop log: {e2e.log_path}")


# ------------------------------------------------------------------ helpers


def _text_update(uid: int, text: str) -> dict[str, Any]:
    update_id = _next_update_id()
    message: dict[str, Any] = {
        "message_id": update_id,
        "from": _user(uid),
        "chat": {"id": uid, "type": "private"},
        "date": int(time.time()),
        "text": text,
    }
    if text.startswith("/"):
        message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    return {"update_id": update_id, "message": message}


def _visible(screen: dict[str, Any]) -> str:
    return (screen.get("text") or "") + " " + " ".join(b.get("text", "") for b in buttons(screen))


def assert_stars_only(screen: dict[str, Any]) -> None:
    visible = _visible(screen)
    for word in BANNED:
        assert word not in visible, f"'{word}' shown to the user: {visible}"
    for button in buttons(screen):
        url = button.get("url") or ""
        assert "platega" not in url and "componovpn.com" not in url, url


async def open_plans(shop: ShopE2E, uid: int) -> dict[str, Any]:
    since = await send(shop, _text_update(uid, "/start"))
    menu = await wait_screen(shop, since, uid)
    sub = await tap(shop, menu, "Подписк")
    show(f"{uid} Подписка", sub)
    return await tap(shop, sub, "Купить")


def stars_checkout(shop: ShopE2E, screen: dict[str, Any], invoices_before: int) -> dict[str, Any]:
    """The confirm screen pays by one Stars invoice link and offers support for rubles."""
    show("confirm", screen)
    assert_stars_only(screen)
    assert RUBLE_NOTE in (screen.get("text") or "")
    by_text = {b.get("text", ""): b for b in buttons(screen)}
    pay = next(b for t, b in by_text.items() if "Оплатить звёздами" in t)
    support = next(b for t, b in by_text.items() if "compono_support" in t)
    assert support["url"] == SUPPORT_URL
    assert len(shop.tg.invoices) == invoices_before + 1
    invoice = shop.tg.invoices[-1]
    assert pay["url"] == invoice["link"]
    assert invoice["currency"] == "XTR"
    return invoice


async def pay_with_stars(shop: ShopE2E, uid: int, invoice: dict[str, Any]) -> None:
    """What Telegram sends after the user pays the invoice: pre_checkout_query, successful_payment."""
    amount = invoice["prices"][0]["amount"]
    started = time.time()
    update_id = _next_update_id()
    await send(
        shop,
        {
            "update_id": update_id,
            "pre_checkout_query": {
                "id": f"pcq-{update_id}",
                "from": _user(uid),
                "currency": "XTR",
                "total_amount": amount,
                "invoice_payload": invoice["payload"],
            },
        },
    )
    assert await shop.wait_for(lambda: shop.tg.calls_of("answerPreCheckoutQuery"), timeout=10)
    update_id = _next_update_id()
    await send(
        shop,
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "from": _user(uid),
                "chat": {"id": uid, "type": "private"},
                "date": int(time.time()),
                "successful_payment": {
                    "currency": "XTR",
                    "total_amount": amount,
                    "invoice_payload": invoice["payload"],
                    "telegram_payment_charge_id": f"stxe2e{update_id}",
                    "provider_payment_charge_id": "",
                },
            },
        },
    )
    assert await shop.wait_for(lambda: invoice["payload"] in shop.billing.completed, timeout=10)
    # Billing completes the payment asynchronously (Kafka); the paid stars must stay paid.
    assert await shop.wait_for(
        lambda: shop.billing.transactions[invoice["payload"]]["Status"] == "COMPLETED", timeout=10
    )
    await asyncio.sleep(3)  # let the handler finish its own completion check
    assert not shop.tg.calls_of("refundStarPayment", started), "a paid order was refunded"
    assert not any(
        "Звёзды вернули" in (s.get("text") or "") for s in user_screens(shop, started, uid)
    )


# ------------------------------------------------------------------ tests


async def test_plans_durations_and_checkout_are_stars_only(shop: ShopE2E) -> None:
    started = time.time()
    plans = await open_plans(shop, BUYER)
    show("plans", plans)
    assert_stars_only(plans)
    assert "119 ★/мес" in plans["text"] and "799 ★/мес" in plans["text"]

    durations = await tap(shop, plans, "Старт")
    show("durations", durations)
    assert_stars_only(durations)
    labels = [b.get("text", "") for b in buttons(durations)]
    for price in ("1 месяц — 119 ★", "3 месяца — 319 ★", "6 месяцев — 579 ★", "1 год — 999 ★"):
        assert any(price in label for label in labels), (price, labels)

    before = len(shop.tg.invoices)
    confirm = await tap(shop, durations, "1 месяц")
    invoice = stars_checkout(shop, confirm, before)
    assert invoice["prices"][0]["amount"] == 119
    created = shop.billing.created[-1]
    assert (created["gateway_type"], created["currency"], created["plan_id"]) == (
        "TELEGRAM_STARS",
        "XTR",
        1,
    )
    assert invoice["payload"] == created["ID"]
    assert {c["gateway_type"] for c in shop.billing.created} == {"TELEGRAM_STARS"}

    await pay_with_stars(shop, BUYER, invoice)
    assert shop.billing.transactions[invoice["payload"]]["Status"] == "COMPLETED"
    assert not admin_alerts(shop, started), admin_alerts(shop, started)


async def test_promo_code_discount_applies_to_the_stars_price(shop: ShopE2E) -> None:
    since = await send(shop, _text_update(PROMO, "/start"))
    menu = await wait_screen(shop, since, PROMO)
    sub = await tap(shop, menu, "Подписк")
    await tap(shop, sub, "промокод")
    since = await send(shop, _text_update(PROMO, "return30"))
    done = await wait_screen(shop, since, PROMO)
    show("promo", done)
    assert shop.billing.discounts[PROMO] == 30

    plans = await open_plans(shop, PROMO)
    show("promo plans", plans)
    assert "🎁 Ваша скидка 30% уже учтена" in plans["text"]
    assert "⚡ <b>Старт</b> — 83 ★/мес" in plans["text"]
    durations = await tap(shop, plans, "Старт")
    assert any("1 месяц — 83 ★" in b.get("text", "") for b in buttons(durations))
    before = len(shop.tg.invoices)
    confirm = await tap(shop, durations, "1 месяц")
    invoice = stars_checkout(shop, confirm, before)
    assert invoice["prices"][0]["amount"] == 83  # 119 * 0.7 = 83.3, billing floors to whole stars


async def test_renewal_from_the_expiry_notice_goes_to_stars(shop: ShopE2E) -> None:
    # The expiring/expired notices carry «🔄 Продлить подписку» = callback gt_purchase_RENEW.
    notice = _bot_message(
        7001,
        "⚠️ Внимание! Ваша подписка закончится через 1 день.",
        {
            "inline_keyboard": [
                [{"text": "🔄 Продлить подписку", "callback_data": "gt_purchase_RENEW"}]
            ]
        },
        RENEW,
    )
    since = await send(shop, callback_update("gt_purchase_RENEW", notice))
    sub = await wait_screen(shop, since, RENEW)
    show("renew sub", sub)
    durations = await tap(shop, sub, "Продлить")
    show("renew durations", durations)
    assert_stars_only(durations)
    before = len(shop.tg.invoices)
    confirm = await tap(shop, durations, "1 месяц")
    invoice = stars_checkout(shop, confirm, before)
    assert invoice["prices"][0]["amount"] == 119
    created = shop.billing.created[-1]
    assert (created["purchase_type"], created["gateway_type"]) == ("RENEW", "TELEGRAM_STARS")
    await pay_with_stars(shop, RENEW, invoice)


async def test_proxy_purchase_uses_a_stars_invoice(shop: ShopE2E) -> None:
    since = await send(shop, _text_update(PROXY, "/start proxy"))
    screen = await wait_screen(shop, since, PROXY)
    show("proxy", screen)
    assert_stars_only(screen)
    assert "49 ★ в месяц" in screen["text"]
    before = len(shop.tg.invoices)
    confirm = await tap(shop, screen, "Pro за 49 ★")
    show("proxy confirm", confirm)
    assert_stars_only(confirm)
    assert RUBLE_NOTE in confirm["text"]
    assert len(shop.tg.invoices) == before + 1
    invoice = shop.tg.invoices[-1]
    assert invoice["currency"] == "XTR" and invoice["prices"][0]["amount"] == 49
    pay = next(b for b in buttons(confirm) if "Оплатить 49 ★" in b.get("text", ""))
    assert pay["url"] == invoice["link"]
    created = shop.billing.created[-1]
    assert (created["plan_id"], created["gateway_type"], created["currency"]) == (
        5,
        "TELEGRAM_STARS",
        "XTR",
    )
    await pay_with_stars(shop, PROXY, invoice)


async def test_ultra_purchase_with_stars(shop: ShopE2E) -> None:
    plans = await open_plans(shop, ULTRA_BUYER)
    durations = await tap(shop, plans, "Ультра")
    before = len(shop.tg.invoices)
    confirm = await tap(shop, durations, "1 месяц")
    invoice = stars_checkout(shop, confirm, before)
    assert invoice["prices"][0]["amount"] == 799
    assert shop.billing.created[-1]["plan_id"] == 38
    await pay_with_stars(shop, ULTRA_BUYER, invoice)


async def test_ultra_owner_gets_the_country_prompt(shop: ShopE2E) -> None:
    since = await send(shop, _text_update(ULTRA_OWNER, "/start"))
    menu = await wait_screen(shop, since, ULTRA_OWNER)
    sub = await tap(shop, menu, "Подписк")
    show("ultra sub", sub)
    prompt = await tap(shop, sub, "Выделенный IP")
    show("ultra prompt", prompt)
    labels = [b.get("text", "") for b in buttons(prompt)]
    assert any("Швеция" in t for t in labels) and any("Нидерланды" in t for t in labels)


async def _pre_checkout(shop: ShopE2E, uid: int, invoice: dict[str, Any]) -> dict[str, Any]:
    since = time.time()
    update_id = _next_update_id()
    await send(
        shop,
        {
            "update_id": update_id,
            "pre_checkout_query": {
                "id": f"pcq-{update_id}",
                "from": _user(uid),
                "currency": "XTR",
                "total_amount": invoice["prices"][0]["amount"],
                "invoice_payload": invoice["payload"],
            },
        },
    )
    assert await shop.wait_for(lambda: shop.tg.calls_of("answerPreCheckoutQuery", since), 10)
    return shop.tg.calls_of("answerPreCheckoutQuery", since)[-1]["data"]


def _ok(answer: dict[str, Any]) -> bool:
    return str(answer.get("ok")).lower() in ("true", "1")


async def test_paid_or_cancelled_invoice_cannot_be_paid_again(shop: ShopE2E) -> None:
    # A Stars invoice link stays payable after billing cancels the payment (30 min) and after it
    # was paid once; billing completes only PENDING payments, so Telegram must refuse it.
    paid = next(i for i in shop.tg.invoices if i["payload"] in shop.billing.completed)
    answer = await _pre_checkout(shop, BUYER, paid)
    print("\n[pre-checkout paid invoice]", answer)
    assert not _ok(answer) and answer.get("error_message")

    plans = await open_plans(shop, BUYER)
    durations = await tap(shop, plans, "Про")
    before = len(shop.tg.invoices)
    confirm = await tap(shop, durations, "1 месяц")
    invoice = stars_checkout(shop, confirm, before)
    assert _ok(await _pre_checkout(shop, BUYER, invoice))
    shop.billing.transactions[invoice["payload"]]["Status"] = "CANCELED"  # billing's 30 min timeout
    answer = await _pre_checkout(shop, BUYER, invoice)
    print("[pre-checkout cancelled invoice]", answer)
    assert not _ok(answer)


async def test_charge_for_a_payment_billing_cancelled_is_refunded(shop: ShopE2E) -> None:
    # Billing's 30 min timeout can cancel the payment after Telegram accepted the pre-checkout
    # answer. handle-free then answers 200 and skips it, so the bot must give the stars back.
    plans = await open_plans(shop, BUYER)
    durations = await tap(shop, plans, "Макс")
    before = len(shop.tg.invoices)
    confirm = await tap(shop, durations, "1 месяц")
    invoice = stars_checkout(shop, confirm, before)
    shop.billing.transactions[invoice["payload"]]["Status"] = "CANCELED"
    since = time.time()
    update_id = _next_update_id()
    charge = f"stxe2e{update_id}"
    await send(
        shop,
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "from": _user(BUYER),
                "chat": {"id": BUYER, "type": "private"},
                "date": int(time.time()),
                "successful_payment": {
                    "currency": "XTR",
                    "total_amount": invoice["prices"][0]["amount"],
                    "invoice_payload": invoice["payload"],
                    "telegram_payment_charge_id": charge,
                    "provider_payment_charge_id": "",
                },
            },
        },
    )
    assert await shop.wait_for(lambda: shop.tg.calls_of("refundStarPayment", since), timeout=10)
    refund = shop.tg.calls_of("refundStarPayment", since)[0]["data"]
    assert str(refund["user_id"]) == str(BUYER)
    assert refund["telegram_payment_charge_id"] == charge
    assert await shop.wait_for(
        lambda: any(
            "Звёзды вернули" in (s.get("text") or "") for s in user_screens(shop, since, BUYER)
        ),
        timeout=10,
    )
    assert shop.billing.transactions[invoice["payload"]]["Status"] == "CANCELED"


async def _successful_payment(
    shop: ShopE2E, uid: int, invoice: dict[str, Any], charge: str
) -> None:
    update_id = _next_update_id()
    await send(
        shop,
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "from": _user(uid),
                "chat": {"id": uid, "type": "private"},
                "date": int(time.time()),
                "successful_payment": {
                    "currency": "XTR",
                    "total_amount": invoice["prices"][0]["amount"],
                    "invoice_payload": invoice["payload"],
                    "telegram_payment_charge_id": charge,
                    "provider_payment_charge_id": "",
                },
            },
        },
    )


async def test_same_invoice_paid_twice_while_billing_is_slow(shop: ShopE2E) -> None:
    # Billing's Kafka consumer lags: the paid payment stays PENDING for a while and the confirm
    # screen still shows the invoice link. Billing completes a payment once, so a second payment of
    # that invoice must be refused, and a second charge that gets through must be refunded, while
    # the first charge stays paid.
    shop.billing.completion_delay = 6
    try:
        plans = await open_plans(shop, BUYER)
        durations = await tap(shop, plans, "Старт")
        before = len(shop.tg.invoices)
        confirm = await tap(shop, durations, "3 месяца")
        invoice = stars_checkout(shop, confirm, before)
        since = time.time()
        assert _ok(await _pre_checkout(shop, BUYER, invoice))
        await _successful_payment(shop, BUYER, invoice, "stxe2e-first")
        assert await shop.wait_for(lambda: invoice["payload"] in shop.billing.completed, 10)
        assert shop.billing.transactions[invoice["payload"]]["Status"] == "PENDING"

        answer = await _pre_checkout(shop, BUYER, invoice)
        print("\n[pre-checkout of an invoice paid a moment ago]", answer)
        assert not _ok(answer) and answer.get("error_message")

        # Two devices passed the pre-checkout at the same moment: Telegram charged twice.
        await _successful_payment(shop, BUYER, invoice, "stxe2e-second")
        assert await shop.wait_for(lambda: shop.tg.calls_of("refundStarPayment", since), 10)
        assert await shop.wait_for(
            lambda: shop.billing.transactions[invoice["payload"]]["Status"] == "COMPLETED", 15
        )
        await asyncio.sleep(2)
        refunds = [
            c["data"]["telegram_payment_charge_id"]
            for c in shop.tg.calls_of("refundStarPayment", since)
        ]
        print("[refunded charges]", refunds)
        assert refunds == ["stxe2e-second"]
    finally:
        shop.billing.completion_delay = 0.7


async def test_no_ruble_payment_was_ever_created(shop: ShopE2E) -> None:
    print(
        "\n[billing] payments created:",
        [(c["gateway_type"], c["plan_id"]) for c in shop.billing.created],
    )
    print("[billing] routes the fake does not model:", sorted(set(shop.billing.unknown)))
    assert shop.billing.created
    assert {c["gateway_type"] for c in shop.billing.created} == {"TELEGRAM_STARS"}
    assert {c["currency"] for c in shop.billing.created} == {"XTR"}
