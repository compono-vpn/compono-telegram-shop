"""Plan list and duration list: layout of the 2026-11-18 redesign, Stars and ruble modes."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fluentogram import TranslatorHub
from fluentogram.storage import FileStorage

from src.bot.plan_screen import (
    DurationRow,
    format_devices,
    format_period,
    format_traffic,
    saving_percent,
)
from src.bot.routers.subscription.getters import duration_getter as _duration_getter
from src.bot.routers.subscription.getters import plans_getter as _plans_getter
from src.infrastructure.billing import billing_plan_to_dto
from src.infrastructure.billing.models import BillingPlan, BillingPlanDuration, BillingPriceDetails
from tests.conftest import make_dialog_manager, make_user, unwrap_inject

plans_getter = unwrap_inject(_plans_getter)
duration_getter = unwrap_inject(_duration_getter)


def _plan(plan_id, name, gb, devices, days=(30,)):
    return BillingPlan(
        ID=plan_id,
        Name=name,
        Type="BOTH",
        IsActive=True,
        TrafficLimit=gb,
        DeviceLimit=devices,
        Durations=[BillingPlanDuration(ID=plan_id * 10 + i, Days=d) for i, d in enumerate(days)],
    )


def _i18n():
    hub = TranslatorHub(
        {"ru": ("ru",)},
        root_locale="ru",
        storage=FileStorage(path=Path("assets/translations") / "{locale}"),
    )
    return hub.get_translator_by_locale("ru")


def _billing(plans, prices, currency="XTR"):
    billing = AsyncMock()
    billing.get_available_plans.return_value = plans
    billing.get_default_currency.return_value = "RUB"

    async def calculate(telegram_id, plan_id, duration_days, currency_arg=None, **kwargs):
        # Stars mode prices in XTR; ruble mode in billing's default currency (RUB).
        assert kwargs.get("currency", currency_arg) == currency
        value = prices[(plan_id, duration_days)]
        if isinstance(value, Exception):
            raise value
        original, final = value
        discount = 0 if original == final else 30
        return BillingPriceDetails(
            original_amount=original, discount_percent=discount, final_amount=final
        )

    billing.calculate_price.side_effect = calculate
    return billing


async def _screen(billing):
    return await plans_getter(
        dialog_manager=make_dialog_manager(),
        user=make_user(),
        i18n=_i18n(),
        billing=billing,
    )


THREE = [_plan(1, "⚡️ Старт", 100, 2), _plan(2, "🚀 Про", 300, 6), _plan(3, "💎 Макс", 1024, 20)]


async def test_plan_list_without_discount_stars_mode():
    billing = _billing(
        THREE, {(1, 30): ("119", "119"), (2, 30): ("239", "239"), (3, 30): ("399", "399")}
    )

    data = await _screen(billing)

    assert data["plans_text"] == (
        "<b>Выберите тариф</b>\n"
        "\n"
        "⚡ <b>Старт</b> — 119 ★/мес\n"
        "100 ГБ · 2 устройства\n"
        "\n"
        "🚀 <b>Про</b> — 239 ★/мес\n"
        "300 ГБ · 6 устройств\n"
        "\n"
        "💎 <b>Макс</b> — 399 ★/мес\n"
        "1 ТБ · 20 устройств"
    )
    assert [p["label"] for p in data["plans"]] == [
        "⚡ Старт · 119 ★",
        "🚀 Про · 239 ★",
        "💎 Макс · 399 ★",
    ]


@pytest.mark.rubles
async def test_plan_list_with_discount_in_rubles():
    billing = _billing(
        THREE,
        {(1, 30): ("119", "83"), (2, 30): ("239", "167"), (3, 30): ("399", "279")},
        currency="RUB",
    )

    data = await _screen(billing)

    text = data["plans_text"]
    assert text.startswith("<b>Выберите тариф</b>\n🎁 Ваша скидка 30% уже учтена\n\n")
    assert "⚡ <b>Старт</b> — 83 ₽/мес\n100 ГБ · 2 устройства" in text
    assert "<s>" not in text
    assert [p["label"] for p in data["plans"]] == [
        "⚡ Старт · 83 ₽",
        "🚀 Про · 167 ₽",
        "💎 Макс · 279 ₽",
    ]


async def test_ultra_line_and_every_plan_button_coloured():
    ultra = _plan(38, "👑 Ультра", 1024, 20)
    ultra.Tag = "ULTRA"
    billing = _billing(THREE + [ultra], {(i, 30): ("1", "1") for i in (1, 2, 3, 38)})

    data = await _screen(billing)

    assert data["plans_text"].endswith(
        "👑 <b>Ультра</b> — 1 ★/мес\n1 ТБ · 20 устройств · личный IP (Швеция или Нидерланды)"
    )
    styles = [p["style"] for p in data["plans"]]
    # Ultra has its own colour: no plan uses the default (black) style of the navigation row.
    assert styles == ["success", "primary", "danger", "primary"]


async def test_the_month_price_is_taken_from_the_30_day_duration():
    plan = _plan(1, "⚡️ Старт", 100, 2, days=(90, 30, 365))
    billing = _billing([plan], {(1, 30): ("119", "119")})

    await _screen(billing)

    assert billing.calculate_price.await_args.kwargs["duration_days"] == 30


async def test_a_plan_without_a_30_day_duration_uses_its_shortest():
    plan = _plan(1, "⚡️ Старт", 100, 2, days=(90, 365))
    billing = _billing([plan], {(1, 90): ("299", "299")})

    data = await _screen(billing)

    assert "⚡ <b>Старт</b> — 299 ★ / 3 месяца\n" in data["plans_text"]


async def test_a_price_lookup_failure_keeps_the_plan_without_a_price():
    plans = [_plan(1, "⚡️ Старт", 100, 2), _plan(2, "🚀 Про", 300, 6)]
    billing = _billing(plans, {(1, 30): RuntimeError("billing down"), (2, 30): ("239", "239")})

    data = await _screen(billing)

    assert "⚡ <b>Старт</b>\n100 ГБ · 2 устройства" in data["plans_text"]
    assert [p["label"] for p in data["plans"]] == ["⚡ Старт", "🚀 Про · 239 ★"]


def test_traffic_formatting():
    assert format_traffic(100) == "100 ГБ"
    assert format_traffic(1024) == "1 ТБ"
    assert format_traffic(2048) == "2 ТБ"
    assert format_traffic(1536) == "1.5 ТБ"
    assert format_traffic(-1) == "безлимитный трафик"


def test_plural_forms():
    assert [format_devices(n) for n in (1, 2, 5, 11, 21, 22)] == [
        "1 устройство",
        "2 устройства",
        "5 устройств",
        "11 устройств",
        "21 устройство",
        "22 устройства",
    ]
    assert [format_period(d) for d in (30, 90, 180, 365)] == [
        "1 месяц",
        "3 месяца",
        "6 месяцев",
        "1 год",
    ]


def test_duration_button_shows_saving():
    assert saving_percent(90, Decimal("299"), Decimal("119")) == 16
    assert saving_percent(30, Decimal("119"), Decimal("119")) == 0
    assert DurationRow(90, Decimal("299"), "RUB", 16).button() == "3 месяца — 299 ₽ (−16%)"
    assert DurationRow(30, Decimal("119"), "XTR").button() == "1 месяц — 119 ★"


@pytest.mark.rubles
async def test_duration_screen_in_rubles_with_discount():
    plan = billing_plan_to_dto(_plan(1, "⚡️ Старт", 100, 2, days=(30, 90, 365)))
    dm = make_dialog_manager()
    dm.dialog_data["plandto"] = plan.model_dump()
    prices = {
        (1, 30): ("119", "83"),
        (1, 90): ("299", "299"),
        (1, 365): ("999", "999"),
    }
    billing = _billing([], prices, currency="RUB")
    incentive = AsyncMock()
    incentive.discount_context.return_value = None

    data = await duration_getter(dm, make_user(), _i18n(), billing, None, incentive)

    assert data["duration_text"] == (
        "<b>Выберите срок</b>\n🎁 Ваша скидка 30% уже учтена\n\n⚡ <b>Старт</b>\n100 ГБ · 2 устройства"
    )
    assert [d["label"] for d in data["durations"]] == [
        "1 месяц — 83 ₽",
        "3 месяца — 299 ₽ (−16%)",
        "1 год — 999 ₽ (−30%)",
    ]
    assert data["style"] == "success"
