"""Only an ADMIN or DEV may open or use the admin dialogs (Dashboard*).

They change a user's role (a DEV has every Stars payment refunded at once while billing still
completes the order) and grant subscriptions. Callback data is not trusted: «Перейти к
пользователю» (gt_DashboardUser:MAIN:<id>) and the main menu's hidden «dashboard» button worked
for any user who sent that data, and nothing inside the dialogs checked the role.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.filters import PrivilegedFilter
from src.bot.routers.extra.goto import on_goto
from src.bot.routers.menu.handlers import on_open_dashboard
from src.core.constants import USER_KEY
from tests.conftest import make_user

pytestmark = pytest.mark.asyncio


def _user(role: str):
    return make_user(telegram_id=31337).model_copy(update={"role": role})


@pytest.mark.parametrize("data", ["gt_DashboardUser:MAIN:31337", "gt_Dashboard:MAIN"])
async def test_goto_into_an_admin_dialog_is_refused_for_a_user(data):
    callback = MagicMock(data=data)
    callback.answer = AsyncMock()
    dm = MagicMock()
    await on_goto(callback, dm, _user("USER"))
    dm.bg.assert_not_called()


async def test_goto_into_an_admin_dialog_still_works_for_an_admin():
    callback = MagicMock(data="gt_DashboardUser:MAIN:42")
    callback.answer = AsyncMock()
    dm = MagicMock()
    dm.bg.return_value.start = AsyncMock()
    await on_goto(callback, dm, _user("ADMIN"))
    dm.bg.return_value.start.assert_awaited_once()


@pytest.mark.parametrize("role, opened", [("USER", False), ("ADMIN", True), ("DEV", True)])
async def test_dashboard_button_opens_only_for_privileged(role, opened):
    dm = MagicMock()
    dm.start = AsyncMock()
    dm.middleware_data = {USER_KEY: _user(role)}
    await on_open_dashboard(AsyncMock(), MagicMock(), dm)
    assert dm.start.await_count == (1 if opened else 0)


@pytest.mark.parametrize("role, allowed", [("USER", False), ("ADMIN", True), ("DEV", True)])
async def test_filter_lets_only_privileged_users_into_admin_dialogs(role, allowed):
    assert await PrivilegedFilter()(MagicMock(), **{USER_KEY: _user(role)}) is allowed
    assert await PrivilegedFilter()(MagicMock()) is False
