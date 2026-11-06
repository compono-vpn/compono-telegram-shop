from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram_dialog.widgets.kbd import Url
from fluentogram import TranslatorHub
from fluentogram.storage import FileStorage

from src.bot.routers.menu.dialog import menu
from src.bot.routers.menu.getters import menu_getter as _menu_getter
from src.core.constants import CONTAINER_KEY
from tests.conftest import (
    make_billing_client,
    make_config,
    make_dialog_manager,
    make_experiment_service,
    make_i18n,
    make_referral_service,
    make_subscription,
    make_user,
    unwrap_inject,
)

menu_getter = unwrap_inject(_menu_getter)

IOS_URL = "https://componovpn.com/ios?utm_source=bot&utm_medium=menu"


def _translator():
    hub = TranslatorHub(
        {"ru": ("ru",)},
        root_locale="ru",
        storage=FileStorage(path=Path("assets/translations") / "{locale}"),
    )
    return hub.get_translator_by_locale("ru")


async def _render_ios_button(user):
    manager = make_dialog_manager()
    container = MagicMock()
    container.get = AsyncMock(return_value=_translator())
    manager.middleware_data = {CONTAINER_KEY: container}
    remnawave = AsyncMock()
    remnawave.is_beta_tester.return_value = False
    data = await menu_getter(
        dialog_manager=manager,
        config=make_config(),
        user=user,
        i18n=make_i18n(),
        billing=make_billing_client(),
        referral_service=make_referral_service(),
        experiment_service=make_experiment_service(),
        remnawave_service=remnawave,
    )
    ios = next(
        w
        for row in menu.keyboard.buttons
        for w in row.buttons
        if getattr(w, "widget_id", None) == "ios_app"
    )
    assert isinstance(ios, Url)
    text = await ios.text.render_text(data, manager)
    url = await ios.url.render_text(data, manager)
    return text, url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user",
    [make_user(), make_user(subscription=make_subscription())],
    ids=["no-subscription", "active-subscription"],
)
async def test_main_menu_renders_ios_button_with_site_url(user):
    text, url = await _render_ios_button(user)

    assert text == "📱 Приложение для iPhone"
    assert url == IOS_URL
