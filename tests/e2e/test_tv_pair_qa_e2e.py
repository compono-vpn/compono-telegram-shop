"""QA round 1 E2E for TV pairing (COM-202): edge cases beyond the author's happy paths.

Same harness as ``test_tv_pair_e2e.py`` (real bot, tgmock, fake billing, optionally the real
compono-api via ``SHOP_E2E_API_BIN``). Separate Telegram IDs so the two modules never share
rate-limit counters.
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

PAID = 730188001
NOSUB = 730188002
GUESSER = 730188003
LOWER = 730188004
DOWN = 730188005
DOUBLE = 730188006
FORGED = 730188007
BADLINK = 730188008
API_BIN = os.environ.get("SHOP_E2E_API_BIN")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env():
    shop = ShopE2E()
    shop.billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid in (PAID, NOSUB, GUESSER, LOWER, DOWN, DOUBLE, FORGED, BADLINK):
        shop.billing.add_user(uid, f"QA{uid}")
    for uid in (PAID, LOWER, DOWN, DOUBLE):
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


def deleted_ids(shop: ShopE2E, since: float) -> set[int]:
    return {int(c["data"].get("message_id", 0)) for c in shop.tg.calls_of("deleteMessage", since)}


async def test_no_subscription_keeps_the_retry_message(env) -> None:
    """The 422 screen promises «нажмите «Подключить» ещё раз». Opening the plan list must not
    delete that message, or the retry button is gone."""
    shop, tv = env
    code, _ = await tv.create()
    question = await open_link(shop, NOSUB, code)
    since = time.time()
    after = await tap(shop, NOSUB, question, f"tvp:{code}")
    await asyncio.sleep(1.0)
    gone = deleted_ids(shop, since)
    retry = [
        s
        for s in after + screens(shop, NOSUB, since)
        if "нужна активная подписка" in (s.get("text") or "")
        and [b["callback_data"] for b in buttons(s)] == [f"tvp:{code}"]
    ]
    print(
        f"[no sub] deleted ids after the tap: {gone}; retry messages: {[r['message_id'] for r in retry]}"
    )
    assert retry, "no message carries the explanation and the retry button"
    assert all(int(r["message_id"]) not in gone for r in retry), "the retry message was deleted"


async def test_lower_case_payload(env) -> None:
    shop, tv = env
    code, token = await tv.create()
    mark = len(shop.billing.bodies)
    since = await send(shop, start_update(LOWER, f"TV-{code.lower()}"))
    question = (await wait_screens(shop, LOWER, since))[-1]
    assert f"{code[:4]}-{code[4:]}" in question["text"]
    assert [b["callback_data"] for b in buttons(question)] == [f"tvp:{code}", "tvx"]
    await tap(shop, LOWER, question, f"tvp:{code}")
    assert claims(shop, mark) == [{"code": code, "telegramId": LOWER}]


@pytest.mark.parametrize(
    "payload",
    ["tv-ILOU1234", "tv-ABC", "tv-ABCDEFGH9", "tv-", "tv_ABCDEFGH", "tv-ABCD-EFGH", "xtv-ABCDEFGH"],
)
async def test_bad_tv_payload_opens_the_main_menu(env, payload: str) -> None:
    shop, _ = env
    mark = len(shop.billing.bodies)
    since = await send(shop, start_update(BADLINK, payload))
    screen = (await wait_screens(shop, BADLINK, since))[-1]
    assert "Подключить телевизор" not in (screen.get("text") or "")
    assert any("Подписк" in b.get("text", "") for b in buttons(screen)), screen
    assert claims(shop, mark) == []


@pytest.mark.parametrize(
    "data", ["tvp:", "tvp:ABC", "tvp:ILOU1234", "tvp:abcdefgh", "tvp:ABCDEFGH1", "tvp:../../x"]
)
async def test_forged_button_never_claims(env, data: str) -> None:
    shop, _ = env
    t0 = time.time()
    mark = len(shop.billing.bodies)
    screen = {"message_id": 999001, "text": "x", "reply_markup": None}
    since = await send(shop, callback_update(FORGED, data, screen))
    assert await shop.wait_for(lambda: shop.tg.calls_of("answerCallbackQuery", since), timeout=10)
    assert claims(shop, mark) == []
    assert not alerts(shop, t0)


async def test_api_failure_shows_alert_keeps_buttons(env) -> None:
    """compono-api (or billing behind it) answering 5xx: an alert, no edit, the buttons stay."""
    shop, tv = env
    code, _ = await tv.create()
    question = await open_link(shop, DOWN, code)
    saved = shop.billing.tv_pair_api
    shop.billing.tv_pair_api = f"http://127.0.0.1:{free_port()}"  # nothing listens
    try:
        since = await send(shop, callback_update(DOWN, f"tvp:{code}", question))
        assert await shop.wait_for(
            lambda: shop.tg.calls_of("answerCallbackQuery", since), timeout=15
        )
        await asyncio.sleep(0.5)
    finally:
        shop.billing.tv_pair_api = saved
    answer = shop.tg.calls_of("answerCallbackQuery", since)[-1]["data"]
    print(f"[api down] answer: {answer}")
    assert "Не получилось подключить телевизор" in str(answer.get("text"))
    assert str(answer.get("show_alert")).lower() in ("true", "1")
    assert not [s for s in screens(shop, DOWN, since) if s["method"] == "editMessageText"]


async def test_guessing_codes_is_stopped(env) -> None:
    """5 unknown codes, then the 6th tap (even a real code) is rate limited."""
    shop, tv = env
    if not tv.api_url:
        pytest.skip("the failure limit lives in compono-api")
    for i in range(5):
        fake = f"ZZZZ00{i}0"
        q = await open_link(shop, GUESSER, fake)
        after = await tap(shop, GUESSER, q, f"tvp:{fake}")
        assert any("Код устарел" in (s.get("text") or "") for s in after), after
    code, _ = await tv.create()
    q = await open_link(shop, GUESSER, code)
    since = await send(shop, callback_update(GUESSER, f"tvp:{code}", q))
    assert await shop.wait_for(lambda: shop.tg.calls_of("answerCallbackQuery", since), timeout=15)
    answer = shop.tg.calls_of("answerCallbackQuery", since)[-1]["data"]
    assert "Слишком много попыток" in str(answer.get("text")), answer


async def test_double_tap_at_once(env) -> None:
    """Two taps of «Подключить» delivered at the same moment: no #EventError, the TV pairs."""
    shop, tv = env
    t0 = time.time()
    code, token = await tv.create()
    question = await open_link(shop, DOUBLE, code)
    await asyncio.sleep(1.0)
    u1 = callback_update(DOUBLE, f"tvp:{code}", question)
    u2 = callback_update(DOUBLE, f"tvp:{code}", question)
    since = time.time()
    codes = await asyncio.gather(shop.send_update(u1), shop.send_update(u2))
    assert codes == [200, 200]
    await shop.wait_for(lambda: shop.tg.calls_of("answerCallbackQuery", since), timeout=15)
    await asyncio.sleep(2.0)
    assert not alerts(shop, t0)
    status, body = await tv.poll(token, code)
    assert body["status"] in ("paired", "claimed"), body


