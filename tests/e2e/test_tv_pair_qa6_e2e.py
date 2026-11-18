"""QA round 6 E2E for TV pairing (COM-202): the tap arrives with an InaccessibleMessage.

Since Bot API 7.0 ``callback_query.message`` can be an InaccessibleMessage (``date`` 0, no
text): the message was deleted or is otherwise inaccessible, for example too old for Telegram to
send its content. The handler used to drop the outcome silently in that case: the claim ran (the
TV paired) but the user saw nothing, and «Отмена» answered nothing either.

Same harness as ``test_tv_pair_e2e.py`` (real bot, tgmock, fake billing, optionally the real
compono-api via ``SHOP_E2E_API_BIN``). Own Telegram IDs.
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
    _user,
    alerts,
    buttons,
    no_subscription_message,
    open_link,
    screens,
    send,
)

if not os.environ.get("SHOP_E2E") or not redis_server_binary():
    pytest.skip("set SHOP_E2E=1 and provide a redis-server to run the e2e", allow_module_level=True)

pytestmark = pytest.mark.asyncio(loop_scope="module")

OLD_OK = 730599001  # paid; taps «Подключить» on an inaccessible question
OLD_USED = 730599002  # paid; the code was already claimed by OLD_OK
OLD_CANCEL = 730599003  # paid; taps «Отмена» on an inaccessible question
OLD_NOSUB = 730599004  # no subscription; taps «Подключить» on an inaccessible question
API_BIN = os.environ.get("SHOP_E2E_API_BIN")


def inaccessible_tap(uid: int, data: str, screen: dict[str, Any]) -> dict[str, Any]:
    n = _next()
    return {
        "update_id": n,
        "callback_query": {
            "id": f"cq-{n}",
            "from": _user(uid),
            "chat_instance": "e2e-tv-qa6",
            "data": data,
            # InaccessibleMessage: chat, message_id and date 0, nothing else.
            "message": {
                "chat": {"id": uid, "type": "private"},
                "message_id": screen["message_id"],
                "date": 0,
            },
        },
    }


async def tap_inaccessible(shop: ShopE2E, uid: int, screen: dict[str, Any], data: str):
    since = await send(shop, inaccessible_tap(uid, data, screen))
    await shop.wait_for(lambda: shop.tg.calls_of("answerCallbackQuery", since), timeout=15)
    await asyncio.sleep(1.0)
    return since, screens(shop, uid, since)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env():
    shop = ShopE2E()
    shop.billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid in (OLD_OK, OLD_USED, OLD_CANCEL):
        shop.billing.add_user(uid, f"QA6{uid}")
        shop.billing.add_active_subscription(uid)
    shop.billing.add_user(OLD_NOSUB, f"QA6{OLD_NOSUB}")
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
                    "REDIS_URL": f"redis://:e2e@127.0.0.1:{shop.redis_port}/10",
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


async def test_inaccessible_question_still_gets_the_outcome(env) -> None:
    shop, tv = env
    t0 = time.time()
    code, token = await tv.create()
    question = await open_link(shop, OLD_OK, code)
    _, shown = await tap_inaccessible(shop, OLD_OK, question, f"tvp:{code}")
    texts = [s.get("text") or "" for s in shown]
    print(f"[inaccessible] screens after the tap: {[t[:50] for t in texts]}")
    assert any(
        s["method"] == "sendMessage" and "телевизор подключится" in (s.get("text") or "")
        for s in shown
    ), texts
    assert not alerts(shop, t0), "an inaccessible question must not page admins"
    if tv.api_url:
        status, body = await tv.poll(token, code)
        assert status == 200 and body["status"] == "paired", (status, body)


async def test_inaccessible_question_used_code_is_told(env) -> None:
    shop, tv = env
    code, _ = await tv.create()
    first = await open_link(shop, OLD_OK, code)
    await tap_inaccessible(shop, OLD_OK, first, f"tvp:{code}")
    question = await open_link(shop, OLD_USED, code)
    _, shown = await tap_inaccessible(shop, OLD_USED, question, f"tvp:{code}")
    assert any("уже использован" in (s.get("text") or "") for s in shown), shown


async def test_inaccessible_question_cancel_is_told(env) -> None:
    shop, tv = env
    t0 = time.time()
    code, _ = await tv.create()
    question = await open_link(shop, OLD_CANCEL, code)
    _, shown = await tap_inaccessible(shop, OLD_CANCEL, question, "tvx")
    assert any("Отменено" in (s.get("text") or "") for s in shown), shown
    assert not alerts(shop, t0)


async def test_inaccessible_question_without_subscription_opens_plans(env) -> None:
    shop, tv = env
    t0 = time.time()
    code, _ = await tv.create()
    question = await open_link(shop, OLD_NOSUB, code)
    _, shown = await tap_inaccessible(shop, OLD_NOSUB, question, f"tvp:{code}")
    retry = no_subscription_message(shown)
    assert [b["callback_data"] for b in buttons(retry)] == [f"tvp:{code}"]
    others = [s for s in shown if s is not retry]
    assert any("Старт" in b.get("text", "") for s in others for b in buttons(s)), (
        "the plan list was not opened"
    )
    assert not alerts(shop, t0)
