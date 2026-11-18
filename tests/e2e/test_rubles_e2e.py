"""E2E with APP_BOT_RUBLE_PAYMENTS=true (the default since 2026-11-18): rubles next to Stars.

Real app against tgmock + the in-memory billing with the prod gateway rows (PLATEGA BOT RUB,
PLATEGA WEB, PLATEGA_CRYPTO BOT, TELEGRAM_STARS ALL; the stage YooKassa/TON rows are removed).
Prices show in rubles (billing's default currency), the method screen lists СБП and Stars with
their own prices, СБП makes a Platega payment with billing's link, Stars still makes an XTR
invoice, crypto/TON never appear and the «Оплата в рублях сейчас недоступна» line is gone.

    SHOP_E2E=1 SHOP_E2E_REDIS_SERVER=/opt/homebrew/bin/redis-server uv run pytest tests/e2e -v -s
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest
import pytest_asyncio

pytest.importorskip("tgmock")

from .harness import DEV_ID, ShopE2E, redis_server_binary  # noqa: E402
from .test_stale_callback_e2e import admin_alerts, buttons, send, show, tap, wait_screen  # noqa: E402
from .test_stars_only_crawl_e2e import ALLOWED_URL_PREFIXES, crawl  # noqa: E402
from .test_stars_only_e2e import (  # noqa: E402
    PROD_ROWS,
    RUBLE_NOTE,
    _proxy_plan,
    _text_update,
    _ultra_plan,
    open_plans,
    pay_with_stars,
)

if not os.environ.get("SHOP_E2E") or not redis_server_binary():
    pytest.skip("set SHOP_E2E=1 and provide a redis-server to run the e2e", allow_module_level=True)

pytestmark = pytest.mark.asyncio(loop_scope="module")

SBP_BUYER = 830000001
STARS_BUYER = 830000002
PROXY = 830000003
CRAWL_NEW = 830000004
CRAWL_PAID = 830000005

PLATEGA_URL = "https://pay.platega.io/"
# With rubles on, ₽ and СБП are expected; crypto, TON, card wording, the website and the
# "rubles unavailable" note must still never appear.
RUBLE_BANNED = (
    RUBLE_NOTE,
    "Карта",
    "карт",
    "крипт",
    "Крипт",
    "Platega",
    "ЮKassa",
    "TON",
    "componovpn.com/pricing",
    "/purchase",
    "app.componovpn.com",
    "на сайте",
    "на сайт",
)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def shop():
    e2e = ShopE2E(extra_env={"APP_BOT_RUBLE_PAYMENTS": "true"})
    billing = e2e.billing
    stars = [g for g in billing.gateways if g["Type"] == "TELEGRAM_STARS"]
    billing.gateways[:] = [*PROD_ROWS, *stars]
    billing.extra_plans.append(_ultra_plan())
    billing.hidden_plans.append(_proxy_plan())
    billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid in (SBP_BUYER, STARS_BUYER, PROXY, CRAWL_NEW, CRAWL_PAID):
        billing.add_user(uid, f"u{uid}")
    billing.add_active_subscription(CRAWL_PAID)
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


def _labels(screen: dict[str, Any]) -> list[str]:
    return [b.get("text", "") for b in buttons(screen)]


async def _method_screen(shop: ShopE2E, uid: int) -> dict[str, Any]:
    plans = await open_plans(shop, uid)
    show("plans", plans)
    assert "119 ₽/мес" in plans["text"] and "★" not in plans["text"], plans["text"]
    # Every plan button is coloured; only «Назад» / «Главное меню» keep the default style.
    plan_buttons = [b for b in buttons(plans) if "₽" in b.get("text", "")]
    assert plan_buttons and all(b.get("style") for b in plan_buttons), plan_buttons
    nav = [b for b in buttons(plans) if b.get("text") in ("⬅️ Назад", "↩️ Главное меню")]
    assert len(nav) == 2 and not any(b.get("style") for b in nav), nav
    durations = await tap(shop, plans, "Старт")
    show("durations", durations)
    labels = _labels(durations)
    for price in ("1 месяц — 119 ₽", "3 месяца — 319 ₽", "6 месяцев — 579 ₽", "1 год — 999 ₽"):
        assert any(price in label for label in labels), (price, labels)
    methods = await tap(shop, durations, "1 месяц")
    show("methods", methods)
    assert RUBLE_NOTE not in (methods.get("text") or "")
    labels = _labels(methods)
    assert any("СБП" in t and "119 ₽" in t for t in labels), labels
    assert any("Telegram Stars" in t and "119 ★" in t for t in labels), labels
    assert not any("крипт" in t.lower() or "TON" in t or "compono_support" in t for t in labels)
    return methods


async def test_sbp_creates_a_platega_ruble_payment(shop: ShopE2E) -> None:
    started = time.time()
    methods = await _method_screen(shop, SBP_BUYER)
    invoices = len(shop.tg.invoices)
    confirm = await tap(shop, methods, "СБП")
    show("confirm sbp", confirm)

    created = shop.billing.created[-1]
    assert (created["gateway_type"], created["currency"], created["plan_id"]) == (
        "PLATEGA",
        "RUB",
        1,
    )
    pricing = shop.billing.transactions[created["ID"]]["Pricing"]
    assert pricing["final_amount"] == "119"
    pay = next(b for b in buttons(confirm) if b.get("text") == "💳 Оплатить")
    assert pay["url"] == f"{PLATEGA_URL}{created['ID']}"
    assert len(shop.tg.invoices) == invoices, "a Stars invoice was made for a ruble payment"
    assert RUBLE_NOTE not in (confirm.get("text") or "")
    assert "119₽" in (confirm.get("text") or "")
    assert not any("compono_support" in t for t in _labels(confirm))
    assert not admin_alerts(shop, started), admin_alerts(shop, started)


async def test_stars_still_makes_an_xtr_invoice(shop: ShopE2E) -> None:
    methods = await _method_screen(shop, STARS_BUYER)
    before = len(shop.tg.invoices)
    confirm = await tap(shop, methods, "Telegram Stars")
    show("confirm stars", confirm)
    created = shop.billing.created[-1]
    assert (created["gateway_type"], created["currency"]) == ("TELEGRAM_STARS", "XTR")
    assert len(shop.tg.invoices) == before + 1
    invoice = shop.tg.invoices[-1]
    assert invoice["currency"] == "XTR" and invoice["prices"][0]["amount"] == 119
    pay = next(b for b in buttons(confirm) if "Оплатить звёздами" in b.get("text", ""))
    assert pay["url"] == invoice["link"]
    await pay_with_stars(shop, STARS_BUYER, invoice)
    assert shop.billing.transactions[invoice["payload"]]["Status"] == "COMPLETED"


async def test_proxy_is_sold_for_rubles(shop: ShopE2E) -> None:
    since = await send(shop, _text_update(PROXY, "/start proxy"))
    screen = await wait_screen(shop, since, PROXY)
    show("proxy", screen)
    assert "49 ₽ в месяц" in screen["text"]
    confirm = await tap(shop, screen, "Pro за 49 ₽")
    show("proxy confirm", confirm)
    created = shop.billing.created[-1]
    assert (created["gateway_type"], created["currency"], created["plan_id"]) == (
        "PLATEGA",
        "RUB",
        5,
    )
    pay = next(b for b in buttons(confirm) if "Оплатить 49 ₽" in b.get("text", ""))
    assert pay["url"] == f"{PLATEGA_URL}{created['ID']}"
    assert RUBLE_NOTE not in (confirm.get("text") or "")


@pytest.mark.parametrize("uid", [CRAWL_NEW, CRAWL_PAID])
async def test_crawl_with_rubles_on(shop: ShopE2E, uid: int) -> None:
    findings = await crawl(
        shop,
        uid,
        max_taps=60,
        banned=RUBLE_BANNED,
        allowed_urls=(*ALLOWED_URL_PREFIXES, PLATEGA_URL),
        allow_ruble_note=False,
    )
    for f in findings:
        print("FINDING:", f)
    assert not findings, findings
