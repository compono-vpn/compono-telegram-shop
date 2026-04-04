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
    # --- Always visible (read-only / emergency ops) ---
    # Statistics: read-only analytics, safe to keep visible.
    # Users: MUST stay enabled for emergency user management (block abusers,
    # inspect subscriptions, grant access).  This is a runtime-safety escape
    # hatch that cannot wait for a Django admin panel.
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
    # Admin flows (broadcast, promocodes, access, remnashop, remnawave,
    # importer) have been removed.  Use the admin portal instead.
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Dashboard.MAIN,
)

router = Dialog(dashboard)
