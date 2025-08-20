from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Row, Start

from src.bot.routers.dashboard.users.handlers import on_user_search
from src.bot.routers.extra.test import show_dev_popup
from src.bot.states import Dashboard, MainMenu, Subscription
from src.bot.widgets import Banner, I18nFormat, IgnoreUpdate
from src.core.enums import BannerName

from .getters import menu_getter

menu = Window(
    Banner(BannerName.MENU),
    I18nFormat("msg-menu-profile"),
    I18nFormat("separator"),
    I18nFormat("msg-menu-subscription"),
    # Row(
    #     Button(
    #         text=I18nFormat(ButtonKey.CONNECT),
    #         id="connect",
    #     ),
    # ),
    # Row(
    #     Button(
    #         text=I18nFormat(ButtonKey.TRIAL),
    #         id="trial",
    #     ),
    # ),
    Row(
        # Button(
        #     text=I18nFormat(ButtonKey.PROMOCODE),
        #     id="promocode",
        # ),
        Start(
            text=I18nFormat("btn-menu-subscription"),
            id="subscription",
            state=Subscription.MAIN,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-menu-invite"),
            id="invite",
            on_click=show_dev_popup,
        ),
        Button(
            text=I18nFormat("btn-menu-support"),
            id="support",
            on_click=show_dev_popup,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-menu-dashboard"),
            id="dashboard",
            state=Dashboard.MAIN,
            mode=StartMode.RESET_STACK,
            when="is_privileged",
        ),
    ),
    MessageInput(func=on_user_search),
    IgnoreUpdate(),
    state=MainMenu.MAIN,
    getter=menu_getter,
)

router = Dialog(
    menu,
)
