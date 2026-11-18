"""E2E: TV pairing with APP_BOT_RUBLE_PAYMENTS=true (the prod default since v0.61.6).

Same harness as test_tv_pair_e2e.py (real bot against tgmock; the TV side is a real compono-api
with ``SHOP_E2E_API_BIN`` or the in-memory claim model), but with rubles on and the prod gateway
rows, so the plan list the bot opens for a user without a subscription is the ruble one.

Matrix: paid user pairs, expired/unknown code, code already used, no subscription (plan list in
rubles, code stays valid), trial user pairs (trial counts as active), LIMITED user is refused.

    SHOP_E2E=1 SHOP_E2E_REDIS_SERVER=... [SHOP_E2E_API_BIN=...] uv run pytest tests/e2e -v -s
"""

from __future__ import annotations

import os
import subprocess
import time

import pytest
import pytest_asyncio

pytest.importorskip("tgmock")

from .harness import DEV_ID, ShopE2E, free_port, redis_server_binary  # noqa: E402
from .test_stars_only_e2e import PROD_ROWS, RUBLE_NOTE  # noqa: E402
from .test_tv_pair_e2e import (  # noqa: E402
    API_BIN,
    TV,
    _healthy,
    alerts,
    buttons,
    claims,
    deleted_message_ids,
    no_subscription_message,
    open_link,
    show,
    tap,
)

if not os.environ.get("SHOP_E2E") or not redis_server_binary():
    pytest.skip("set SHOP_E2E=1 and provide a redis-server to run the e2e", allow_module_level=True)

pytestmark = pytest.mark.asyncio(loop_scope="module")

PAID_ID = 731177001
OTHER_ID = 731177002
NOSUB_ID = 731177003
TRIAL_ID = 731177004
LIMITED_ID = 731177005


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env():
    shop = ShopE2E(extra_env={"APP_BOT_RUBLE_PAYMENTS": "true"})
    billing = shop.billing
    stars = [g for g in billing.gateways if g["Type"] == "TELEGRAM_STARS"]
    billing.gateways[:] = [*PROD_ROWS, *stars]
    billing.add_user(DEV_ID, "Owner", role="DEV")
    for uid in (PAID_ID, OTHER_ID, NOSUB_ID, TRIAL_ID, LIMITED_ID):
        billing.add_user(uid, f"u{uid}")
    billing.add_active_subscription(PAID_ID)
    billing.add_active_subscription(OTHER_ID)
    billing.add_active_subscription(TRIAL_ID, plan_id=4, plan_name="🎁 Пробный", is_trial=True)
    billing.add_active_subscription(LIMITED_ID)
    billing.subscriptions[LIMITED_ID]["Status"] = "LIMITED"

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
                    "BILLING_API_URL": billing.url,
                    "BILLING_INTERNAL_SECRET": "e2e",
                    "LOG_LEVEL": "info",
                    "LOG_DEST": "stdout",
                    "APP_ENVIRONMENT": "local",
                    "ROUTING_REFRESH_INTERVAL": "24h",
                },
                stdout=api_log,
                stderr=subprocess.STDOUT,
            )
            api_url = f"http://127.0.0.1:{port}"
            assert await shop.wait_for(lambda: _healthy(api_url), timeout=20), "api did not start"
            billing.tv_pair_api = api_url
        print(f"\n[tv rubles e2e] TV side: {api_url or 'in-memory fake'}")
        yield shop, TV(shop, api_url)
    finally:
        if api and api.poll() is None:
            api.terminate()
            api.wait(timeout=10)
        if api_log:
            api_log.close()
        await shop.stop()
        print(f"\n--- shop log: {shop.log_path}")


def _edited(after: list[dict]) -> dict:
    edited = [s for s in after if s["method"] == "editMessageText"]
    assert edited, f"no edit: {[s.get('text') for s in after]}"
    return edited[-1]


async def _pairs(shop: ShopE2E, tv: TV, uid: int) -> None:
    t0 = time.time()
    code, token = await tv.create()
    question = await open_link(shop, uid, code)
    mark = len(shop.billing.bodies)
    after = await tap(shop, uid, question, f"tvp:{code}")
    for s in after:
        show(f"pair {uid}", s)
    assert claims(shop, mark) == [{"code": code, "telegramId": uid}]
    done = _edited(after)
    assert "Телевизор попросит подтвердить подключение" in done["text"]
    assert not buttons(done)
    status, body = await tv.poll(token, code)
    if tv.api_url:
        assert status == 200 and body["status"] == "paired", body
        assert body["subscriptionUrl"] == shop.billing.subscriptions[uid]["URL"]
        status, _ = await tv.poll(token, code)
        assert status == 410
    else:
        assert body == {"status": "claimed", "tg": uid}
    assert not alerts(shop, t0)
    assert code not in shop.log()


async def test_paid_user_pairs(env) -> None:
    shop, tv = env
    await _pairs(shop, tv, PAID_ID)


async def test_trial_user_pairs(env) -> None:
    shop, tv = env
    await _pairs(shop, tv, TRIAL_ID)


async def test_expired_or_unknown_code(env) -> None:
    shop, _ = env
    code = "ZZZZ0000"
    question = await open_link(shop, PAID_ID, code)
    after = await tap(shop, PAID_ID, question, f"tvp:{code}")
    assert "Код устарел" in _edited(after)["text"]


async def test_code_used_by_someone_else(env) -> None:
    shop, tv = env
    code, _ = await tv.create()
    q1 = await open_link(shop, PAID_ID, code)
    await tap(shop, PAID_ID, q1, f"tvp:{code}")
    q2 = await open_link(shop, OTHER_ID, code)
    after = await tap(shop, OTHER_ID, q2, f"tvp:{code}")
    assert "Этот код уже использован" in _edited(after)["text"]


async def _refused_then_ruble_plans(shop: ShopE2E, tv: TV, uid: int) -> None:
    t0 = time.time()
    code, token = await tv.create()
    question = await open_link(shop, uid, code)
    after = await tap(shop, uid, question, f"tvp:{code}")
    for s in after:
        show(f"refused {uid}", s)
    retry = no_subscription_message(after)
    assert [b["callback_data"] for b in buttons(retry)] == [f"tvp:{code}"]
    assert retry["message_id"] not in deleted_message_ids(shop)
    plan_screens = [s for s in after if s is not retry and buttons(s)]
    plan_buttons = [b.get("text", "") for s in plan_screens for b in buttons(s)]
    assert any("Старт" in t and "₽" in t for t in plan_buttons), plan_buttons
    assert not any(RUBLE_NOTE in (s.get("text") or "") for s in after)
    status, body = await tv.poll(token, code)
    assert status == 200 and body["status"] == "pending", body
    assert not alerts(shop, t0)


async def test_no_subscription_opens_ruble_plans(env) -> None:
    shop, tv = env
    await _refused_then_ruble_plans(shop, tv, NOSUB_ID)


async def test_limited_user_is_refused(env) -> None:
    shop, tv = env
    await _refused_then_ruble_plans(shop, tv, LIMITED_ID)
