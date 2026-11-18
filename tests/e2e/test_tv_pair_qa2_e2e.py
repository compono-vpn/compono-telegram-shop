"""QA round 2 E2E for TV pairing (COM-202): flows round 1 did not cover.

Same harness as ``test_tv_pair_e2e.py`` (real bot, tgmock, fake billing, optionally the real
compono-api via ``SHOP_E2E_API_BIN``). Own Telegram IDs, so no rate-limit counter is shared with
the other modules.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from typing import Any

import pytest
import pytest_asyncio

pytest.importorskip("tgmock")

from .harness import DEV_ID, ShopE2E, free_port, redis_server_binary  # noqa: E402
from .test_tv_pair_e2e import (  # noqa: E402
    TV,
    _healthy,
    _next,
    alerts,
    buttons,
    callback_update,
    claims,
    no_subscription_message,
    open_link,
    screens,
    send,
    start_update,
    tap,
    wait_screens,
)

if not os.environ.get("SHOP_E2E") or not redis_server_binary():
    pytest.skip("set SHOP_E2E=1 and provide a redis-server to run the e2e", allow_module_level=True)

pytestmark = pytest.mark.asyncio(loop_scope="module")

PROMO = 730199001  # paid, sits in the promocode input when the TV link arrives
SPAM = 730199002  # no subscription, keeps tapping «Подключить»
NEWBIE = 730199003  # never seen before, cancels, then uses the bot normally
STALE = 730199004  # taps an old retry message after the code was redeemed
TWO_TVS = 730199005  # paid, pairs two TVs one after the other
API_BIN = os.environ.get("SHOP_E2E_API_BIN")
USED: list[str] = []


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env():
    shop = ShopE2E()
    shop.billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid in (PROMO, SPAM, STALE, TWO_TVS):
        shop.billing.add_user(uid, f"QA2{uid}")
    for uid in (PROMO, TWO_TVS):
        shop.billing.add_active_subscription(uid)
    api = None
    api_log = None
    try:
        await shop.start()
        api_url = None
        if API_BIN:
            port = free_port()
            api_log = open(shop.log_path.with_name("api.log"), "wb")
            api = subprocess.Popen(
                [API_BIN],
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PORT": str(port),
                    "METRICS_ADDRESS": f"127.0.0.1:{free_port()}",
                    "REDIS_URL": f"redis://:e2e@127.0.0.1:{shop.redis_port}/9",
                    "JWT_SECRET": "e2e-jwt",
                    "RESEND_API_KEY": "e2e",
                    "BILLING_API_URL": shop.billing.url,
                    "BILLING_INTERNAL_SECRET": "e2e",
                    "LOG_LEVEL": "debug",
                    "LOG_DEST": "stdout",
                    "APP_ENVIRONMENT": "local",
                    "ROUTING_REFRESH_INTERVAL": "24h",
                },
                stdout=api_log,
                stderr=subprocess.STDOUT,
            )
            api_url = f"http://127.0.0.1:{port}"
            assert await shop.wait_for(lambda: _healthy(api_url), timeout=20)
            shop.billing.tv_pair_api = api_url
        yield shop, TV(shop, api_url)
    finally:
        if api and api.poll() is None:
            api.terminate()
            api.wait(timeout=10)
        if api_log:
            api_log.close()
        await shop.stop()
        print(f"\n--- shop log: {shop.log_path}")


def plain_start(uid: int) -> dict[str, Any]:
    update = start_update(uid, "x")
    update["message"]["text"] = "/start"
    update["update_id"] = _next()
    return update


def text_update(uid: int, text: str) -> dict[str, Any]:
    update = start_update(uid, "x")
    update["message"]["text"] = text
    update["message"].pop("entities", None)
    update["update_id"] = _next()
    return update


def find_button(screen: dict[str, Any], needle: str) -> dict[str, Any] | None:
    return next((b for b in buttons(screen) if needle in b.get("text", "")), None)


async def test_tv_link_while_waiting_for_promocode_text(env) -> None:
    """A user who sits in the promocode input (a text MessageInput) scans the TV QR. The
    /start tv- message must reach the TV handler, not be eaten as a promocode."""
    shop, tv = env
    since = await send(shop, plain_start(PROMO))
    menu = (await wait_screens(shop, PROMO, since))[-1]
    sub_btn = find_button(menu, "Подписк")
    assert sub_btn, [b.get("text") for b in buttons(menu)]
    after = await tap(shop, PROMO, menu, sub_btn["callback_data"])
    sub_screen = after[-1]
    promo_btn = find_button(sub_screen, "промокод")
    assert promo_btn, [b.get("text") for b in buttons(sub_screen)]
    after = await tap(shop, PROMO, sub_screen, promo_btn["callback_data"])
    print(f"[promo] input screen: {(after[-1].get('text') or '')[:120]!r}")

    code, token = await tv.create()
    USED.append(code)
    mark = len(shop.billing.bodies)
    promo_calls = len([1 for (_, route, _) in shop.billing.bodies if "promocode" in route])
    question = await open_link(shop, PROMO, code)
    assert claims(shop, mark) == []
    assert (
        len([1 for (_, route, _) in shop.billing.bodies if "promocode" in route]) == promo_calls
    ), "the /start tv- text was sent to billing as a promocode"
    after = await tap(shop, PROMO, question, f"tvp:{code}")
    assert any("Телевизор попросит подтвердить" in (s.get("text") or "") for s in after), after
    status, body = await tv.poll(token, code)
    assert body["status"] in ("paired", "claimed"), body


async def test_repeated_taps_without_subscription_then_the_claim_limit(env) -> None:
    """Each tap without a subscription: one new explanation, no #EventError, the code stays
    pending. The claim limit (10 per 10 minutes per Telegram ID) then ends in a friendly alert,
    not an error."""
    shop, tv = env
    t0 = time.time()
    code, token = await tv.create()
    USED.append(code)
    question = await open_link(shop, SPAM, code)
    after = await tap(shop, SPAM, question, f"tvp:{code}")
    retry = no_subscription_message(after)
    explanations = 1
    for _ in range(2):
        since = await send(shop, callback_update(SPAM, f"tvp:{code}", retry))
        await shop.wait_for(lambda s=since: shop.tg.calls_of("answerCallbackQuery", s), timeout=15)
        await asyncio.sleep(1.0)
        retry = no_subscription_message(screens(shop, SPAM, since))
        explanations += 1
    print(f"[spam] explanations after 3 taps: {explanations}")
    assert not alerts(shop, t0)
    status, body = await tv.poll(token, code)
    assert body["status"] == "pending", body
    if not tv.api_url:
        return
    # 3 claims so far; 7 more reach the limit, the 11th is refused.
    answers = []
    for _ in range(8):
        since = await send(shop, callback_update(SPAM, f"tvp:{code}", retry))
        await shop.wait_for(lambda s=since: shop.tg.calls_of("answerCallbackQuery", s), timeout=15)
        await asyncio.sleep(0.8)
        answers.append(shop.tg.calls_of("answerCallbackQuery", since)[-1]["data"])
        fresh = [
            s
            for s in screens(shop, SPAM, since)
            if s["method"] == "sendMessage" and "нужна активная подписка" in (s.get("text") or "")
        ]
        if fresh:
            retry = fresh[-1]
    last = answers[-1]
    print(f"[spam] last answer: {last}")
    assert "Слишком много попыток" in str(last.get("text")), last
    assert str(last.get("show_alert")).lower() in ("true", "1")
    assert not alerts(shop, t0), "the claim limit must not page admins"


async def test_new_user_cancels_then_uses_the_bot(env) -> None:
    shop, tv = env
    t0 = time.time()
    code, token = await tv.create()
    USED.append(code)
    question = await open_link(shop, NEWBIE, code)
    after = await tap(shop, NEWBIE, question, "tvx")
    assert any("Отменено" in (s.get("text") or "") for s in after)
    since = await send(shop, plain_start(NEWBIE))
    menu = (await wait_screens(shop, NEWBIE, since))[-1]
    assert find_button(menu, "Подписк"), [b.get("text") for b in buttons(menu)]
    assert not alerts(shop, t0)
    status, body = await tv.poll(token, code)
    assert body["status"] == "pending", "cancel in the bot must not touch the TV's code"


async def test_old_retry_message_after_the_tv_paired(env) -> None:
    """The user buys, pairs through the retry message, the TV redeems; a later tap on an older
    copy of the retry message says the code is used up and raises nothing."""
    shop, tv = env
    t0 = time.time()
    code, token = await tv.create()
    USED.append(code)
    question = await open_link(shop, STALE, code)
    first = no_subscription_message(await tap(shop, STALE, question, f"tvp:{code}"))
    since = await send(shop, callback_update(STALE, f"tvp:{code}", first))
    await shop.wait_for(lambda: shop.tg.calls_of("answerCallbackQuery", since), timeout=15)
    await asyncio.sleep(1.0)
    second = no_subscription_message(screens(shop, STALE, since))
    shop.billing.add_active_subscription(STALE)
    after = await tap(shop, STALE, second, f"tvp:{code}")
    assert any("Телевизор попросит подтвердить" in (s.get("text") or "") for s in after)
    status, body = await tv.poll(token, code)
    assert body["status"] in ("paired", "claimed"), body
    after = await tap(shop, STALE, first, f"tvp:{code}")
    texts = [s.get("text") or "" for s in after]
    print(f"[stale retry] after the TV paired: {texts}")
    if tv.api_url:
        assert any("Код устарел" in t for t in texts), texts
    assert not alerts(shop, t0)


async def test_two_tvs_one_after_the_other(env) -> None:
    shop, tv = env
    for n in range(2):
        code, token = await tv.create()
        USED.append(code)
        question = await open_link(shop, TWO_TVS, code)
        after = await tap(shop, TWO_TVS, question, f"tvp:{code}")
        assert any("Телевизор попросит подтвердить" in (s.get("text") or "") for s in after), (n, after)
        status, body = await tv.poll(token, code)
        if tv.api_url:
            assert status == 200 and body["status"] == "paired"
            assert body["subscriptionUrl"] == shop.billing.subscriptions[TWO_TVS]["URL"]


async def test_bot_log_has_no_full_code(env) -> None:
    shop, _ = env
    log = shop.log()
    for uid in (PROMO, SPAM, NEWBIE, STALE, TWO_TVS):
        sub = shop.billing.subscriptions.get(uid)
        if sub:
            assert sub["URL"] not in log
    assert USED, "no code was created in this module"
    leaked = [c for c in USED if c in log]
    print(f"[log] bot log {len(log)} bytes, {len(USED)} codes checked, {len(leaked)} found")
    assert not leaked, "a full pairing code reached the bot log"
