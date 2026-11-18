"""E2E: the real shop bot when Telegram refuses answerCallbackQuery, plus the main menu flows.

Runs the actual app (uvicorn + aiogram + aiogram-dialog + dishka + Redis) against tgmock's fake
Bot API and an in-memory billing seeded with real stage plan/gateway responses. Opt-in: needs
``tgmock`` importable and a working ``redis-server``; otherwise the module is skipped (CI installs
neither).

    uv pip install -e ../tgmock
    SHOP_E2E=1 [SHOP_E2E_REDIS_SERVER=/path/to/redis-server] uv run pytest tests/e2e -v -s

Prod origin: 2026-11-16 19:36:50 UTC, user 730166164 tapped WILL_THINK in the cancel-reason
survey; the answer was saved, then ``callback.answer()`` failed with "query is too old ..." and the
error middleware sent an #EventError card to the admin and pushed the user back to the main menu.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any

import pytest
import pytest_asyncio

pytest.importorskip("tgmock")

from .harness import BOT_ID, DEV_ID, ShopE2E, redis_server_binary  # noqa: E402

if not os.environ.get("SHOP_E2E") or not redis_server_binary():
    pytest.skip("set SHOP_E2E=1 and provide a redis-server to run the e2e", allow_module_level=True)

# The fake servers live on the module fixture's loop, so the tests must run on it too.
pytestmark = pytest.mark.asyncio(loop_scope="module")

USER_ID = 730166164
PAID_ID = 730166165  # a second user with an active paid subscription (for Подключиться)
STALE = "Bad Request: query is too old and response timeout expired or query ID is invalid"
OTHER_400 = "Bad Request: chat not found"
THANKS = "Спасибо за ответ"

_ids = {"update": 839206000}


def _next_update_id() -> int:
    _ids["update"] += 1
    return _ids["update"]


def _user(uid: int = USER_ID) -> dict[str, Any]:
    return {"id": uid, "is_bot": False, "first_name": "Vitaliy", "language_code": "ru"}


def _bot_message(
    message_id: int, text: str, markup: Any = None, uid: int = USER_ID
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "message_id": message_id,
        "from": {"id": BOT_ID, "is_bot": True, "first_name": "Compono"},
        "chat": {"id": uid, "type": "private"},
        "date": int(time.time()) - 60,
        "text": text,
    }
    if markup:
        msg["reply_markup"] = markup
    return msg


def start_update(user_id: int = USER_ID) -> dict[str, Any]:
    uid = _next_update_id()
    return {
        "update_id": uid,
        "message": {
            "message_id": uid,
            "from": _user(user_id),
            "chat": {"id": user_id, "type": "private"},
            "date": int(time.time()),
            "text": "/start",
            "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
        },
    }


def callback_update(data: str, message: dict[str, Any]) -> dict[str, Any]:
    uid = _next_update_id()
    return {
        "update_id": uid,
        "callback_query": {
            "id": f"cq-{uid}",
            "from": _user(message["chat"]["id"]),
            "chat_instance": "e2e",
            "data": data,
            "message": message,
        },
    }


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def shop():
    e2e = ShopE2E()
    e2e.billing.add_user(DEV_ID, "Owner", role="DEV")
    e2e.billing.add_user(USER_ID, "Vitaliy")
    e2e.billing.add_user(PAID_ID, "Paid")
    e2e.billing.add_active_subscription(PAID_ID)
    try:
        await e2e.start()
        yield e2e
    finally:
        await e2e.stop()
        print(f"\n--- shop log: {e2e.log_path}")


# ------------------------------------------------------------------ helpers


async def send(shop: ShopE2E, update: dict[str, Any]) -> float:
    """Deliver an update like Telegram does; wait out the bot's 0.5 s per-user throttle first."""
    await asyncio.sleep(1.0)
    since = time.time()
    assert await shop.send_update(update) == 200
    return since


def user_screens(shop: ShopE2E, since: float, uid: int = USER_ID) -> list[dict[str, Any]]:
    """Messages the bot sent or edited for the user, with the message_id tgmock assigned."""
    return [
        r
        for r in shop.tg._responses.get(uid, [])
        if r.get("method") in ("sendMessage", "editMessageText", "sendPhoto")
        and r.get("_at", 0) >= since
    ]


