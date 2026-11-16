"""The plan screen shows what a month costs, discounts included."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from fluentogram import TranslatorHub
from fluentogram.storage import FileStorage

from src.bot.routers.subscription.getters import plans_getter as _plans_getter
from src.infrastructure.billing.models import BillingPlan, BillingPlanDuration, BillingPriceDetails
from tests.conftest import make_dialog_manager, make_user, unwrap_inject

plans_getter = unwrap_inject(_plans_getter)


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


def _billing(plans, prices):
    billing = AsyncMock()
    billing.get_available_plans.return_value = plans
    billing.get_default_currency.return_value = "RUB"

    async def calculate(telegram_id, plan_id, duration_days, currency, **kwargs):
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


async def _summary(billing):
    data = await plans_getter(
        dialog_manager=make_dialog_manager(),
        user=make_user(),
        i18n=_i18n(),
        billing=billing,
    )
    return data["summary"].split("\n")


async def test_every_plan_line_has_a_monthly_price():
    plans = [_plan(1, "⚡️ Старт", 100, 2), _plan(2, "🚀 Про", 300, 6)]
    billing = _billing(plans, {(1, 30): ("119", "119"), (2, 30): ("239", "239")})

    lines = await _summary(billing)

    assert lines[0] == "⚡️ Старт — 119 ₽/мес · 100 ГБ, 2 устройства"
    assert lines[1] == "🚀 Про — 239 ₽/мес · 300 ГБ, 6 устройств"


async def test_a_personal_discount_shows_the_old_price_struck_through():
    billing = _billing([_plan(1, "⚡️ Старт", 100, 2)], {(1, 30): ("119", "83")})

    lines = await _summary(billing)

    assert lines == ["⚡️ Старт — <s>119 ₽</s> 83 ₽/мес · 100 ГБ, 2 устройства"]


async def test_the_month_price_is_taken_from_the_30_day_duration():
    plan = _plan(1, "⚡️ Старт", 100, 2, days=(90, 30, 365))
    billing = _billing([plan], {(1, 30): ("119", "119")})

    await _summary(billing)

    assert billing.calculate_price.await_args.kwargs["duration_days"] == 30


async def test_a_plan_without_a_30_day_duration_uses_its_shortest():
    plan = _plan(1, "⚡️ Старт", 100, 2, days=(90, 365))
    billing = _billing([plan], {(1, 90): ("299", "299")})

    lines = await _summary(billing)

    assert lines == ["⚡️ Старт — 299 ₽ / 90 дн. · 100 ГБ, 2 устройства"]


async def test_a_price_lookup_failure_keeps_the_line_without_a_price():
    plans = [_plan(1, "⚡️ Старт", 100, 2), _plan(2, "🚀 Про", 300, 6)]
    billing = _billing(plans, {(1, 30): RuntimeError("billing down"), (2, 30): ("239", "239")})

    lines = await _summary(billing)

    assert lines[0] == "⚡️ Старт — 100 ГБ, 2 устройства"
    assert lines[1] == "🚀 Про — 239 ₽/мес · 300 ГБ, 6 устройств"


async def test_buttons_still_list_the_plans():
    plans = [_plan(1, "⚡️ Старт", 100, 2)]
    billing = _billing(plans, {(1, 30): ("119", "119")})

    data = await plans_getter(
        dialog_manager=make_dialog_manager(), user=make_user(), i18n=_i18n(), billing=billing
    )

    assert data["plans"] == [{"id": 1, "name": "⚡️ Старт"}]


async def test_ultra_line_names_the_dedicated_ip():
    ultra = _plan(38, "👑 Ультра", 1024, 20)
    ultra.Tag = "ULTRA"
    billing = _billing(
        [_plan(3, "💎 Макс", 1024, 20), ultra], {(3, 30): ("399", "399"), (38, 30): ("799", "799")}
    )

    lines = [line.replace("\u00a0", " ").replace("\u202f", " ") for line in await _summary(billing)]

    assert lines[0] == "💎 Макс — 399 ₽/мес · 1 024 ГБ, 20 устройств"
    assert (
        lines[1]
        == "👑 Ультра — 799 ₽/мес · 1 024 ГБ, 20 устройств, 🌐 личный IP (Швеция или Нидерланды)"
    )
