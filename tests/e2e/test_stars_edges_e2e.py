"""E2E edge cases of the Stars-only checkout: a free (0 star) order, an old «Другой способ» nudge
button, and repeated taps. Opt-in like the other e2e modules (see test_stars_only_e2e.py).
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest
import pytest_asyncio

pytest.importorskip("tgmock")

from .harness import DEV_ID, ShopE2E, redis_server_binary  # noqa: E402
from .test_stale_callback_e2e import (  # noqa: E402
    _bot_message,
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

OLD_PLATEGA_PAYMENT = "3d0c8f62-6a52-4a8e-9a55-6d1b2b0c1a01"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def shop():
    e2e = ShopE2E()
    e2e.billing.gateways.extend(PROD_ROWS)
    e2e.billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid in (FREE, NUDGE, TAPS):
        e2e.billing.add_user(uid, f"u{uid}")
    e2e.billing.discounts[FREE] = 100
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
    assert await shop.wait_for(lambda: created["ID"] in shop.billing.completed, timeout=10)
    assert get is not None


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
