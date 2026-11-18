"""QA round 5 E2E for TV pairing (COM-202): the user deletes the question while the claim runs.

The claim can take many seconds. If the user deletes the «Подключить телевизор?» message in the
meantime, Telegram refuses editMessageText with "message to edit not found". The claim has
already happened, so the TV pairs; before the fix that refusal escaped the handler, the tap was
never answered, admins got #EventError and the user was told something went wrong. tgmock does
not track deleted messages, so the refusal is injected on editMessageText.

Same harness as ``test_tv_pair_e2e.py`` (real bot, tgmock, fake billing, optionally the real
compono-api via ``SHOP_E2E_API_BIN``). Own Telegram IDs.
"""

from __future__ import annotations

import os
import subprocess
import time

import pytest
import pytest_asyncio

pytest.importorskip("tgmock")

from .harness import DEV_ID, ShopE2E, free_port, redis_server_binary  # noqa: E402
from .test_tv_pair_e2e import TV, _healthy, alerts, open_link, screens, tap  # noqa: E402

if not os.environ.get("SHOP_E2E") or not redis_server_binary():
    pytest.skip("set SHOP_E2E=1 and provide a redis-server to run the e2e", allow_module_level=True)

pytestmark = pytest.mark.asyncio(loop_scope="module")

GONE_OK = 730499001  # paid; the question is deleted while the claim attaches
GONE_USED = 730499002  # paid; the code was already claimed by GONE_OK
API_BIN = os.environ.get("SHOP_E2E_API_BIN")
NOT_FOUND = "Bad Request: message to edit not found"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env():
    shop = ShopE2E()
    shop.billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid in (GONE_OK, GONE_USED):
        shop.billing.add_user(uid, f"QA5{uid}")
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


async def test_deleted_question_still_gets_the_outcome(env) -> None:
    shop, tv = env
    t0 = time.time()
    code, token = await tv.create()
    question = await open_link(shop, GONE_OK, code)
    since = time.time()
    shop.tg.failures["editMessageText"] = (400, NOT_FOUND)
    try:
        await tap(shop, GONE_OK, question, f"tvp:{code}")
    finally:
        shop.tg.failures.pop("editMessageText", None)
    shown = screens(shop, GONE_OK, since)
    texts = [s.get("text") or "" for s in shown]
    print(f"[deleted question] screens after the tap: {[t[:50] for t in texts]}")
    assert any(
        s["method"] == "sendMessage" and "Телевизор попросит подтвердить" in (s.get("text") or "")
        for s in shown
    ), texts
    assert not any("ошибка" in t.lower() for t in texts), texts
    assert not alerts(shop, t0), "a deleted question must not page admins"
    if tv.api_url:
        status, body = await tv.poll(token, code)
        assert status == 200 and body["status"] == "paired", (status, body)


async def test_deleted_question_used_code_is_told(env) -> None:
    shop, tv = env
    code, _ = await tv.create()
    first = await open_link(shop, GONE_OK, code)
    await tap(shop, GONE_OK, first, f"tvp:{code}")
    t0 = time.time()
    question = await open_link(shop, GONE_USED, code)
    since = time.time()
    shop.tg.failures["editMessageText"] = (400, NOT_FOUND)
    try:
        await tap(shop, GONE_USED, question, f"tvp:{code}")
    finally:
        shop.tg.failures.pop("editMessageText", None)
    shown = screens(shop, GONE_USED, since)
    assert any("уже использован" in (s.get("text") or "") for s in shown), shown
    assert not alerts(shop, t0)
