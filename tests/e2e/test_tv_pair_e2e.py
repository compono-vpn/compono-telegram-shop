"""E2E: TV pairing through the real bot (COM-202).

The real shop app runs against tgmock and the in-memory billing (see test_stale_callback_e2e.py).
The "TV" side is either

- a real compono-api (``SHOP_E2E_API_BIN=/path/to/compono-api/server``, built from the
  compono-api ``feat/tv-pairing`` branch): the test creates the pairing with
  ``POST /api/v1/tv/pair``, the bot's claim is forwarded to that API, and the test polls
  ``/api/v1/tv/pair/poll`` like the TV app; the API keeps its state in the e2e Redis (DB 9) and
  reads subscriptions from the fake billing; or
- without it, an in-memory model of the claim endpoint in ``FakeBilling``.

    uv pip install -e /path/to/tgmock
    SHOP_E2E=1 [SHOP_E2E_REDIS_SERVER=...] [SHOP_E2E_API_BIN=...] uv run pytest tests/e2e -v -s
"""

from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio

pytest.importorskip("tgmock")

from aiohttp import ClientSession  # noqa: E402

from .harness import BOT_ID, DEV_ID, ShopE2E, free_port, redis_server_binary  # noqa: E402

if not os.environ.get("SHOP_E2E") or not redis_server_binary():
    pytest.skip("set SHOP_E2E=1 and provide a redis-server to run the e2e", allow_module_level=True)

pytestmark = pytest.mark.asyncio(loop_scope="module")

PAID_ID = 730177001  # active paid subscription
NOSUB_ID = 730177002  # no subscription, buys during the flow
OTHER_ID = 730177003  # a second subscriber
NEW_ID = 730177004  # never seen by the bot before
NOSUB_AGAIN_ID = 730177006  # no subscription, taps «Подключить» twice without buying
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
API_BIN = os.environ.get("SHOP_E2E_API_BIN")

_ids = {"update": 940000000}


def _next() -> int:
    _ids["update"] += 1
    return _ids["update"]


def _user(uid: int) -> dict[str, Any]:
    return {"id": uid, "is_bot": False, "first_name": "TV", "language_code": "ru"}


def start_update(uid: int, payload: str) -> dict[str, Any]:
    n = _next()
    return {
        "update_id": n,
        "message": {
            "message_id": n,
            "from": _user(uid),
            "chat": {"id": uid, "type": "private"},
            "date": int(time.time()),
            "text": f"/start {payload}",
            "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
        },
    }


def callback_update(uid: int, data: str, screen: dict[str, Any]) -> dict[str, Any]:
    n = _next()
    message = {
        "message_id": screen["message_id"],
        "from": {"id": BOT_ID, "is_bot": True, "first_name": "Compono"},
        "chat": {"id": uid, "type": "private"},
        "date": int(time.time()) - 5,
        "text": screen.get("text", ""),
        "reply_markup": screen.get("reply_markup"),
    }
    return {
        "update_id": n,
        "callback_query": {
            "id": f"cq-{n}",
            "from": _user(uid),
            "chat_instance": "e2e-tv",
            "data": data,
            "message": message,
        },
    }


