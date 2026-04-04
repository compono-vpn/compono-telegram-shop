from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.kbd import Row, Start

from src.bot.keyboards import back_main_menu_button
from src.bot.states import (
    Dashboard,
    DashboardStatistics,
    DashboardUsers,
)
from src.bot.widgets import Banner, I18nFormat, IgnoreUpdate
from src.core.enums import BannerName

dashboard = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-dashboard-main"),
    # Statistics: read-only analytics.
    # Users: emergency user management (block abusers, inspect subscriptions,
    # grant access).  Kept as a runtime-safety escape hatch until the Django
    # admin panel covers these operations.
    Row(
        Start(
            text=I18nFormat("btn-dashboard-statistics"),
            id="statistics",
            state=DashboardStatistics.MAIN,
        ),
        Start(
            text=I18nFormat("btn-dashboard-users"),
            id="users",
            state=DashboardUsers.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    # All other admin flows (broadcast, promocodes, access, gateway config,
    # importer, etc.) have been removed.  Use the web admin portal instead.
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Dashboard.MAIN,
)

router = Dialog(dashboard)
