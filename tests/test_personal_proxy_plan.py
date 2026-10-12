from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
from aiogram_dialog.widgets.kbd import Button

from src.bot import proxy_view
from src.bot.routers.menu.dialog import tg_proxy
from src.bot.routers.menu.getters import tg_proxy_getter
from src.bot.routers.menu.handlers import on_start_command
from src.bot.routers.subscription.getters import proxy_confirm_getter, proxy_success_getter
from src.bot.routers.subscription.handlers import on_buy_proxy
from src.bot.states import MainMenu, Subscription
from src.core.constants import USER_KEY
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.models import BillingPersonalProxies, BillingTGProxy
from src.infrastructure.kafka.consumer import UserNotificationConsumer
from tests.conftest import (
    make_billing_client,
    make_dialog_manager,
    make_subscription,
    make_user,
    unwrap_inject,
)
from tests.test_on_start_command import _setup

PUBLIC_WEB = "https://t.me/webproxy?server=russia.compono.online&secret=aa"
PERSONAL_WEB = "https://t.me/webproxy?server=me.compono.online&secret=bb"
PERSONAL_PHONE = "tg://proxy?server=me.compono.online&port=443&secret=cc"
PUBLIC_PHONE = "tg://proxy?server=pub.compono.online&port=443&secret=dd"
PAY_URL = "https://pay.example.invalid/checkout"
EXPIRES = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)


def _row(id, kind, server, link, is_public, port=443):
    return BillingTGProxy(
        id=id, server=server, port=port, secret="x", kind=kind, link=link, is_public=is_public
    )


def _public_rows():
    return [_row(7, "WEB", "russia.compono.online", PUBLIC_WEB, True)]


def _personal_rows():
    return [
        _row(20, "MTPROTO", "me.compono.online", PERSONAL_PHONE, False),
        _row(21, "WEB", "me.compono.online", PERSONAL_WEB, False),
        *_public_rows(),
    ]


def _entitled(source, expires_at=None, proxies=None):
    return BillingPersonalProxies(
        entitled=True,
        source=source,
        expires_at=expires_at,
        proxy_plan_id=9,
        price_rub=25,
        proxies=proxies if proxies is not None else _personal_rows(),
    )


def _not_entitled(proxies=None):
    return BillingPersonalProxies(
        entitled=False,
        proxy_plan_id=9,
        price_rub=25,
        proxies=proxies if proxies is not None else _public_rows(),
    )


async def _render(personal=None, personal_error=None, user=None, **kwargs):
    billing = make_billing_client(personal=personal, personal_error=personal_error, **kwargs)
    result = await unwrap_inject(tg_proxy_getter)(
        dialog_manager=make_dialog_manager(),
        user=user or make_user(),
        billing=billing,
    )
    return result, billing


class TestProxyScreenStates:
    async def test_vpn_subscriber_gets_personal_links_free(self):
        result, _ = await _render(personal=_entitled("vpn_plan"))
        msg = result["proxy_message"]

        assert "бесплатно входит в вашу подписку Compono VPN" in msg
        assert "до 3 устройств одновременно" in msg
        assert "выключенным VPN" in msg
        assert f'<a href="{PERSONAL_PHONE}">Подключить me.compono.online:443</a> — личный' in msg
        assert f'<a href="{PERSONAL_WEB}">Подключить me.compono.online</a> — личный' in msg
        assert msg.index(PERSONAL_WEB) < msg.index(PUBLIC_WEB)
        assert "25 ₽" not in msg and "<s>" not in msg
        assert result["can_buy_proxy"] is False
        assert result["can_renew_proxy"] is False
        assert result["show_plans_offer"] is False

    async def test_proxy_plan_buyer_sees_expiry_and_renew(self):
        result, _ = await _render(personal=_entitled("proxy_plan", EXPIRES))
        msg = result["proxy_message"]

        assert "Личный прокси действует до 12.11.2026." in msg
        assert "до 3 устройств одновременно" in msg
        assert PERSONAL_PHONE in msg and PERSONAL_WEB in msg
        assert "<s>" not in msg
        assert result["can_renew_proxy"] is True
        assert result["can_buy_proxy"] is False
        assert result["proxy_price"] == "25"
        assert result["show_plans_offer"] is False

    async def test_not_entitled_sees_public_links_and_offer(self):
        result, _ = await _render(personal=_not_entitled())
        msg = result["proxy_message"]

        assert PUBLIC_WEB in msg
        assert "<s>49 ₽</s> <b>25 ₽</b> в месяц" in msg
        assert "на ограниченное время" in msg
        assert "до 3 устройств" in msg
        assert "🎁 Подписчикам Compono VPN — бесплатно." in msg
        assert "платном тарифе" not in msg
        assert "входит в платный тариф" not in msg
        assert result["can_buy_proxy"] is True
        assert result["can_renew_proxy"] is False
        assert result["show_plans_offer"] is True

    async def test_not_entitled_without_public_phone_points_to_offer(self):
        result, _ = await _render(personal=_not_entitled())
        assert "Общих прокси для телефона нет — личный ниже." in result["proxy_message"]

    async def test_offer_uses_price_from_billing(self):
        personal = _not_entitled()
        personal.price_rub = 30
        result, _ = await _render(personal=personal)
        assert "<b>30 ₽</b>" in result["proxy_message"]
        assert result["proxy_price"] == "30"

    async def test_no_offer_when_proxy_plan_missing(self):
        personal = _not_entitled()
        personal.proxy_plan_id = 0
        result, _ = await _render(personal=personal)
        assert result["can_buy_proxy"] is False
        assert "<s>49 ₽</s>" not in result["proxy_message"]


