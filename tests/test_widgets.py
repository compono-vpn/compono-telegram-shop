"""Message widgets (Bot API 10.4): connect card, subscription status card, plan picker."""

import json
import zlib
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from remnapy.enums import TrafficLimitStrategy

from src.core.enums import Currency, PlanAvailability, PlanType, PurchaseType
from src.models.dto.plan import PlanDto, PlanDurationDto, PlanPriceDto
from src.services import widgets
from src.services.widgets import (
    AnswerWidgetQuery,
    EditMessageWidgetData,
    SendWidget,
    WidgetService,
    parse_widget_query,
    plans_state,
    purchase_type,
    status_state,
)
from tests.conftest import make_subscription, make_user

FORBIDDEN = ("<input", "fetch(", "XMLHttpRequest", "@font-face", "vh;", "<iframe", "https://cdn")


def plan(pid, name, prices, *, ptype=PlanType.BOTH, availability=PlanAvailability.ALL, order=0):
    return PlanDto(
        id=pid,
        name=name,
        type=ptype,
        availability=availability,
        order_index=order,
        is_active=True,
        traffic_limit=300,
        device_limit=6,
        traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
        internal_squads=[],
        durations=[
            PlanDurationDto(days=d, prices=[PlanPriceDto(currency=Currency.RUB, price=Decimal(p))])
            for d, p in prices
        ],
    )


CATALOGUE = [
    plan(2, "🚀 Про", [(30, 239), (365, 1990)], order=2),
    plan(1, "⚡️ Старт", [(30, 119), (90, 299), (180, 549), (365, 999)], order=1),
    plan(3, "💎 Макс", [(30, 399), (90, 999), (180, 1799), (365, 2990)], order=3),
    plan(4, "🎁 Пробный период", [(2, 0)], availability=PlanAvailability.TRIAL, order=4),
    plan(5, "Прокси", [(30, 49)], ptype=PlanType.PROXY, order=5),
]


@pytest.mark.parametrize("html", [widgets.CONNECT_HTML, widgets.STATUS_HTML, widgets.PLANS_HTML])
def test_every_card_fits_telegrams_limits_and_profile(html):
    raw = html.encode()
    assert len(raw) <= 32768
    assert len(zlib.compress(raw, 9)) <= 4096
    for token in FORBIDDEN:
        assert token not in html


def test_widget_query_is_parsed_from_the_raw_update():
    q = parse_widget_query(
        {
            "id": "q1",
            "from": {"id": 7, "is_bot": False},
            "chat": {"id": 7},
            "message_id": 9,
            "data": "chk",
        }
    )
    assert (q.id, q.user_id, q.chat_id, q.message_id, q.data) == ("q1", 7, 7, 9, "chk")
    assert parse_widget_query({"from": {"id": 7}}) is None
    assert parse_widget_query("junk") is None


def test_plan_card_lists_sellable_plans_in_order_with_labels():
    state = plans_state(CATALOGUE, selected=2)
    assert [p["n"] for p in state["p"]] == ["⚡️ Старт", "🚀 Про", "💎 Макс"]
    assert state["p"][0]["d"][0] == [30, 119, "1 месяц"]
    assert state["p"][0]["d"][-1] == [365, 999, "1 год"]
    assert state["s"] == 2
    assert len(widgets.pack(state).encode()) <= 1024


def test_purchase_type_follows_the_current_subscription():
    assert purchase_type(None, 1) == PurchaseType.NEW
    assert purchase_type(make_subscription(is_trial=True), 1) == PurchaseType.NEW
    assert purchase_type(make_subscription(active=False), 2) == PurchaseType.NEW
    assert purchase_type(make_subscription(plan_id=2), 2) == PurchaseType.RENEW
    assert purchase_type(make_subscription(plan_id=2), 3) == PurchaseType.CHANGE


def test_status_card_shows_days_left_and_traffic():
    sub = make_subscription(traffic_limit=300)
    state = status_state(
        sub, used_bytes=12 * 1024**3, now=sub.expire_at - timedelta(days=23, hours=2)
    )
    assert state["n"] == "🚀 Про"
    assert state["d"] == 24
    assert (state["u"], state["l"]) == (12.0, 300)
    assert "e" in state


def gw(kind, currency, *, order=0, channel="BOT", active=True):
    return SimpleNamespace(
        Type=kind, Currency=currency, OrderIndex=order, Channel=channel, IsActive=active
    )


def test_card_payments_prefer_platega_and_fall_back_to_any_ruble_gateway():
    assert (
        widgets.pick_gateway(
            [gw("YOOKASSA", "RUB", order=1), gw("PLATEGA", "RUB", order=2)], False
        ).Type
        == "PLATEGA"
    )
    assert (
        widgets.pick_gateway([gw("TELEGRAM_STARS", "XTR"), gw("YOOKASSA", "RUB")], False).Type
        == "YOOKASSA"
    )
    assert widgets.pick_gateway([gw("PLATEGA", "RUB", active=False)], False) is None
    assert widgets.pick_gateway([gw("TELEGRAM_STARS", "XTR")], True).Type == "TELEGRAM_STARS"