class TV:
    """The TV app side: a real compono-api, or the fake's in-memory codes."""

    def __init__(self, shop: ShopE2E, api_url: str | None) -> None:
        self.shop = shop
        self.api_url = api_url

    async def create(self) -> tuple[str, str | None]:
        if self.api_url:
            async with ClientSession() as s:
                async with s.post(
                    f"{self.api_url}/api/v1/tv/pair",
                    json={"platform": "android-tv", "appVersion": "e2e"},
                    headers={"CF-Connecting-IP": f"198.51.100.{secrets.randbelow(250) + 1}"},
                ) as r:
                    assert r.status == 201, await r.text()
                    body = await r.json()
            assert body["botUrl"].endswith(f"?start=tv-{body['code']}")
            return body["code"], body["pollToken"]
        code = "".join(secrets.choice(ALPHABET) for _ in range(8))
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        self.shop.billing.tv_codes[code] = {"tg": None, "expiresAt": expires}
        return code, None

    async def poll(self, token: str | None, code: str) -> tuple[int, dict[str, Any]]:
        if not self.api_url:
            tg = self.shop.billing.tv_codes.get(code, {}).get("tg")
            return 200, ({"status": "claimed", "tg": tg} if tg else {"status": "pending"})
        await asyncio.sleep(2.1)  # the API allows one poll per 2 s per token
        async with ClientSession() as s:
            async with s.post(
                f"{self.api_url}/api/v1/tv/pair/poll", json={"pollToken": token}
            ) as r:
                return r.status, await r.json()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env():
    shop = ShopE2E()
    shop.billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid, name in (
        (PAID_ID, "Paid"),
        (NOSUB_ID, "NoSub"),
        (OTHER_ID, "Other"),
        (NOSUB_AGAIN_ID, "NoSubAgain"),
    ):
        shop.billing.add_user(uid, name)
    shop.billing.add_active_subscription(PAID_ID)
    shop.billing.add_active_subscription(OTHER_ID)
    api: subprocess.Popen[bytes] | None = None
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
                    "BILLING_INTERNAL_SECRET": "e2e",  # = the shop's APP_API_INTERNAL_SECRET
                    "LOG_LEVEL": "info",
                    "LOG_DEST": "stdout",
                    "APP_ENVIRONMENT": "local",
                    "ROUTING_REFRESH_INTERVAL": "24h",
                },
                stdout=api_log,
                stderr=subprocess.STDOUT,
            )
            api_url = f"http://127.0.0.1:{port}"
            ok = await shop.wait_for(lambda: _healthy(api_url), timeout=20)
            assert ok, "compono-api did not start"
            shop.billing.tv_pair_api = api_url
        print(
            f"\n[tv e2e] TV side: {'real compono-api ' + api_url if api_url else 'in-memory fake'}"
        )
        yield shop, TV(shop, api_url)
    finally:
        if api and api.poll() is None:
            api.terminate()
            api.wait(timeout=10)
        if api_log:
            api_log.close()
        await shop.stop()
        print(f"\n--- shop log: {shop.log_path}")


def _healthy(url: str) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"{url}/healthz", timeout=1) as r:  # noqa: S310 - local test URL
            return r.status == 200
    except Exception:
        return False


# ------------------------------------------------------------------ helpers


async def send(shop: ShopE2E, update: dict[str, Any]) -> float:
    await asyncio.sleep(1.0)  # the bot throttles 0.5 s per user
    since = time.time()
    assert await shop.send_update(update) == 200
    return since


def screens(shop: ShopE2E, uid: int, since: float) -> list[dict[str, Any]]:
    return [
        r
        for r in shop.tg._responses.get(uid, [])
        if r.get("method") in ("sendMessage", "editMessageText", "sendPhoto")
        and r.get("_at", 0) >= since
    ]


def buttons(screen: dict[str, Any]) -> list[dict[str, Any]]:
    return [b for row in (screen.get("reply_markup") or {}).get("inline_keyboard", []) for b in row]


def alerts(shop: ShopE2E, since: float) -> list[dict[str, Any]]:
    return [
        c
        for c in shop.tg.calls
        if c["at"] >= since
        and c["method"] in ("sendDocument", "sendMessage")
        and str(c["data"].get("chat_id")) == str(DEV_ID)
        and "#EventError" in str(c["data"])
    ]


async def wait_screens(shop: ShopE2E, uid: int, since: float, n: int = 1) -> list[dict[str, Any]]:
    ok = await shop.wait_for(lambda: len(screens(shop, uid, since)) >= n, timeout=15)
    assert ok, f"bot did not answer:\n{shop.log()[-3000:]}"
    await asyncio.sleep(0.7)
    return screens(shop, uid, since)


def claims(shop: ShopE2E, since_index: int) -> list[Any]:
    return [b for (_, route, b) in shop.billing.bodies[since_index:] if route == "/tv-pair/claim"]


def show(tag: str, screen: dict[str, Any]) -> None:
    text = (screen.get("text") or "").replace("\n", " | ")
    print(f"[{tag}] {screen.get('method')}: {text[:300]}")
    print(f"[{tag}] buttons: {[(b.get('text'), b.get('callback_data')) for b in buttons(screen)]}")


