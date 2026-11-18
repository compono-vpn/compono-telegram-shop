"""QA round 4 E2E for TV pairing (COM-202): a claim that outlasts Telegram's callback window.

The claim can take longer than Telegram keeps a callback query answerable: compono-api waits up
to 15 s for billing and the bot waits up to 30 s for the API. Telegram then refuses
answerCallbackQuery with "query is too old". tgmock has no clock for that, so the refusal is
injected on answerCallbackQuery while the claim is slowed down.

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
from aiohttp import web

pytest.importorskip("tgmock")

from .harness import DEV_ID, ShopE2E, free_port, redis_server_binary  # noqa: E402
from .test_tv_pair_e2e import (  # noqa: E402
    TV,
    _healthy,
    alerts,
    buttons,
    open_link,
    screens,
    tap,
)

if not os.environ.get("SHOP_E2E") or not redis_server_binary():
    pytest.skip("set SHOP_E2E=1 and provide a redis-server to run the e2e", allow_module_level=True)

pytestmark = pytest.mark.asyncio(loop_scope="module")

SLOW_FAIL = 730399001  # paid; the API answers 502 after a delay
SLOW_NOSUB = 730399002  # no subscription; the 422 arrives after a delay
SLOW_OK = 730399003  # paid; the claim attaches after a delay
API_BIN = os.environ.get("SHOP_E2E_API_BIN")
STALE = "Bad Request: query is too old and response timeout expired or query ID is invalid"
DELAY = 1.5


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env():
    shop = ShopE2E()
    shop.billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid in (SLOW_FAIL, SLOW_NOSUB, SLOW_OK):
        shop.billing.add_user(uid, f"QA4{uid}")
    for uid in (SLOW_FAIL, SLOW_OK):
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


class SlowClaim:
    """For one claim: wait, then answer ``status`` (or forward to the real claim when None),
    while Telegram refuses every answerCallbackQuery as too old."""

    def __init__(self, shop: ShopE2E, *, status: int | None) -> None:
        self.shop = shop
        self.original = shop.billing._tv_pair_claim
        self.status = status

    async def __call__(self, request: web.Request, body: dict[str, Any]) -> web.Response:
        self.shop.billing._tv_pair_claim = self.original  # one slow claim only
        await asyncio.sleep(DELAY)
        if self.status is None:
            return await self.original(request, body)
        return web.json_response({"error": "billing_unavailable"}, status=self.status)

    def __enter__(self) -> SlowClaim:
        self.shop.billing._tv_pair_claim = self
        self.shop.tg.failures["answerCallbackQuery"] = (400, STALE)
        return self

    def __exit__(self, *exc: object) -> None:
        self.shop.billing._tv_pair_claim = self.original
        self.shop.tg.failures.pop("answerCallbackQuery", None)


async def test_late_failure_reaches_the_user_as_a_message(env) -> None:
    """Before the round-4 fix the failure was only an alert; Telegram refused it, so the user
    saw nothing at all after waiting for the claim."""
    shop, tv = env
    t0 = time.time()
    code, token = await tv.create()
    question = await open_link(shop, SLOW_FAIL, code)
    since = time.time()
    with SlowClaim(shop, status=502):
        await tap(shop, SLOW_FAIL, question, f"tvp:{code}")
        await asyncio.sleep(1.0)
    shown = screens(shop, SLOW_FAIL, since)
    texts = [s.get("text") or "" for s in shown]
    print(f"[late failure] screens after the tap: {[t[:50] for t in texts]}")
    assert any("Не получилось подключить телевизор" in t for t in texts), texts
    assert not [s for s in shown if s["method"] == "editMessageText"], "the question keeps buttons"
    assert not alerts(shop, t0), "a late answer must not page admins"
    # The code is still pending, so a normal tap now pairs.
    after = await tap(shop, SLOW_FAIL, question, f"tvp:{code}")
    assert any("телевизор подключится" in (s.get("text") or "") for s in after), after
    if tv.api_url:
        status, body = await tv.poll(token, code)
        assert status == 200 and body["status"] == "paired", (status, body)


async def test_late_no_subscription_still_opens_the_plan_list(env) -> None:
    """Before the fix the refused answer came before the plan list and stopped the handler."""
    shop, tv = env
    t0 = time.time()
    code, _ = await tv.create()
    question = await open_link(shop, SLOW_NOSUB, code)
    since = time.time()
    with SlowClaim(shop, status=None):
        await tap(shop, SLOW_NOSUB, question, f"tvp:{code}")
        await asyncio.sleep(1.5)
    shown = screens(shop, SLOW_NOSUB, since)
    print(f"[late 422] screens after the tap: {[(s.get('text') or '')[:40] for s in shown]}")
    assert any("нужна активная подписка" in (s.get("text") or "") for s in shown), shown
    assert any("Старт" in b.get("text", "") for s in shown for b in buttons(s)), (
        "the plan list was not opened"
    )
    assert not alerts(shop, t0)


async def test_late_attach_is_quiet(env) -> None:
    shop, tv = env
    t0 = time.time()
    code, token = await tv.create()
    question = await open_link(shop, SLOW_OK, code)
    since = time.time()
    with SlowClaim(shop, status=None):
        await tap(shop, SLOW_OK, question, f"tvp:{code}")
        await asyncio.sleep(1.0)
    shown = screens(shop, SLOW_OK, since)
    assert any("телевизор подключится" in (s.get("text") or "") for s in shown), shown
    assert not [s for s in shown if s["method"] == "sendMessage"], "no extra message on success"
    assert not alerts(shop, t0)
    if tv.api_url:
        status, body = await tv.poll(token, code)
        assert status == 200 and body["status"] == "paired", (status, body)