class TestFallback:
    async def test_personal_error_falls_back_to_public_call(self):
        result, billing = await _render(tg_proxies=_public_rows())

        billing.get_personal_tg_proxies.assert_awaited_once()
        billing.get_tg_proxies.assert_awaited_once_with(0)
        assert PUBLIC_WEB in result["proxy_message"]
        assert result["can_buy_proxy"] is False
        assert result["can_renew_proxy"] is False
        assert result["show_plans_offer"] is True
        assert "платном тарифе" not in result["proxy_message"]

    async def test_fallback_keeps_plan_id_for_paid_subscriber(self):
        user = make_user(subscription=make_subscription(plan_id=3))
        result, billing = await _render(tg_proxies=_personal_rows(), user=user)

        billing.get_tg_proxies.assert_awaited_once_with(3)
        assert result["show_plans_offer"] is False
        assert PERSONAL_WEB in result["proxy_message"]

    async def test_both_calls_failing_never_raises(self):
        result, _ = await _render(tg_proxies_error=Exception("down"))
        assert result["has_proxies"] is False
        assert "Нет доступных прокси." in result["proxy_message"]


class TestWindowButtons:
    def _buttons(self):
        return {
            b.widget_id: b
            for row in tg_proxy.keyboard.buttons
            for b in getattr(row, "buttons", [row])
            if isinstance(b, Button)
        }

    def test_buy_and_renew_buttons_exist_and_are_conditional(self):
        buttons = self._buttons()
        assert "proxy_buy" in buttons and "proxy_renew" in buttons
        assert buttons["proxy_buy"].on_click.callback is buttons["proxy_renew"].on_click.callback

    def test_buy_visible_only_when_can_buy(self):
        buttons = self._buttons()
        assert buttons["proxy_buy"].is_({"can_buy_proxy": True}, None)
        assert not buttons["proxy_buy"].is_({"can_buy_proxy": False}, None)
        assert buttons["proxy_renew"].is_({"can_renew_proxy": True}, None)
        assert not buttons["proxy_renew"].is_({"can_renew_proxy": False}, None)


def _buy_args(personal, create_result=None, gateway=True):
    user = make_user()
    dm = make_dialog_manager()
    dm.middleware_data[USER_KEY] = user
    dm.start = AsyncMock()
    billing = make_billing_client(personal=personal)
    billing.get_gateway_by_type.return_value = MagicMock(Currency="RUB") if gateway else None
    billing.create_payment.return_value = create_result or MagicMock(ID=str(uuid4()), URL=PAY_URL)
    notification = AsyncMock()
    return user, dm, billing, notification


async def _buy(dm, billing, notification):
    await unwrap_inject(on_buy_proxy)(
        callback=MagicMock(),
        widget=MagicMock(),
        dialog_manager=dm,
        billing=billing,
        notification_service=notification,
    )