async def open_link(shop: ShopE2E, uid: int, code: str) -> dict[str, Any]:
    mark = len(shop.billing.bodies)
    since = await send(shop, start_update(uid, f"tv-{code}"))
    question = (await wait_screens(shop, uid, since))[-1]
    show("/start tv-", question)
    assert question["method"] == "sendMessage"
    assert f"{code[:4]}-{code[4:]}" in question["text"]
    assert "Нажмите, только если этот код сейчас на экране вашего телевизора" in question["text"]
    assert [b["callback_data"] for b in buttons(question)] == [f"tvp:{code}", "tvx"]
    assert claims(shop, mark) == [], "the bot must not claim on /start"
    return question


async def tap(shop: ShopE2E, uid: int, screen: dict[str, Any], data: str) -> list[dict[str, Any]]:
    since = await send(shop, callback_update(uid, data, screen))
    await shop.wait_for(lambda: shop.tg.calls_of("answerCallbackQuery", since), timeout=15)
    await asyncio.sleep(1.0)
    return screens(shop, uid, since)


# ------------------------------------------------------------------ tests


async def test_paid_user_pairs_tv(env) -> None:
    shop, tv = env
    t0 = time.time()
    code, token = await tv.create()
    status, body = await tv.poll(token, code)
    assert status == 200 and body["status"] == "pending", body

    question = await open_link(shop, PAID_ID, code)
    mark = len(shop.billing.bodies)
    after = await tap(shop, PAID_ID, question, f"tvp:{code}")
    for s in after:
        show("tap Подключить", s)
    assert claims(shop, mark) == [{"code": code, "telegramId": PAID_ID}]
    edited = [s for s in after if s["method"] == "editMessageText"]
    assert edited and "телевизор подключится через несколько секунд" in edited[-1]["text"]
    assert not buttons(edited[-1])

    status, body = await tv.poll(token, code)
    print(f"[TV poll] {status} {body if not tv.api_url else {**body, 'subscriptionUrl': '<url>'}}")
    if tv.api_url:
        assert status == 200 and body["status"] == "paired"
        assert body["subscriptionUrl"] == shop.billing.subscriptions[PAID_ID]["URL"]
        status, body = await tv.poll(token, code)
        assert status == 410, "the URL is handed out once"
    else:
        assert body == {"status": "claimed", "tg": PAID_ID}
    assert not alerts(shop, t0)
    assert code not in shop.log(), "the full code must never be logged"


async def test_user_without_subscription_gets_plans_then_retries(env) -> None:
    shop, tv = env
    code, token = await tv.create()
    question = await open_link(shop, NOSUB_ID, code)
    after = await tap(shop, NOSUB_ID, question, f"tvp:{code}")
    for s in after:
        show("no subscription", s)
    edited = [
        s
        for s in after
        if s["method"] == "editMessageText" and s["message_id"] == question["message_id"]
    ]
    assert edited and "нужна активная подписка" in edited[-1]["text"]
    assert [b["callback_data"] for b in buttons(edited[-1])] == [f"tvp:{code}"]
    others = [s for s in after if s is not edited[-1]]
    assert any("Старт" in b.get("text", "") for s in others for b in buttons(s)), (
        "the plan list was not opened"
    )
    status, body = await tv.poll(token, code)
    assert body["status"] == "pending", "a 422 claim leaves the code pending"

    # The user buys, then taps «Подключить» again on the same message.
    shop.billing.add_active_subscription(NOSUB_ID)
    after = await tap(shop, NOSUB_ID, edited[-1], f"tvp:{code}")
    done = [s for s in after if s["method"] == "editMessageText"]
    assert done and "телевизор подключится" in done[-1]["text"]
    status, body = await tv.poll(token, code)
    assert body["status"] in ("paired", "claimed"), body


