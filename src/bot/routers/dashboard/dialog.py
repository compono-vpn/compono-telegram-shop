from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.kbd import Row, Start
from magic_filter import F

from src.bot.filters.admin_gate import admin_enabled_condition
from src.bot.keyboards import back_main_menu_button
from src.bot.states import (
    Dashboard,
    DashboardAccess,
    DashboardBroadcast,
    DashboardImporter,
    DashboardPromocodes,
    DashboardRemnashop,
    DashboardRemnawave,
    DashboardStatistics,
    DashboardUsers,
)
from src.bot.widgets import Banner, I18nFormat, IgnoreUpdate
from src.core.constants import IS_SUPER_DEV_KEY, MIDDLEWARE_DATA_KEY, USER_KEY
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
    # --- Gated by SHOP_ADMIN_ENABLED ---
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
        when=admin_enabled_condition,
    ),
    Row(
        Start(
            text=I18nFormat("btn-dashboard-access"),
            id="access",
            state=DashboardAccess.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        when=admin_enabled_condition,
    ),
    Row(
        Start(
            text=I18nFormat("btn-dashboard-remnawave"),
            id="remnawave",
            state=DashboardRemnawave.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        Start(
            text=I18nFormat("btn-dashboard-remnashop"),
            id="remnashop",
            state=DashboardRemnashop.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        when=F[MIDDLEWARE_DATA_KEY][USER_KEY].is_dev & admin_enabled_condition,
    ),
    Row(
        Start(
            text=I18nFormat("btn-dashboard-importer"),
            id="importer",
            state=DashboardImporter.MAIN,
        ),
        when=F[MIDDLEWARE_DATA_KEY][IS_SUPER_DEV_KEY] & admin_enabled_condition,
    ),
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Dashboard.MAIN,
)

router = Dialog(dashboard)
