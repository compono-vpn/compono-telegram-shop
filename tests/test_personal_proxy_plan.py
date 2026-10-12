from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

from src.bot.routers.dashboard.statistics.getters import statistics_getter
from src.bot.routers.dashboard.users.user.getters import (
    give_access_getter,
    give_subscription_getter,
)
from src.bot.routers.menu.getters import tg_proxy_getter
from src.bot.routers.menu.handlers import on_start_command
from src.bot.routers.subscription.getters import (
    plans_getter,
    proxy_confirm_getter,
)
from src.bot.routers.subscription.handlers import on_buy_proxy
from src.bot.states import MainMenu, Subscription
from src.core.constants import USER_KEY
from src.core.enums import PlanType
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.client import BillingClientError
from src.infrastructure.billing.converters import (
    billing_plan_to_dto,
    billing_subscription_to_dto,
    billing_transaction_to_dto,
)
from src.infrastructure.billing.models import (
    BillingPersonalProxies,
    BillingPlan,
    BillingSubscription,
    BillingTGProxy,
    BillingTransaction,
)
from src.infrastructure.kafka.consumer import UserNotificationConsumer
from tests.conftest import (
    make_billing_client,
    make_dialog_manager,
    make_subscription,
    make_user,
    unwrap_inject,
)
from tests.test_menu_getter import _call_menu_getter
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
        _row(-1, "MTPROTO", "me.compono.online", PERSONAL_PHONE, False),
        _row(-2, "WEB", "me.compono.online", PERSONAL_WEB, False),
        *_public_rows(),
    ]


