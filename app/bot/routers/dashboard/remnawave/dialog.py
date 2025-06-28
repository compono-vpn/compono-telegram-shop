from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.kbd import Row, Start, SwitchTo

from app.bot.states import Dashboard, DashboardRemnawave
from app.bot.widgets import Banner, I18nFormat, IgnoreUpdate
from app.core.enums import BannerName

from .getters import (
    hosts_getter,
    inbounds_getter,
    nodes_getter,
    system_getter,
    users_getter,
)

remnawave = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnawave-main"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-remnawave-users"),
            id="users",
            state=DashboardRemnawave.USERS,
        )
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-remnawave-hosts"),
            id="hosts",
            state=DashboardRemnawave.HOSTS,
        ),
        SwitchTo(
            text=I18nFormat("btn-remnawave-nodes"),
            id="nodes",
            state=DashboardRemnawave.NODES,
        ),
        SwitchTo(
            text=I18nFormat("btn-remnawave-inbounds"),
            id="inbounds",
            state=DashboardRemnawave.INBOUNDS,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back"),
            id="back",
            state=Dashboard.MAIN,
            mode=StartMode.RESET_STACK,
        )
    ),
    IgnoreUpdate(),
    state=DashboardRemnawave.MAIN,
    getter=system_getter,
)

users = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnawave-users"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardRemnawave.MAIN,
        )
    ),
    IgnoreUpdate(),
    state=DashboardRemnawave.USERS,
    getter=users_getter,
)

hosts = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnawave-hosts"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardRemnawave.MAIN,
        )
    ),
    IgnoreUpdate(),
    state=DashboardRemnawave.HOSTS,
    getter=hosts_getter,
)

nodes = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnawave-nodes"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardRemnawave.MAIN,
        )
    ),
    IgnoreUpdate(),
    state=DashboardRemnawave.NODES,
    getter=nodes_getter,
)

inbounds = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-remnawave-inbounds"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardRemnawave.MAIN,
        )
    ),
    IgnoreUpdate(),
    state=DashboardRemnawave.INBOUNDS,
    getter=inbounds_getter,
)


router = Dialog(
    remnawave,
    users,
    hosts,
    nodes,
    inbounds,
)