async def test_nothing_secret_in_logs(env) -> None:
    """Pair once more, then scan the bot log and the API log for the full code, the pollToken
    and the subscription URL."""
    shop, tv = env
    code, token = await tv.create()
    q = await open_link(shop, PAID, code)
    await tap(shop, PAID, q, f"tvp:{code}")
    status, body = await tv.poll(token, code)
    url = shop.billing.subscriptions[PAID]["URL"]
    bot_log = shop.log()
    assert code not in bot_log
    assert url not in bot_log
    if tv.api_url:
        assert status == 200 and body["subscriptionUrl"] == url
        api_log = shop.log_path.with_name("api.log").read_text(errors="replace")
        for secret in (code, token, url, url.rsplit("/", 1)[-1]):
            assert secret not in api_log, "a secret reached the API log"
        print(f"[logs] api log {len(api_log)} bytes, bot log {len(bot_log)} bytes, 0 secrets")


async def test_main_menu_still_works_after_tv_question(env) -> None:
    shop, _ = env
    update: dict[str, Any] = start_update(PAID, "x")
    update["message"]["text"] = "/start"
    update["update_id"] = _next()
    since = await send(shop, update)
    menu = (await wait_screens(shop, PAID, since))[-1]
    assert any("Подписк" in b.get("text", "") for b in buttons(menu))