class TestBuyProxy:
    async def test_creates_platega_payment_for_proxy_plan_and_opens_confirm(self):
        user, dm, billing, notification = _buy_args(_not_entitled())

        await _buy(dm, billing, notification)

        billing.create_payment.assert_awaited_once_with(
            telegram_id=user.telegram_id,
            plan_id=9,
            duration_days=30,
            currency="RUB",
            gateway_type="PLATEGA",
            purchase_type="NEW",
            is_test=user.is_dev,
        )
        billing.get_gateway_by_type.assert_awaited_once_with("PLATEGA")
        dm.start.assert_awaited_once()
        assert dm.start.await_args.args[0] == Subscription.PROXY_CONFIRM
        assert dm.start.await_args.kwargs["data"] == {
            "payment_url": PAY_URL,
            "price": 25,
            "original_price": 49,
        }
        notification.notify_user.assert_not_awaited()

    async def test_renewal_uses_renew_purchase_type(self):
        _, dm, billing, notification = _buy_args(_entitled("proxy_plan", EXPIRES))

        await _buy(dm, billing, notification)

        assert billing.create_payment.await_args.kwargs["purchase_type"] == "RENEW"
        assert billing.create_payment.await_args.kwargs["plan_id"] == 9
        assert dm.start.await_args.args[0] == Subscription.PROXY_CONFIRM

    async def test_vpn_subscriber_is_never_charged(self):
        _, dm, billing, notification = _buy_args(_entitled("vpn_plan"))

        await _buy(dm, billing, notification)

        billing.create_payment.assert_not_awaited()
        dm.start.assert_not_awaited()

    async def test_payment_failure_notifies_user_and_stays_on_screen(self):
        _, dm, billing, notification = _buy_args(_not_entitled())
        billing.create_payment.side_effect = Exception("platega down")

        await _buy(dm, billing, notification)

        dm.start.assert_not_awaited()
        payload = notification.notify_user.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-subscription-payment-creation-failed"

    async def test_missing_gateway_notifies_user(self):
        _, dm, billing, notification = _buy_args(_not_entitled(), gateway=False)

        await _buy(dm, billing, notification)

        billing.create_payment.assert_not_awaited()
        dm.start.assert_not_awaited()
        notification.notify_user.assert_awaited_once()

    async def test_billing_personal_endpoint_down_notifies_user(self):
        user, dm, billing, notification = _buy_args(None)

        await _buy(dm, billing, notification)

        billing.create_payment.assert_not_awaited()
        notification.notify_user.assert_awaited_once()


class TestDeepLinkToPurchase:
    async def test_proxy_deep_link_opens_screen_with_buy_button_then_buy_reaches_payment(self):
        message, user, dm, i18n, channel, notification = _setup("/start proxy")
        await unwrap_inject(on_start_command)(message, user, dm, i18n, channel, notification)
        assert dm.start.await_args.args[0] == MainMenu.TG_PROXY

        result, _ = await _render(personal=_not_entitled(), user=user)
        assert result["can_buy_proxy"] is True

        _, buy_dm, billing, buy_notification = _buy_args(_not_entitled())
        await _buy(buy_dm, billing, buy_notification)
        assert buy_dm.start.await_args.args[0] == Subscription.PROXY_CONFIRM
        assert buy_dm.start.await_args.kwargs["data"]["payment_url"] == PAY_URL