def _shared_rows():
    return [
        _row(9, "MTPROTO", "phone.compono.online", PERSONAL_PHONE, False),
        _row(10, "WEB", "stable.compono.online", PERSONAL_WEB, False),
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
            "price": "25",
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


class TestVpnSubscriberGuard:
    def _vpn_user(self):
        return make_user(subscription=make_subscription(plan_id=2))

    async def test_no_buy_button_even_if_billing_says_not_entitled(self):
        result, _ = await _render(personal=_not_entitled(), user=self._vpn_user())
        assert result["can_buy_proxy"] is False
        assert "<s>" not in result["proxy_message"]

    async def test_trial_user_can_still_buy(self):
        user = make_user(subscription=make_subscription(is_trial=True))
        result, _ = await _render(personal=_not_entitled(), user=user)
        assert result["can_buy_proxy"] is True

    async def test_buy_click_by_vpn_subscriber_does_not_create_payment(self):
        user, dm, billing, notification = _buy_args(_not_entitled())
        dm.middleware_data[USER_KEY] = self._vpn_user()

        await _buy(dm, billing, notification)

        billing.create_payment.assert_not_awaited()

    @pytest.mark.parametrize("status", [400, 422])
    async def test_billing_validation_error_gets_clear_message(self, status):
        _, dm, billing, notification = _buy_args(_not_entitled())
        billing.create_payment.side_effect = BillingClientError(status, "already has VPN")

        await _buy(dm, billing, notification)

        dm.start.assert_not_awaited()
        payload = notification.notify_user.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-proxy-already-included"

    async def test_billing_server_error_gets_generic_message(self):
        _, dm, billing, notification = _buy_args(_not_entitled())
        billing.create_payment.side_effect = BillingClientError(500, "boom")

        await _buy(dm, billing, notification)

        payload = notification.notify_user.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-subscription-payment-creation-failed"


class TestMainMenuButton:
    async def _available(self, **kwargs):
        billing = make_billing_client(**kwargs)
        return (await _call_menu_getter(billing=billing))["tg_proxy_available"]

    async def test_shown_when_entitled_even_without_public_rows(self):
        personal = _entitled("vpn_plan", proxies=[])
        assert await self._available(personal=personal) is True

    async def test_shown_when_not_entitled_but_public_rows_exist(self):
        assert await self._available(personal=_not_entitled()) is True

    async def test_hidden_when_nothing_to_show(self):
        assert await self._available(personal=_not_entitled(proxies=[])) is False

    async def test_falls_back_to_public_rows_when_personal_endpoint_fails(self):
        assert await self._available(tg_proxies=_public_rows()) is True


def _plan_payload(type_):
    return {
        "ID": 5,
        "OrderIndex": 9,
        "IsActive": True,
        "Type": type_,
        "Availability": "ALL",
        "Name": "Прокси",
        "TrafficLimit": 0,
        "DeviceLimit": 0,
        "Durations": [
            {"ID": 1, "Days": 30, "Prices": [{"ID": 1, "Currency": "RUB", "Price": "25"}]}
        ],
    }


def _snapshot_payload(type_):
    return {
        "id": 5,
        "name": "Прокси",
        "type": type_,
        "traffic_limit": 0,
        "device_limit": 0,
        "duration": 30,
    }


class TestProxyPlanTypeParsing:
    def test_plan_type_enum_knows_proxy(self):
        assert PlanType("PROXY") is PlanType.PROXY

    def test_plan_list_with_proxy_plan_converts(self):
        plans = [BillingPlan.model_validate(_plan_payload(t)) for t in ("BOTH", "PROXY")]
        dtos = [billing_plan_to_dto(p) for p in plans]

        assert dtos[1].type == PlanType.PROXY
        assert dtos[1].get_duration(30) is not None

    def test_transaction_and_subscription_snapshots_with_proxy_convert(self):
        txn = BillingTransaction.model_validate(
            {"ID": 1, "Status": "COMPLETED", "Plan": _snapshot_payload("PROXY")}
        )
        sub = BillingSubscription.model_validate(
            {"ID": 1, "ExpireAt": "2026-12-01T00:00:00Z", "Plan": _snapshot_payload("PROXY")}
        )

        assert billing_transaction_to_dto(txn).plan.type == PlanType.PROXY
        assert billing_subscription_to_dto(sub).plan.type == PlanType.PROXY

    async def test_statistics_plans_page_with_proxy_plan(self):
        billing = AsyncMock()
        billing.list_plans.return_value = [
            BillingPlan.model_validate(_plan_payload(t)) for t in ("BOTH", "PROXY")
        ]
        widget = MagicMock()
        widget.get_page = AsyncMock(return_value=3)
        dm = make_dialog_manager()
        dm.find = MagicMock(return_value=widget)
        i18n = MagicMock()
        i18n.get.side_effect = lambda key, **kw: kw["plans"]

        result = await unwrap_inject(statistics_getter)(
            dialog_manager=dm, i18n=i18n, billing=billing
        )

        assert "Прокси: active" in result["statistics"]

    async def test_admin_plan_pickers_with_proxy_plan(self):
        plans = [BillingPlan.model_validate(_plan_payload(t)) for t in ("BOTH", "PROXY")]
        billing = AsyncMock()
        billing.get_allowed_plans.return_value = plans
        billing.get_available_plans.return_value = plans
        user_service = AsyncMock()
        user_service.get.return_value = make_user()
        dm = make_dialog_manager()
        dm.dialog_data["target_telegram_id"] = 1

        access = await unwrap_inject(give_access_getter)(
            dialog_manager=dm, user_service=user_service, billing=billing
        )
        grant = await unwrap_inject(give_subscription_getter)(
            dialog_manager=dm, user_service=user_service, billing=billing
        )

        assert len(access["plans"]) == 2 and len(grant["plans"]) == 2

    async def test_user_plan_list_getter_with_proxy_plan(self):
        billing = AsyncMock()
        billing.get_available_plans.return_value = [
            BillingPlan.model_validate(_plan_payload(t)) for t in ("BOTH", "PROXY")
        ]
        i18n = MagicMock()
        i18n.get.side_effect = lambda key, **kw: key

        result = await unwrap_inject(plans_getter)(
            dialog_manager=make_dialog_manager(), user=make_user(), i18n=i18n, billing=billing
        )

        assert len(result["plans"]) == 2
