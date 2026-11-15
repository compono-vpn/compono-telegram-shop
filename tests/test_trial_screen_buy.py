"""The trial-granted screen has a buy button that starts the same purchase flow."""

from __future__ import annotations

from pathlib import Path

from fluentogram import TranslatorHub
from fluentogram.storage import FileStorage

from src.bot.routers.subscription.dialog import success_trial
from src.bot.routers.subscription.handlers import on_subscription_plans
from src.core.constants import PURCHASE_PREFIX
from src.core.enums import PurchaseType


def test_buy_button_runs_the_new_purchase_flow():
    button = success_trial.find(f"{PURCHASE_PREFIX}{PurchaseType.NEW}")

    assert button is not None
    assert button.on_click.callback is on_subscription_plans


def test_label_is_short_and_in_russian():
    hub = TranslatorHub(
        {"ru": ("ru",)},
        root_locale="ru",
        storage=FileStorage(path=Path("assets/translations") / "{locale}"),
    )

    assert hub.get_translator_by_locale("ru").get("btn-trial-buy") == "💳 Купить подписку"
