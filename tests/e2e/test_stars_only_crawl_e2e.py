"""E2E crawl: tap every button the bot shows and look for any ruble/card/SBP/website payment route.

Starts at /start for several kinds of users (new, paid, expiring, Ultra, proxy buyer) and walks
every callback button breadth-first, replaying the path from /start for each new screen. Every
message, edit and callback-answer text the user sees is checked, and every URL button is listed.
Opt-in like the other e2e modules (SHOP_E2E=1 plus a redis-server).
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest
import pytest_asyncio

pytest.importorskip("tgmock")

from .harness import DEV_ID, ShopE2E, redis_server_binary  # noqa: E402
from .test_stale_callback_e2e import (  # noqa: E402
    _bot_message,
    buttons,
    callback_update,
    send,
    user_screens,
)
from .test_stars_only_e2e import (  # noqa: E402
    PROD_ROWS,
    RUBLE_NOTE,
    _proxy_plan,
    _text_update,
    _ultra_plan,
)

if not os.environ.get("SHOP_E2E") or not redis_server_binary():
    pytest.skip("set SHOP_E2E=1 and provide a redis-server to run the e2e", allow_module_level=True)

pytestmark = pytest.mark.asyncio(loop_scope="module")

NEW = 820000001
PAID = 820000002
EXPIRING = 820000003
ULTRA = 820000004
PROXY_BUYER = 820000005

BANNED = (
    "₽",
    "СБП",
    "сбп",
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
# Words that contain a banned fragment but are fine.
ALLOWED_FRAGMENTS = ("Карточка", "карточк")
ALLOWED_URL_PREFIXES = (
    "https://t.me/",
    "tg://",
    "https://componovpn.com/connect/",
    "https://componovpn.com/ios",
    "https://componovpn.com/ru/terms",
    "https://componovpn.com/ru/privacy",
    "https://componovpn.com/terms",
    "https://componovpn.com/privacy",
)
# Buttons that leave the user flow or would loop forever.
SKIP = ("Закрыть",)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def shop():
    e2e = ShopE2E()
    billing = e2e.billing
    billing.gateways.extend(PROD_ROWS)
    billing.extra_plans.append(_ultra_plan())
    billing.hidden_plans.append(_proxy_plan())
    billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid in (NEW, PAID, EXPIRING, ULTRA, PROXY_BUYER):
        billing.add_user(uid, f"u{uid}")
    billing.add_active_subscription(PAID)
    billing.add_active_subscription(EXPIRING, days_left=1)
    billing.add_active_subscription(ULTRA, plan_id=38, plan_name="👑 Ультра", tag="ULTRA")
    billing.personal_proxies[PROXY_BUYER] = {
        "entitled": False,
        "proxy_plan_id": 5,
        "price_rub": 49,
        "proxies": [],
    }
    try:
        await e2e.start()
        yield e2e
    finally:
        await e2e.stop()
        print(f"\n--- shop log: {e2e.log_path}")


def _texts_since(shop: ShopE2E, since: float, uid: int) -> list[str]:
    out = []
    for r in user_screens(shop, since, uid):
        out.append(r.get("text") or r.get("caption") or "")
        out.extend(b.get("text", "") for b in buttons(r))
    for c in shop.tg.calls_of("answerCallbackQuery", since):
        if c["data"].get("text"):
            out.append(str(c["data"]["text"]))
    return out


def _problems(
    texts: list[str],
    screens: list[dict[str, Any]],
    banned: tuple[str, ...] = BANNED,
    allowed_urls: tuple[str, ...] = ALLOWED_URL_PREFIXES,
    allow_ruble_note: bool = True,
) -> list[str]:
    found = []
    for text in texts:
        clean = text
        if allow_ruble_note:
            clean = clean.replace(RUBLE_NOTE, "").replace("оплатить в рублях", "")
        for fragment in ALLOWED_FRAGMENTS:
            clean = clean.replace(fragment, "")
        for word in banned:
            if word in clean:
                found.append(f"'{word}' in: {text[:300]!r}")
    for screen in screens:
        for b in buttons(screen):
            url = b.get("url") or (b.get("web_app") or {}).get("url") or ""
            if url and not url.startswith(allowed_urls):
                found.append(f"url button {b.get('text')!r} -> {url}")
    return found


async def _replay(
    shop: ShopE2E, uid: int, path: list[str], start: str = "/start"
) -> dict[str, Any] | None:
    since = await send(shop, _text_update(uid, start))
    ok = await shop.wait_for(lambda: user_screens(shop, since, uid), timeout=15)
    if not ok:
        return None
    await __import__("asyncio").sleep(0.5)
    screen = user_screens(shop, since, uid)[-1]
    for label in path:
        button = next(
            (b for b in buttons(screen) if b.get("text") == label and b.get("callback_data")),
            None,
        )
        if button is None:
            return None
        message = _bot_message(
            screen["message_id"], screen.get("text", ""), screen.get("reply_markup"), uid
        )
        since = await send(shop, callback_update(button["callback_data"], message))
        await shop.wait_for(lambda: user_screens(shop, since, uid), timeout=6)
        await __import__("asyncio").sleep(0.5)
        screens = user_screens(shop, since, uid)
        if not screens:
            return {"_none": True, "since": since}
        screen = screens[-1]
    return screen


async def crawl(
    shop: ShopE2E,
    uid: int,
    max_depth: int = 4,
    max_taps: int = 90,
    start: str = "/start",
    prefix: list[str] | None = None,
    **problem_rules: Any,
) -> list[str]:
    findings: list[str] = []
    seen: set[str] = set()
    queue: list[list[str]] = [list(prefix or [])]
    taps = 0
    while queue and taps < max_taps:
        path = queue.pop(0)
        since = time.time()
        screen = await _replay(shop, uid, path, start)
        taps += len(path) + 1
        screens = user_screens(shop, since, uid)
        problems = _problems(_texts_since(shop, since, uid), screens, **problem_rules)
        for p in problems:
            findings.append(f"{uid} {' > '.join(path) or '/start'}: {p}")
        if not screen or screen.get("_none"):
            continue
        labels = [b.get("text", "") for b in buttons(screen)]
        signature = (screen.get("text") or "")[:120] + "|" + "|".join(labels)
        if signature in seen:
            continue
        seen.add(signature)
        text = (screen.get("text") or screen.get("caption") or "").replace("\n", " | ")
        print(f"\n[{uid} {' > '.join(path) or '/start'}] {text[:300]}")
        print(f"   buttons: {[(b.get('text'), b.get('url')) for b in buttons(screen)]}")
        if len(path) >= max_depth:
            continue
        for b in buttons(screen):
            if b.get("callback_data") and not any(s in b.get("text", "") for s in SKIP):
                queue.append([*path, b["text"]])
    return findings


@pytest.mark.parametrize("uid", [NEW, PAID, EXPIRING, ULTRA, PROXY_BUYER])
async def test_crawl_every_button(shop: ShopE2E, uid: int) -> None:
    findings = await crawl(shop, uid)
    for f in findings:
        print("FINDING:", f)
    assert not findings, findings


@pytest.mark.parametrize(
    ("uid", "start", "prefix"),
    [
        (PROXY_BUYER, "/start proxy", []),
        (NEW, "/start web_legacytoken", []),
        (PAID, "/start", ["👥 Пригласить"]),
    ],
)
async def test_crawl_from_other_entry_points(
    shop: ShopE2E, uid: int, start: str, prefix: list[str]
) -> None:
    findings = await crawl(
        shop, uid, max_depth=len(prefix) + 3, max_taps=40, start=start, prefix=prefix
    )
    for f in findings:
        print("FINDING:", f)
    assert not findings, findings
