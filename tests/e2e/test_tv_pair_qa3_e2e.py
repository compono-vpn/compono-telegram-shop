"""QA round 3 E2E for TV pairing (COM-202): the network dropping mid-claim, and typed look-alike
codes.

Same harness as ``test_tv_pair_e2e.py`` (real bot, tgmock, fake billing, optionally the real
compono-api via ``SHOP_E2E_API_BIN``). Own Telegram IDs, so no rate-limit counter is shared with
the other modules.
"""

from __future__ import annotations

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
    _next,
    alerts,
    buttons,
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

LOST = 730299001  # paid; the claim lands on the API but its answer never reaches the bot
RESET = 730299002  # paid; the connection drops before the claim reaches the API
LOOKALIKE = 730299003  # types /start tv- with a non-ASCII look-alike letter
API_BIN = os.environ.get("SHOP_E2E_API_BIN")
USED: list[str] = []


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env():
    shop = ShopE2E()
    shop.billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid in (LOST, RESET, LOOKALIKE):
        shop.billing.add_user(uid, f"QA3{uid}")
    for uid in (LOST, RESET):
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


class DropNextClaim:
    """Replaces the fake's claim route for one call: optionally let the claim reach compono-api
    (or the in-memory model), then close the connection without any answer."""

    def __init__(self, shop: ShopE2E, *, forward: bool) -> None:
        self.billing = shop.billing
        self.original = shop.billing._tv_pair_claim
        self.forward = forward
        self.calls = 0

    async def __call__(self, request: web.Request, body: dict[str, Any]) -> web.Response:
        self.calls += 1
        self.billing._tv_pair_claim = self.original  # one drop only
        if self.forward:
            await self.original(request, body)
        assert request.transport is not None
        request.transport.close()
        raise ConnectionResetError("e2e: connection dropped mid-claim")

    def __enter__(self) -> DropNextClaim:
        self.billing._tv_pair_claim = self
        return self

    def __exit__(self, *exc: object) -> None:
        self.billing._tv_pair_claim = self.original


def last_answer(shop: ShopE2E, since: float) -> dict[str, Any]:
    answers = shop.tg.calls_of("answerCallbackQuery", since)
    assert answers, "the tap was not answered"
    return answers[-1]["data"]


async def tap_and_answer(shop: ShopE2E, uid: int, screen: dict[str, Any], data: str):
    since = time.time()
    after = await tap(shop, uid, screen, data)
    return after, last_answer(shop, since)


async def test_answer_lost_after_the_claim_landed(env) -> None:
    """The API attached the user, but the connection dropped before the bot read the answer.
    The user sees a short alert (no #EventError), the question keeps its buttons, and the next
    tap is the idempotent 200 that says «Готово». The TV then gets the URL."""
    shop, tv = env
    t0 = time.time()
    code, token = await tv.create()
    USED.append(code)
    question = await open_link(shop, LOST, code)
    with DropNextClaim(shop, forward=True) as drop:
        after, answer = await tap_and_answer(shop, LOST, question, f"tvp:{code}")
    assert drop.calls == 1
    methods = [s.get("method") for s in after]
    print(f"[lost answer] alert: {answer.get('text')!r}, screens: {methods}")
    assert "Не получилось подключить телевизор" in str(answer.get("text")), answer
    assert str(answer.get("show_alert")).lower() in ("true", "1")
    edits = [s for s in after if s["method"] == "editMessageText"]
    assert not edits, "the question must keep its buttons"
    assert not alerts(shop, t0), "a dropped connection must not page admins"
    status, body = await tv.poll(token, code)
    if tv.api_url:
        assert status == 200 and body["status"] == "paired", (status, body)
        assert body["subscriptionUrl"] == shop.billing.subscriptions[LOST]["URL"]
        return
    # In-memory model: the claim landed, the retry is the idempotent 200.
    after, _ = await tap_and_answer(shop, LOST, question, f"tvp:{code}")
    assert any("телевизор подключится" in (s.get("text") or "") for s in after), after


async def test_answer_lost_then_user_taps_again_before_the_tv_polls(env) -> None:
    shop, tv = env
    t0 = time.time()
    code, token = await tv.create()
    USED.append(code)
    question = await open_link(shop, LOST, code)
    with DropNextClaim(shop, forward=True):
        await tap_and_answer(shop, LOST, question, f"tvp:{code}")
    after, answer = await tap_and_answer(shop, LOST, question, f"tvp:{code}")
    assert any("телевизор подключится" in (s.get("text") or "") for s in after), (after, answer)
    assert not alerts(shop, t0)
    status, body = await tv.poll(token, code)
    if tv.api_url:
        assert status == 200 and body["status"] == "paired", (status, body)


async def test_connection_reset_before_the_claim(env) -> None:
    """The connection dropped before the claim reached the API: the code stays pending and the
    next tap pairs."""
    shop, tv = env
    t0 = time.time()
    code, token = await tv.create()
    USED.append(code)
    question = await open_link(shop, RESET, code)
    mark = len(shop.billing.bodies)
    with DropNextClaim(shop, forward=False):
        after, answer = await tap_and_answer(shop, RESET, question, f"tvp:{code}")
    assert "Не получилось подключить телевизор" in str(answer.get("text")), answer
    assert claims(shop, mark), "the bot did send the claim"
    status, body = await tv.poll(token, code)
    assert status == 200 and body["status"] == "pending", (status, body)
    after, _ = await tap_and_answer(shop, RESET, question, f"tvp:{code}")
    assert any("телевизор подключится" in (s.get("text") or "") for s in after), after
    assert not alerts(shop, t0)


@pytest.mark.parametrize(
    "payload",
    ["tv-K7M4QX9P", "tv-K7M4QX9ſ"],  # KELVIN SIGN for K, LONG S for S
)
async def test_typed_lookalike_code_is_an_ordinary_start(env, payload) -> None:
    """Typed by hand (Telegram deep links cannot carry these letters). Before the round-3 fix the
    Kelvin sign got the TV question with a button whose tap did nothing."""
    shop, _ = env
    t0 = time.time()
    mark = len(shop.billing.bodies)
    update = start_update(LOOKALIKE, payload)
    update["update_id"] = _next()
    since = await send(shop, update)
    shown = await wait_screens(shop, LOOKALIKE, since)
    texts = [s.get("text") or "" for s in shown]
    print(f"[lookalike {payload.encode('unicode_escape').decode()}] {[t[:60] for t in texts]}")
    assert not any("Подключить телевизор" in t for t in texts), texts
    assert not any(b.get("callback_data", "").startswith("tvp:") for s in shown for b in buttons(s))
    assert claims(shop, mark) == []
    assert not alerts(shop, t0)
    assert screens(shop, LOOKALIKE, since), "the ordinary /start answered"


async def test_bot_log_has_no_full_code(env) -> None:
    shop, _ = env
    log = shop.log()
    for uid in (LOST, RESET):
        assert shop.billing.subscriptions[uid]["URL"] not in log
    assert USED
    leaked = [c for c in USED if c in log]
    print(f"[log] bot log {len(log)} bytes, {len(USED)} codes checked, {len(leaked)} found")
    assert not leaked