def admin_alerts(shop: ShopE2E, since: float) -> list[dict[str, Any]]:
    """Anything sent to the dev/admin chat (#EventError goes out as sendDocument + traceback)."""
    return [
        c
        for c in shop.tg.calls
        if c["at"] >= since
        and c["method"] in ("sendDocument", "sendMessage")
        and str(c["data"].get("chat_id")) == str(DEV_ID)
    ]


async def redirect_tasks(shop: ShopE2E) -> int:
    if not await shop.redis("EXISTS", "taskiq"):
        return 0
    return str(await shop.redis("XRANGE", "taskiq", "-", "+")).count("redirect_to_main_menu")


def buttons(screen: dict[str, Any]) -> list[dict[str, Any]]:
    markup = screen.get("reply_markup") or {}
    return [b for row in markup.get("inline_keyboard", []) for b in row]


async def wait_screen(
    shop: ShopE2E, since: float, uid: int = USER_ID, timeout: float = 15
) -> dict[str, Any]:
    ok = await shop.wait_for(lambda: user_screens(shop, since, uid), timeout=timeout)
    assert ok, f"bot did not answer:\n{shop.log()[-3000:]}"
    await asyncio.sleep(0.5)  # let edits settle
    return user_screens(shop, since, uid)[-1]


async def tap(shop: ShopE2E, screen: dict[str, Any], label: str) -> dict[str, Any]:
    button = next((b for b in buttons(screen) if label in b.get("text", "")), None)
    assert button, f"no button '{label}' in {[b.get('text') for b in buttons(screen)]}"
    uid = int(screen["chat_id"])
    message = _bot_message(
        screen["message_id"], screen.get("text", ""), screen.get("reply_markup"), uid
    )
    since = await send(shop, callback_update(button["callback_data"], message))
    return await wait_screen(shop, since, uid)


def show(tag: str, screen: dict[str, Any]) -> None:
    text = (screen.get("text") or screen.get("caption") or "").replace("\n", " | ")
    print(f"\n[{tag}] {screen.get('method')}: {text[:400]}")
    print(f"[{tag}] buttons: {[b.get('text') for b in buttons(screen)]}")


async def survey_tap_with_answer_failure(shop: ShopE2E, error: str, gateway: str) -> dict:
    payment_id = str(uuid.uuid4())
    shop.billing.add_transaction(payment_id, USER_ID, gateway)
    redirects_before = await redirect_tasks(shop)
    survey = _bot_message(9000 + _ids["update"] % 1000, "Почему не получилось оплатить?")
    shop.tg.failures["answerCallbackQuery"] = (400, error)
    try:
        since = await send(shop, callback_update(f"cs:{payment_id}:WILL_THINK", survey))
        await shop.wait_for(lambda: shop.tg.calls_of("answerCallbackQuery", since), timeout=15)
        # give the error middleware time to alert / queue a redirect if it is going to
        await shop.wait_for(lambda: admin_alerts(shop, since), timeout=4)
        await asyncio.sleep(1.0)
    finally:
        shop.tg.failures.pop("answerCallbackQuery", None)
    keys = await shop.redis("KEYS", f"*{payment_id}*")
    return {
        "stored": await shop.redis("HGETALL", keys[0]) if keys else {},
        "screens": user_screens(shop, since),
        "answers": shop.tg.calls_of("answerCallbackQuery", since),
        "alerts": admin_alerts(shop, since),
        "redirects": await redirect_tasks(shop) - redirects_before,
    }


# ------------------------------------------------------------------ tests


async def test_start_opens_main_menu(shop: ShopE2E) -> None:
    since = await send(shop, start_update())
    menu = await wait_screen(shop, since)
    show("/start", menu)
    assert buttons(menu), "main menu has no keyboard"
    assert any("Подписк" in b.get("text", "") for b in buttons(menu))
    assert not admin_alerts(shop, since)


