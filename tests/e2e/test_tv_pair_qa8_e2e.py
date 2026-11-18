"""QA round 8 E2E for TV pairing (COM-202): the TV link right after the cancel survey's «Другое».

After a cancelled payment the bot asks why; «Другое» asks for free text and, for the next 30
minutes, treated every message as that text, commands included. A user who then scanned the
TV's QR code had ``/start tv-<CODE>`` swallowed: no confirmation question (the TV could not pair)
and the full code was stored as the survey answer and sent to the admin chat. A command is never
a survey answer now.

Same harness as ``test_tv_pair_e2e.py`` (real bot, tgmock, fake billing, optionally the real
compono-api via ``SHOP_E2E_API_BIN``). Own Telegram IDs.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid

import pytest
import pytest_asyncio

pytest.importorskip("tgmock")

from .harness import DEV_ID, ShopE2E, free_port, redis_server_binary  # noqa: E402
from .test_tv_pair_e2e import (  # noqa: E402
    TV,
    _healthy,
    _next,
    _user,
    open_link,
    screens,
    send,
    tap,
    wait_screens,
)

if not os.environ.get("SHOP_E2E") or not redis_server_binary():
    pytest.skip("set SHOP_E2E=1 and provide a redis-server to run the e2e", allow_module_level=True)

pytestmark = pytest.mark.asyncio(loop_scope="module")

SURVEY_TV = 730899001  # paid; tapped «Другое» in the cancel survey, then scans the TV
SURVEY_START = 730899002  # tapped «Другое», then sends a plain /start
SURVEY_TEXT = 730899003  # tapped «Другое», then types the answer (must still be taken)
API_BIN = os.environ.get("SHOP_E2E_API_BIN")


async def awaiting_survey_text(shop: ShopE2E, uid: int) -> str:
    """The state the «Другое» button leaves behind (CancelSurveyAwaitingTextKey, 30 min)."""
    payment_id = str(uuid.uuid4())
    await shop.redis("SET", f"cancel_survey_awaiting_text:{uid}", payment_id, "EX", "1800")
    return payment_id


def message_update(uid: int, text: str) -> dict:
    n = _next()
    message = {
        "message_id": n,
        "date": int(time.time()),
        "chat": {"id": uid, "type": "private"},
        "from": _user(uid),
        "text": text,
    }
    if text.startswith("/"):
        message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    return {"update_id": n, "message": message}


def admin_texts(shop: ShopE2E, since: float) -> list[str]:
    return [
        str(c["data"])
        for c in shop.tg.calls
        if c["at"] >= since and str(c["data"].get("chat_id")) == str(DEV_ID)
    ]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env():
    shop = ShopE2E()
    shop.billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid in (SURVEY_TV, SURVEY_START, SURVEY_TEXT):
        shop.billing.add_user(uid, f"QA8{uid}")
    shop.billing.add_active_subscription(SURVEY_TV)
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


async def test_tv_link_after_survey_other_still_pairs(env) -> None:
    shop, tv = env
    t0 = time.time()
    payment_id = await awaiting_survey_text(shop, SURVEY_TV)
    code, token = await tv.create()

    question = await open_link(shop, SURVEY_TV, code)  # asserts the confirmation question
    shown = await tap(shop, SURVEY_TV, question, f"tvp:{code}")
    assert any("Телевизор попросит подтвердить" in (s.get("text") or "") for s in shown), shown

    leaked = [t for t in admin_texts(shop, t0) if code in t]
    assert not leaked, "the full pairing code reached the admin chat"
    stored = await shop.redis("HGETALL", f"cancel_survey:{payment_id}")
    assert not stored, f"the TV link was stored as the survey answer: {stored}"
    assert code not in shop.log(), "the full pairing code is in the bot log"
    if tv.api_url:
        status, body = await tv.poll(token, code)
        assert status == 200 and body["status"] == "paired", (status, body)


async def test_plain_start_after_survey_other_opens_menu(env) -> None:
    shop, _ = env
    await awaiting_survey_text(shop, SURVEY_START)
    since = await send(shop, message_update(SURVEY_START, "/start"))
    shown = await wait_screens(shop, SURVEY_START, since)
    assert shown, "plain /start was swallowed by the survey"
    assert not any("Спасибо" in (s.get("text") or "") for s in shown), shown


async def test_typed_answer_is_still_taken(env) -> None:
    shop, _ = env
    t0 = time.time()
    payment_id = await awaiting_survey_text(shop, SURVEY_TEXT)
    since = await send(shop, message_update(SURVEY_TEXT, "дорого"))
    await shop.wait_for(lambda: screens(shop, SURVEY_TEXT, since), timeout=15)
    stored = await shop.redis("HGETALL", f"cancel_survey:{payment_id}")
    assert stored, "a typed answer must still be stored"
    assert any("дорого" in t for t in admin_texts(shop, t0))