def service(user=None, subscription=None, *, connected=False):
    bot = AsyncMock()
    billing = AsyncMock()
    billing.list_active_gateways.return_value = [
        gw("TELEGRAM_STARS", "XTR"),
        gw("YOOKASSA", "RUB", order=1),
        gw("PLATEGA", "RUB", order=2),
        gw("PLATEGA", "RUB", channel="WEB"),
    ]
    billing.create_payment.return_value = SimpleNamespace(
        ID="1b4e28ba-2fa1-11d2-883f-0016d3cca427", URL="https://pay.example/abc"
    )
    users = SimpleNamespace(get=AsyncMock(return_value=user or make_user()))
    subs = SimpleNamespace(get_current=AsyncMock(return_value=subscription))
    remna = AsyncMock()
    remna.get_devices_user.return_value = [object()] if connected else []
    remna.get_user.return_value = SimpleNamespace(sub_last_opened_at=None, user_traffic=None)
    config = SimpleNamespace(widgets_enabled=True, website_url="https://componovpn.com")
    hub = MagicMock()
    hub.get_translator_by_locale.return_value.get.return_value = "caption"
    svc = WidgetService(config, bot, AsyncMock(), hub, billing, users, subs, remna, MagicMock())
    svc._plans = AsyncMock(return_value=CATALOGUE)
    return svc, bot, billing


def sent(bot, kind):
    return [c.args[0] for c in bot.await_args_list if isinstance(c.args[0], kind)]


def answer_of(bot):
    (a,) = sent(bot, AnswerWidgetQuery)
    return json.loads(a.data)


def query(data, **extra):
    return {
        "id": "q1",
        "from": {"id": 1750352084},
        "chat": {"id": 1750352084},
        "message_id": 55,
        "data": data,
        **extra,
    }


async def test_pay_creates_a_platega_payment_and_answers_its_link(monkeypatch):
    monkeypatch.setattr(widgets, "schedule_cancel_survey_check", AsyncMock())
    monkeypatch.setattr(
        widgets,
        "billing_price_details_to_dto",
        lambda _: SimpleNamespace(final_amount=Decimal(119)),
    )
    svc, bot, billing = service(subscription=None)
    await svc.handle_query(query("pay:1:30"))
    kwargs = billing.create_payment.await_args.kwargs
    assert (
        kwargs["plan_id"],
        kwargs["duration_days"],
        kwargs["gateway_type"],
        kwargs["purchase_type"],
    ) == (1, 30, "PLATEGA", "NEW")
    assert answer_of(bot) == {"u": "https://pay.example/abc", "a": "119 ₽"}


async def test_star_payment_answers_a_telegram_invoice_link(monkeypatch):
    monkeypatch.setattr(widgets, "schedule_cancel_survey_check", AsyncMock())
    monkeypatch.setattr(
        widgets,
        "billing_price_details_to_dto",
        lambda _: SimpleNamespace(final_amount=Decimal(239)),
    )
    monkeypatch.setattr(
        widgets, "create_stars_invoice_link", AsyncMock(return_value="https://t.me/$inv")
    )
    svc, bot, billing = service(subscription=make_subscription(plan_id=2))
    billing.create_payment.return_value = SimpleNamespace(
        ID="1b4e28ba-2fa1-11d2-883f-0016d3cca427", URL=""
    )
    await svc.handle_query(query("star:2:30"))
    assert billing.create_payment.await_args.kwargs["purchase_type"] == "RENEW"
    assert answer_of(bot) == {"t": "https://t.me/$inv", "a": "239 ⭐"}


async def test_unknown_plan_or_bad_data_is_refused_without_a_payment():
    svc, bot, billing = service()
    await svc.handle_query(query("pay:5:30"))
    billing.create_payment.assert_not_awaited()
    assert "недоступен" in answer_of(bot)["m"]


async def test_connect_check_marks_the_card_connected():
    svc, bot, _ = service(subscription=make_subscription(), connected=True)
    await svc.handle_query(query("chk"))
    assert answer_of(bot) == {"c": 1}
    (edit,) = sent(bot, EditMessageWidgetData)
    assert (edit.chat_id, edit.message_id, json.loads(edit.chat_data)["c"]) == (1750352084, 55, 1)


async def test_a_failure_still_answers_the_widget():
    svc, bot, _ = service()
    svc.subscription_service.get_current.side_effect = RuntimeError("billing down")
    await svc.handle_query(query("st"))
    assert "Попробуйте" in answer_of(bot)["m"]


async def test_cards_are_sent_with_queries_allowed_and_a_caption():
    sub = make_subscription()
    svc, bot, _ = service(subscription=sub)
    await svc.send_subscription(make_user(subscription=sub))
    (msg,) = sent(bot, SendWidget)
    assert msg.html == widgets.STATUS_HTML and msg.allow_queries and msg.caption == "caption"
    assert json.loads(msg.chat_data)["n"] == "🚀 Про"


async def test_a_user_without_paid_subscription_gets_the_plan_card():
    svc, bot, _ = service(subscription=make_subscription(is_trial=True))
    await svc.send_subscription(make_user())
    (msg,) = sent(bot, SendWidget)
    assert msg.html == widgets.PLANS_HTML


async def test_webhook_answers_widget_queries_without_the_dispatcher():
    from aiogram.types import Update

    from src.api.endpoints.telegram import TelegramWebhookEndpoint

    dispatcher = MagicMock()
    dispatcher.feed_update = AsyncMock()
    endpoint = TelegramWebhookEndpoint(dispatcher=dispatcher, secret_token="s")
    update = Update.model_validate({"update_id": 1, "widget_query": query("chk")})
    widget_service = AsyncMock()
    handler = (
        TelegramWebhookEndpoint._handle_request.__dishka_orig_func__
        if hasattr(TelegramWebhookEndpoint._handle_request, "__dishka_orig_func__")
        else TelegramWebhookEndpoint._handle_request.__wrapped__
    )
    response = await handler(
        endpoint,
        update=update,
        x_telegram_bot_api_secret_token="s",
        bot=AsyncMock(),
        widget_service=widget_service,
    )
    assert response.status_code == 200
    widget_service.handle_query.assert_awaited_once()
    dispatcher.feed_update.assert_not_awaited()