class TestConfirmAndSuccess:
    async def test_confirm_getter_exposes_payment_data(self):
        dm = make_dialog_manager()
        dm.start_data = {"payment_url": PAY_URL, "price": 25, "original_price": 49}

        assert await proxy_confirm_getter(dm) == {
            "url": PAY_URL,
            "price": 25,
            "original_price": 49,
        }

    async def test_success_message_lists_personal_links(self):
        billing = make_billing_client(personal=_entitled("proxy_plan", EXPIRES))

        result = await unwrap_inject(proxy_success_getter)(
            dialog_manager=make_dialog_manager(), user=make_user(), billing=billing
        )
        msg = result["proxy_message"]

        assert msg.startswith("<b>✅ Оплата прошла успешно!</b>")
        assert "Личный прокси действует до 12.11.2026." in msg
        assert "до 3 устройств одновременно" in msg
        assert PERSONAL_PHONE in msg and PERSONAL_WEB in msg

    async def test_success_waits_until_entitlement_is_visible(self):
        billing = make_billing_client(personal=_not_entitled())
        billing.get_personal_tg_proxies.side_effect = [
            _not_entitled(),
            _not_entitled(),
            _entitled("proxy_plan", EXPIRES),
        ]

        with patch.object(proxy_view.asyncio, "sleep", new=AsyncMock()):
            result = await unwrap_inject(proxy_success_getter)(
                dialog_manager=make_dialog_manager(), user=make_user(), billing=billing
            )

        assert billing.get_personal_tg_proxies.await_count == 3
        assert PERSONAL_WEB in result["proxy_message"]

    async def test_success_message_when_entitlement_never_appears(self):
        billing = make_billing_client(personal=_not_entitled())

        with patch.object(proxy_view.asyncio, "sleep", new=AsyncMock()):
            result = await unwrap_inject(proxy_success_getter)(
                dialog_manager=make_dialog_manager(), user=make_user(), billing=billing
            )

        assert "Оплата прошла успешно" in result["proxy_message"]
        assert "через минуту" in result["proxy_message"]


def _consumer() -> UserNotificationConsumer:
    config = MagicMock()
    config.kafka_brokers = "localhost:9092"
    config.kafka_notify_topic = "prod.compono.notify.user.v1"
    config.kafka_group_id = f"test-{uuid4()}"
    return UserNotificationConsumer(config, MagicMock())


class TestRedirect:
    async def test_proxy_success_starts_proxy_success_state(self):
        consumer = _consumer()
        consumer._start_redirect = AsyncMock()  # type: ignore[method-assign]

        await consumer._handle_redirect(123, {"redirect_to": "proxy_success"})

        consumer._start_redirect.assert_awaited_once_with(123, Subscription.PROXY_SUCCESS, {})

    async def test_subscription_success_still_starts_subscription_success(self):
        consumer = _consumer()
        consumer._start_redirect = AsyncMock()  # type: ignore[method-assign]

        await consumer._handle_redirect(
            123, {"redirect_to": "subscription_success", "purchase_type": "RENEW"}
        )

        state, data = consumer._start_redirect.await_args.args[1:]
        assert state == Subscription.SUCCESS
        assert data["purchase_type"].value == "RENEW"

    async def test_unknown_redirect_is_ignored(self):
        consumer = _consumer()
        consumer._start_redirect = AsyncMock()  # type: ignore[method-assign]

        await consumer._handle_redirect(123, {"redirect_to": "nope"})

        consumer._start_redirect.assert_not_awaited()


class TestBillingClientPersonal:
    async def test_get_personal_tg_proxies_calls_billing_with_contract_shape(self):
        client = BillingClient("http://api", "s", direct_base_url="http://billing")
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "entitled": True,
            "source": "proxy_plan",
            "expires_at": "2026-11-12T09:00:00Z",
            "proxy_plan_id": 9,
            "price_rub": 25,
            "proxies": [
                {
                    "id": 1,
                    "server": "s",
                    "port": 443,
                    "secret": "x",
                    "kind": "MTPROTO",
                    "link": "tg://proxy",
                    "is_public": False,
                }
            ],
        }
        http = AsyncMock(spec=httpx.AsyncClient)
        http.is_closed = False
        http.request.return_value = resp
        client._direct_client = http

        result = await client.get_personal_tg_proxies(42)

        assert http.request.call_args[0] == (
            "GET",
            "http://billing/api/v1/internal/tg-proxies/personal/42",
        )
        assert result.entitled is True
        assert result.source == "proxy_plan"
        assert result.expires_at == EXPIRES
        assert result.proxy_plan_id == 9
        assert result.price_rub == 25
        assert result.proxies[0].is_public is False

    async def test_null_expiry_and_source_for_free_users(self):
        data = BillingPersonalProxies.model_validate(
            {
                "entitled": False,
                "source": None,
                "expires_at": None,
                "proxy_plan_id": 9,
                "price_rub": 25,
                "proxies": [],
            }
        )
        assert data.expires_at is None and data.source is None
