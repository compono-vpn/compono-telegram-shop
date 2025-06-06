import logging

from aiogram.types import CallbackQuery
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.kbd import Button, Row, Start, SwitchTo
from remnawave_api import RemnawaveSDK

from app.bot.states import DashboardState, RemnawaveState
from app.bot.widgets import Banner, I18nFormat, IgnoreInput
from app.core.constants import REMNAWAVE_KEY
from app.core.enums import BannerName

from .getters import (
    hosts_getter,
    inbounds_getter,
    nodes_getter,
    system_getter,
    users_getter,
)

logger = logging.getLogger(__name__)


async def on_click(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
):
    remnawave: RemnawaveSDK = dialog_manager.middleware_data.get(REMNAWAVE_KEY)

    try:
        response = await remnawave.system.get_stats()
    except Exception as exception:
        logger.error(f"Remnawave: {exception}")
        # TODO: service notification
        await callback.message.answer(f"Failed to connect to Remnawave. {response}")
        return

    await dialog_manager.start(
        RemnawaveState.main,
    )


remnawave = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnawave"),
    Row(
        SwitchTo(
            I18nFormat("btn-remnawave-users"),
            id="remnawave.users",
            state=RemnawaveState.users,
        )
    ),
    Row(
        SwitchTo(
            I18nFormat("btn-remnawave-hosts"),
            id="remnawave.hosts",
            state=RemnawaveState.hosts,
        ),
        SwitchTo(
            I18nFormat("btn-remnawave-nodes"),
            id="remnawave.nodes",
            state=RemnawaveState.nodes,
        ),
        SwitchTo(
            I18nFormat("btn-remnawave-inbounds"),
            id="remnawave.inbounds",
            state=RemnawaveState.inbounds,
        ),
    ),
    Row(
        Start(
            I18nFormat("btn-back"),
            id="back.dashboard",
            state=DashboardState.main,
        )
    ),
    IgnoreInput(),
    state=RemnawaveState.main,
    getter=system_getter,
)

users = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnawave-users"),
    Row(
        SwitchTo(
            I18nFormat("btn-back"),
            id="back.remnawave",
            state=RemnawaveState.main,
        )
    ),
    IgnoreInput(),
    state=RemnawaveState.users,
    getter=users_getter,
)

hosts = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnawave-hosts"),
    Row(
        SwitchTo(
            I18nFormat("btn-back"),
            id="back.remnawave",
            state=RemnawaveState.main,
        )
    ),
    IgnoreInput(),
    state=RemnawaveState.hosts,
    getter=hosts_getter,
)

nodes = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnawave-nodes"),
    Row(
        SwitchTo(
            I18nFormat("btn-back"),
            id="back.remnawave",
            state=RemnawaveState.main,
        )
    ),
    IgnoreInput(),
    state=RemnawaveState.nodes,
    getter=nodes_getter,
)

inbounds = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnawave-inbounds"),
    Row(
        SwitchTo(
            I18nFormat("btn-back"),
            id="back.remnawave",
            state=RemnawaveState.main,
        )
    ),
    IgnoreInput(),
    state=RemnawaveState.inbounds,
    getter=inbounds_getter,
)


router = Dialog(
    remnawave,
    users,
    hosts,
    nodes,
    inbounds,
)