async def test_second_tap_without_subscription_is_quiet(env) -> None:
    """Regression: tapping «Подключить» again while still without a subscription produces the
    same text and buttons, so Telegram refuses the edit with "message is not modified". tgmock
    does not emulate that refusal, so it is injected for the second tap. The bot must answer the
    tap, send no #EventError and not push the user to the main menu."""
    shop, tv = env
    code, token = await tv.create()
    question = await open_link(shop, NOSUB_AGAIN_ID, code)
    after = await tap(shop, NOSUB_AGAIN_ID, question, f"tvp:{code}")
    edited = [
        s
        for s in after
        if s["method"] == "editMessageText" and s["message_id"] == question["message_id"]
    ]
    assert edited and "нужна активная подписка" in edited[-1]["text"]

    t0 = time.time()
    shop.tg.failures["editMessageText"] = (
        400,
        "Bad Request: message is not modified: specified new message content and reply markup "
        "are exactly the same as a current content and reply markup of the message",
    )
    try:
        since = await send(shop, callback_update(NOSUB_AGAIN_ID, f"tvp:{code}", edited[-1]))
        await shop.wait_for(lambda: shop.tg.calls_of("answerCallbackQuery", since), timeout=15)
        await shop.wait_for(lambda: alerts(shop, t0), timeout=4)
    finally:
        shop.tg.failures.pop("editMessageText", None)
    answers = shop.tg.calls_of("answerCallbackQuery", since)
    print(f"[second tap] answers={len(answers)} alerts={len(alerts(shop, t0))}")
    assert answers, "the tap was not answered"
    assert not alerts(shop, t0), "an unchanged message must not page admins"
    status, body = await tv.poll(token, code)
    assert body["status"] == "pending", "the code stays valid after a 422"


async def test_code_used_by_someone_else(env) -> None:
    shop, tv = env
    code, _ = await tv.create()
    q1 = await open_link(shop, PAID_ID, code)
    await tap(shop, PAID_ID, q1, f"tvp:{code}")
    q2 = await open_link(shop, OTHER_ID, code)
    after = await tap(shop, OTHER_ID, q2, f"tvp:{code}")
    edited = [s for s in after if s["method"] == "editMessageText"]
    assert edited and "Этот код уже использован" in edited[-1]["text"]


async def test_expired_or_unknown_code(env) -> None:
    shop, _ = env
    code = "ZZZZ0000"
    question = await open_link(shop, PAID_ID, code)
    after = await tap(shop, PAID_ID, question, f"tvp:{code}")
    edited = [s for s in after if s["method"] == "editMessageText"]
    assert edited and "Код устарел" in edited[-1]["text"]


async def test_cancel_does_not_claim(env) -> None:
    shop, tv = env
    code, token = await tv.create()
    question = await open_link(shop, PAID_ID, code)
    mark = len(shop.billing.bodies)
    after = await tap(shop, PAID_ID, question, "tvx")
    edited = [s for s in after if s["method"] == "editMessageText"]
    assert edited and "Отменено" in edited[-1]["text"]
    assert claims(shop, mark) == []
    status, body = await tv.poll(token, code)
    assert body["status"] == "pending"


async def test_new_user_via_tv_link_has_no_source(env) -> None:
    shop, tv = env
    code, _ = await tv.create()
    mark = len(shop.billing.bodies)
    await open_link(shop, NEW_ID, code)
    created = [
        b for (m, route, b) in shop.billing.bodies[mark:] if m == "POST" and route == "/users"
    ]
    print(f"[new user] billing create_user bodies: {created}")
    assert created, "the new user was not synced to billing"
    assert created[0]["telegram_id"] == NEW_ID
    assert created[0]["source"] is None and created[0]["attribution"] is None


async def test_source_link_still_attributes(env) -> None:
    shop, _ = env
    uid = 730177005
    mark = len(shop.billing.bodies)
    since = await send(shop, start_update(uid, "source-a1_site-header_lios_ry"))
    await wait_screens(shop, uid, since)
    created = [
        b for (m, route, b) in shop.billing.bodies[mark:] if m == "POST" and route == "/users"
    ]
    assert created and created[0]["source"] == "site-header"
    assert created[0]["attribution"]["first_touch"]["ref"] == "site-header"


async def test_plain_start_still_opens_main_menu(env) -> None:
    shop, _ = env
    n = _next()
    update = start_update(PAID_ID, "x")
    update["message"]["text"] = "/start"
    update["update_id"] = n
    since = await send(shop, update)
    menu = (await wait_screens(shop, PAID_ID, since))[-1]
    assert any("Подписк" in b.get("text", "") for b in buttons(menu))