async def test_subscription_plans_durations_payment_methods(shop: ShopE2E) -> None:
    since = await send(shop, start_update())
    menu = await wait_screen(shop, since)
    plans = await tap(shop, menu, "Подписк")
    show("Подписка", plans)
    if not any("Старт" in b.get("text", "") for b in buttons(plans)):
        plans = await tap(shop, plans, "Купить")
        show("Купить", plans)
    durations = await tap(shop, plans, "Старт")
    show("Старт", durations)
    assert any("1 месяц — 119" in b.get("text", "") for b in buttons(durations))
    methods = await tap(shop, durations, "1 месяц")
    show("1 месяц", methods)
    texts = " ".join(b.get("text", "") for b in buttons(methods)) + (methods.get("text") or "")
    assert "119" in texts, "Start/30 days price (119) not shown on the payment method screen"
    assert not admin_alerts(shop, since), admin_alerts(shop, since)


async def test_connect_for_paid_user(shop: ShopE2E) -> None:
    since = await send(shop, start_update(PAID_ID))
    menu = await wait_screen(shop, since, PAID_ID)
    show("/start paid", menu)
    connect = await tap(shop, menu, "Подключиться")
    show("Подключиться", connect)
    labels = [b.get("text", "") for b in buttons(connect)]
    guide = next(b for b in buttons(connect) if "инструкция" in b.get("text", "").lower())
    print("[Подключиться] guide url:", guide.get("url"))
    assert "/connect/" in (guide.get("url") or "")
    before_link = time.time()
    await tap(shop, connect, "ссылку")
    sent = [r for r in user_screens(shop, before_link, PAID_ID) if r["method"] == "sendMessage"]
    for r in sent:
        show("Просто дай ссылку", r)
    assert any("api/sub/e2e730166165" in (r.get("text") or "") for r in sent), labels
    assert not admin_alerts(shop, since), admin_alerts(shop, since)


async def test_stale_answer_is_benign(shop: ShopE2E) -> None:
    r = await survey_tap_with_answer_failure(shop, STALE, "PLATEGA")
    print("\n[stale] fake API: answerCallbackQuery -> 400", STALE)
    print("[stale] stored answer ->", r["stored"])
    print("[stale] screens ->", [s.get("text") for s in r["screens"]])
    print("[stale] answerCallbackQuery calls ->", len(r["answers"]))
    print("[stale] admin alerts ->", len(r["alerts"]), "| main-menu redirects ->", r["redirects"])
    assert r["stored"].get("reason") == "WILL_THINK", "survey answer was not stored"
    assert r["stored"].get("gateway") == "PLATEGA"
    assert any(THANKS in (s.get("text") or "") for s in r["screens"]), "no thanks text"
    assert r["answers"], "bot never called answerCallbackQuery"
    assert r["alerts"] == [], f"unexpected admin alert: {r['alerts']}"
    assert r["redirects"] == 0
    assert "Ignoring stale callback answer for user '730166164'" in shop.log()


async def test_other_bad_request_still_alerts(shop: ShopE2E) -> None:
    r = await survey_tap_with_answer_failure(shop, OTHER_400, "TELEGRAM_STARS")
    print("\n[control] fake API: answerCallbackQuery -> 400", OTHER_400)
    print("[control] stored answer ->", r["stored"])
    print(
        "[control] admin alerts ->",
        [(a["method"], str(a["data"].get("caption", ""))[:160]) for a in r["alerts"]],
    )
    print("[control] main-menu redirects ->", r["redirects"])
    assert r["stored"].get("reason") == "WILL_THINK"
    assert r["alerts"], "a non-stale 400 must still reach the admin"
    assert any("chat not found" in str(a["data"]) for a in r["alerts"])
    assert r["redirects"] == 1


async def test_start_still_works_after_errors(shop: ShopE2E) -> None:
    since = await send(shop, start_update())
    menu = await wait_screen(shop, since)
    show("/start again", menu)
    assert buttons(menu)
    assert not admin_alerts(shop, since)
    print("\n[billing] routes the fake does not model:", sorted(set(shop.billing.unknown)))
