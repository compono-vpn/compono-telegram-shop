import pytest
from aiogram_dialog.widgets.kbd import Start

from src.bot.routers.menu.dialog import tg_proxy
from src.bot.routers.menu.getters import tg_proxy_getter
from src.bot.states import Subscription
from src.infrastructure.billing.models import BillingTGProxy
from tests.conftest import (
    make_billing_client,
    make_dialog_manager,
    make_subscription,
    make_user,
    unwrap_inject,
)

PUBLIC_RU = "https://t.me/webproxy?server=russia.compono.online&secret=aa"
PUBLIC_EU = "https://t.me/webproxy?server=eu.compono.online&secret=bb"
STABLE = "https://t.me/webproxy?server=stable.compono.online&secret=cc"
PHONE = "tg://proxy?server=phone.compono.online&port=443&secret=ee00"


def _public_web(id, server, link):
    return BillingTGProxy(
        id=id, server=server, port=443, secret="x", kind="WEB", link=link, is_public=True
    )


def _paid_web():
    return BillingTGProxy(
        id=9, server="stable.compono.online", port=443, secret="x", kind="WEB",
        link=STABLE, is_public=False,
    )


def _paid_phone():
    return BillingTGProxy(
        id=10, server="phone.compono.online", port=443, secret="ee00", kind="MTPROTO",
        link=PHONE, is_public=False,
    )


def _public_rows():
    return [_public_web(7, "russia.compono.online", PUBLIC_RU), _public_web(8, "eu.compono.online", PUBLIC_EU)]


async def _render(proxies, subscription):
    return await unwrap_inject(tg_proxy_getter)(
        dialog_manager=make_dialog_manager(),
        user=make_user(subscription=subscription),
        billing=make_billing_client(tg_proxies=proxies),
    )


def test_is_public_defaults_to_true_when_billing_does_not_send_it():
    legacy = BillingTGProxy.model_validate(
        {"id": 1, "server": "s", "port": 443, "secret": "x", "kind": "WEB", "link": "l"}
    )
    assert legacy.is_public is True


def test_is_public_false_is_parsed():
    paid = BillingTGProxy.model_validate(
        {"id": 9, "server": "s", "port": 443, "secret": "x", "kind": "WEB", "link": "l", "is_public": False}
    )
    assert paid.is_public is False


@pytest.mark.parametrize(
    "subscription",
    [
        None,
        make_subscription(active=False),
        make_subscription(plan_id=1, active=False),
        make_subscription(is_trial=True),
        make_subscription(plan_id=4),
        make_subscription(plan_id=4, is_trial=True),
        make_subscription(plan_id=0),
        make_subscription(plan_id=-1),
    ],
    ids=[
        "none",
        "expired-default-plan",
        "expired-plan-1",
        "trial-flag",
        "plan-4-without-trial-flag",
        "plan-4-trial",
        "plan-0",
        "plan-minus-1",
    ],
)
async def test_free_user_sees_public_proxies_and_paid_teaser(subscription):
    result = await _render(_public_rows(), subscription)
    msg = result["proxy_message"]

    assert PUBLIC_RU in msg and PUBLIC_EU in msg
    assert "временно недоступны" not in msg
    assert "входит в платный тариф" in msg
    assert "стабильный" in msg
    assert result["show_plans_offer"] is True


async def test_paid_user_gets_phone_proxy_and_stable_web_first():
    rows = _public_rows() + [_paid_web(), _paid_phone()]
    result = await _render(rows, make_subscription(plan_id=2))
    msg = result["proxy_message"]

    assert result["show_plans_offer"] is False
    assert "входит в платный тариф" not in msg
    assert f'<a href="{PHONE}">Подключить phone.compono.online:443</a>' in msg
    stable = f'<a href="{STABLE}">Подключить stable.compono.online</a> — стабильный'
    assert stable in msg
    assert msg.index(stable) < msg.index(PUBLIC_RU) < msg.index(PUBLIC_EU)
    assert msg.index("📱") < msg.index(PHONE) < msg.index("💻") < msg.index(stable)
    assert "Запасные" in msg


async def test_paid_user_without_stable_row_keeps_plain_desktop_list():
    result = await _render(_public_rows(), make_subscription(plan_id=2))
    msg = result["proxy_message"]

    assert "Запасные" not in msg
    assert "стабильный" not in msg
    assert "временно недоступны" in msg
    assert result["show_plans_offer"] is False


def test_proxy_window_has_plans_button_for_free_users():
    starts = [
        b
        for row in tg_proxy.keyboard.buttons
        for b in getattr(row, "buttons", [row])
        if isinstance(b, Start)
    ]
    assert len(starts) == 1
    assert starts[0].state == Subscription.MAIN
    assert starts[0].widget_id == "proxy_plans"
