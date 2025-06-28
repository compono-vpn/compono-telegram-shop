from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import (
    Button,
    Row,
    ScrollingGroup,
    Select,
    Start,
    SwitchTo,
)
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from app.bot.states import Dashboard, DashboardUsers
from app.bot.widgets import Banner, I18nFormat, IgnoreUpdate
from app.core.enums import BannerName

from .getters import blacklist_getter
from .handlers import on_unblock_all, on_user_search, on_user_selected

users = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-users-main"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-users-search"),
            id="search",
            state=DashboardUsers.SEARCH,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-users-recent-registered"),
            id="recent_registered",
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-users-recent-activity"),
            id="recent_activity",
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-users-blacklist"),
            id="blacklist",
            state=DashboardUsers.BLACKLIST,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back"),
            id="back",
            state=Dashboard.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUsers.MAIN,
)

search = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-users-search"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardUsers.MAIN,
        ),
    ),
    MessageInput(func=on_user_search),
    IgnoreUpdate(),
    state=DashboardUsers.SEARCH,
)


blacklist = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-users-blacklist"),
    ScrollingGroup(
        Select(
            text=Format("{item.telegram_id} ({item.name})"),
            id="user",
            item_id_getter=lambda item: item.telegram_id,
            items="blocked_users",
            type_factory=int,
            on_click=on_user_selected,
        ),
        id="scroll",
        width=1,
        height=7,
        hide_on_single_page=True,
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-users-unblock-all"),
            id="unblock_all",
            state=DashboardUsers.UNBLOCK_ALL,
            when=F["blocked_users_exists"],
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardUsers.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUsers.BLACKLIST,
    getter=blacklist_getter,
)

unblock_all = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-users-unblock-all"),
    Row(
        Button(
            text=I18nFormat("btn-users-unblock-all-confirm"),
            id="unblock_all_confirm",
            on_click=on_unblock_all,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back"),
            id="back",
            state=DashboardUsers.BLACKLIST,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardUsers.UNBLOCK_ALL,
)


router = Dialog(
    users,
    search,
    blacklist,
    unblock_all,
)
