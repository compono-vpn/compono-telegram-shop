"""The first screen states the trial terms and the cheapest price before the user taps."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from fluentogram import TranslatorHub
from fluentogram.storage import FileStorage

from src.bot.routers.menu.getters import menu_getter as _menu_getter
from src.infrastructure.billing.models import (
    BillingPlan,
    BillingPlanDuration,
    BillingPlanPrice,
)
from src.services.first_screen import first_screen_terms
from tests.conftest import (
    make_billing_client,
    make_config,
    make_dialog_manager,
    make_experiment_service,
    make_referral_service,
    make_user,
    unwrap_inject,
)

menu_getter = unwrap_inject(_menu_getter)


def _i18n():
    hub = TranslatorHub(
        {"ru": ("ru",)},
        root_locale="ru",
        storage=FileStorage(path=Path("assets/translations") / "{locale}"),
    )
    return hub.get_translator_by_locale("ru")


def _trial(days=2, gb=5, devices=1):
    return BillingPlan(
        ID=4,
        Name="Пробный",
        Type="BOTH",
        Availability="TRIAL",
        IsActive=True,
        TrafficLimit=gb,
        DeviceLimit=devices,
        Durations=[BillingPlanDuration(ID=40, Days=days)],
    )


def _paid(plan_id, price, *, kind="BOTH", availability="ALL", days=30, currency="RUB"):
    return BillingPlan(
        ID=plan_id,
        Name=f"p{plan_id}",
        Type=kind,
        Availability=availability,
        IsActive=True,
        Durations=[
            BillingPlanDuration(
                ID=plan_id * 10,
                Days=days,
                Prices=[
                    BillingPlanPrice(Currency=currency, Price=price),
                    BillingPlanPrice(Currency="USD", Price="1.49"),
                ],
            )
        ],
    )


def _billing(plans):
    billing = AsyncMock()
    billing.get_available_plans.return_value = plans
    billing.get_default_currency.return_value = "RUB"
    return billing


async def test_terms_name_days_traffic_and_devices():
    billing = _billing([_paid(1, "119.00"), _paid(2, "239.00")])

    terms = await first_screen_terms(billing, _i18n(), _trial(), 1)

    assert terms == {"trial_terms": "2 дня, 5 ГБ, 1 устройство", "price_from": "119 ₽/мес"}


async def test_the_cheapest_sellable_month_price_wins():
    plans = [
        _paid(1, "239.00"),
        _paid(2, "399.00"),
        _paid(5, "49.00", kind="PROXY"),
        _paid(6, "10.00", availability="TRIAL"),
        _paid(7, "5.00", days=7),
        _paid(8, "149.00", currency="USDT"),
    ]

    terms = await first_screen_terms(_billing(plans), _i18n(), _trial(), 1)

    assert terms["price_from"] == "239 ₽/мес"


async def test_without_a_trial_plan_there_are_no_terms():
    terms = await first_screen_terms(_billing([_paid(1, "119.00")]), _i18n(), None, 1)

    assert terms == {"trial_terms": False, "price_from": False}


async def test_missing_prices_keep_the_terms_only():
    terms = await first_screen_terms(_billing([]), _i18n(), _trial(), 1)

    assert terms == {"trial_terms": "2 дня, 5 ГБ, 1 устройство", "price_from": False}


async def test_a_billing_failure_never_breaks_the_screen():
    billing = AsyncMock()
    billing.get_available_plans.side_effect = RuntimeError("down")
    billing.get_default_currency.return_value = "RUB"

    terms = await first_screen_terms(billing, _i18n(), _trial(), 1)

    assert terms == {"trial_terms": "2 дня, 5 ГБ, 1 устройство", "price_from": False}


async def test_menu_getter_passes_the_terms_to_a_new_user():
    billing = make_billing_client(trial_plan=_trial(), has_used_trial=False)
    billing.get_available_plans.return_value = [_paid(1, "119.00")]
    billing.get_default_currency.return_value = "RUB"
    remnawave = AsyncMock()
    remnawave.is_beta_tester.return_value = False

    data = await menu_getter(
        dialog_manager=make_dialog_manager(),
        config=make_config(),
        user=make_user(),
        i18n=_i18n(),
        billing=billing,
        referral_service=make_referral_service(),
        experiment_service=make_experiment_service(),
        remnawave_service=remnawave,
    )

    assert data["trial_available"] is True
    assert data["trial_terms"] == "2 дня, 5 ГБ, 1 устройство"
    assert data["price_from"] == "119 ₽/мес"


async def test_menu_getter_skips_the_lookups_for_a_user_who_cannot_take_the_trial():
    billing = make_billing_client(trial_plan=_trial(), has_used_trial=True)
    remnawave = AsyncMock()
    remnawave.is_beta_tester.return_value = False

    data = await menu_getter(
        dialog_manager=make_dialog_manager(),
        config=make_config(),
        user=make_user(),
        i18n=_i18n(),
        billing=billing,
        referral_service=make_referral_service(),
        experiment_service=make_experiment_service(),
        remnawave_service=remnawave,
    )

    assert data["trial_available"] is False
    assert data["trial_terms"] is False
    billing.get_available_plans.assert_not_awaited()


class TestMenuCopy:
    def _text(self, **kwargs):
        i18n = _i18n()
        return i18n.get(
            "msg-main-menu",
            user_id="1",
            user_name="Анна",
            personal_discount=0,
            loyalty_discount=0,
            is_beta_tester=0,
            status="NONE",
            is_trial=0,
            trial_available=1,
            **kwargs,
        )

    def test_the_new_user_text_carries_terms_and_price(self):
        text = self._text(trial_terms="2 дня, 5 ГБ, 1 устройство", price_from="119 ₽/мес")

        assert "2 дня, 5 ГБ, 1 устройство" in text
        assert "от 119 ₽/мес" in text

    def test_without_terms_the_old_sentence_stays(self):
        text = self._text(trial_terms=False, price_from=False)

        assert "бесплатный пробник" in text
        assert "от " not in text.split("пробник")[1]

    def test_terms_without_a_price_do_not_print_a_broken_price(self):
        text = self._text(trial_terms="2 дня, 5 ГБ, 1 устройство", price_from=False)

        assert "2 дня, 5 ГБ, 1 устройство" in text
        assert "от " not in text.split("2 дня, 5 ГБ, 1 устройство")[1]
