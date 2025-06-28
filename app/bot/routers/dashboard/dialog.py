from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.kbd import Button, Column, Row, Select, Start, SwitchTo
from magic_filter import F

from app.bot.conditions import is_dev
from app.bot.routers.dashboard.getters import maintenance_getter
from app.bot.states import (
    Dashboard,
    DashboardBroadcast,
    DashboardPromocodes,
    DashboardRemnashop,
    DashboardUsers,
    MainMenu,
)
from app.bot.widgets import Banner, I18nFormat, IgnoreUpdate
from app.core.enums import BannerName, MaintenanceMode

from .handlers import on_maintenance_mode_selected
from .remnawave.handlers import start_remnawave_window

dashboard = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-dashboard-main"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-dashboard-statistics"),
            id="statistics",
            state=Dashboard.STATISTICS,
        ),
        Start(
            text=I18nFormat("btn-dashboard-users"),
            id="users",
            state=DashboardUsers.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-dashboard-broadcast"),
            id="broadcast",
            state=DashboardBroadcast.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        Start(
            text=I18nFormat("btn-dashboard-promocodes"),
            id="promocodes",
            state=DashboardPromocodes.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-dashboard-maintenance"),
            id="maintenance",
            state=Dashboard.MAINTENANCE,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-dashboard-remnawave"),
            id="remnawave",
            on_click=start_remnawave_window,
        ),
        Start(
            text=I18nFormat("btn-dashboard-remnashop"),
            id="remnashop",
            state=DashboardRemnashop.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        when=is_dev,
    ),
    Row(
        Start(
            text=I18nFormat("btn-back-menu"),
            id="back",
            state=MainMenu.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=Dashboard.MAIN,
)

statistics = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-statistics-main"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=Dashboard.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=Dashboard.STATISTICS,
)

maintenance = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-maintenance-main"),
    Column(
        Select(
            text=I18nFormat("btn-maintenance-mode", mode=F["item"]),
            id="mode",
            item_id_getter=lambda item: item.value,
            items="modes",
            type_factory=MaintenanceMode,
            on_click=on_maintenance_mode_selected,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=Dashboard.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=Dashboard.MAINTENANCE,
    getter=maintenance_getter,
)

router = Dialog(
    dashboard,
    statistics,
    maintenance,
)
