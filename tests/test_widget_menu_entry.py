"""Menu buttons send the widget cards only when widgets are enabled, and fall back to the old screens."""

from unittest.mock import AsyncMock, MagicMock

from src.bot.routers.menu.handlers import on_connect_open, on_subscription_open
from src.bot.states import MainMenu, Subscription
from src.core.constants import USER_KEY
from tests.conftest import make_dialog_manager, make_subscription, make_user, unwrap_inject


def _dm(user):
    dm = make_dialog_manager()
    dm.middleware_data[USER_KEY] = user
    dm.switch_to = AsyncMock()
    dm.start = AsyncMock()
    return dm


def _widgets(enabled, fail=False):
    svc = MagicMock()
    svc.enabled = enabled
    svc.send_connect = AsyncMock(side_effect=RuntimeError("telegram") if fail else None)
    svc.send_subscription = AsyncMock(return_value=object())
    return svc


async def test_connect_sends_the_card_when_widgets_are_on():
    dm, svc = _dm(make_user(subscription=make_subscription())), _widgets(True)
    await unwrap_inject(on_connect_open)(MagicMock(), MagicMock(), dm, svc)
    svc.send_connect.assert_awaited_once()
    dm.switch_to.assert_not_awaited()


async def test_connect_opens_the_submenu_when_widgets_are_off_or_fail():
    for svc in (_widgets(False), _widgets(True, fail=True)):
        dm = _dm(make_user(subscription=make_subscription()))
        await unwrap_inject(on_connect_open)(MagicMock(), MagicMock(), dm, svc)
        dm.switch_to.assert_awaited_once_with(MainMenu.CONNECT)


async def test_subscription_sends_a_card_or_opens_the_dialog():
    dm, svc = _dm(make_user()), _widgets(True)
    await unwrap_inject(on_subscription_open)(MagicMock(), MagicMock(), dm, svc)
    svc.send_subscription.assert_awaited_once()
    dm.start.assert_not_awaited()

    dm, svc = _dm(make_user()), _widgets(False)
    await unwrap_inject(on_subscription_open)(MagicMock(), MagicMock(), dm, svc)
    dm.start.assert_awaited_once_with(Subscription.MAIN)
    svc.send_subscription.assert_not_awaited()
